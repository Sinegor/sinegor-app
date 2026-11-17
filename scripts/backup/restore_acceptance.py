"""Accept one exact backup in disposable, offline containers; never reads project dotenv.

Run as root with RESTIC_REPOSITORY and RESTIC_PASSWORD_FILE supplied explicitly.
All images must already exist locally and be identified by immutable sha256 IDs.
Application compatibility checks are mandatory. Tool output stays in memory.
"""
import argparse
import base64
import json
import os
import re
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
LABEL = "sinegor.restore-acceptance.run"
MARKER = ".sinegor-restore-acceptance"
PGDATA = "/var/lib/postgresql/data"
API_TABLES = (
    "alembic_version", "customers", "orders", "agreements", "admin_users",
    "auth_tokens", "sessions", "auth_rate_limits", "notifications",
    "security_events", "order_events", "customer_events", "disk_folders",
    "material_handovers", "payment_records", "deletion_requests",
    "retention_file_deletions", "agreement_file_deletions",
    "analytics_consent_events", "destruction_operations",
)
CMS_TABLES = (
    "files", "pages", "public_documents", "publications", "services",
    "footer_settings", "strapi_core_store_settings",
)


class AcceptanceError(Exception):
    """A safe error category; upstream output is deliberately excluded."""


def require_root():
    if os.geteuid() != 0:
        raise AcceptanceError("RootRequired")


def private_root(path):
    path = Path(path).absolute()
    if path.resolve() != path or not path.is_dir():
        raise AcceptanceError("PrivateRootInvalid")
    metadata = path.stat()
    if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) & 0o077:
        raise AcceptanceError("PrivateRootPermissions")
    return path


def image_id(value):
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        raise AcceptanceError("ExactLocalImageRequired")
    return value


def snapshot_from_receipt(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise AcceptanceError("ReceiptInvalid")
    receipt = json.loads(path.read_text())
    snapshot = receipt.get("snapshot")
    if (receipt.get("version") != 1 or receipt.get("verified") is not True
            or not isinstance(snapshot, str) or not re.fullmatch(r"[0-9a-f]{64}", snapshot)):
        raise AcceptanceError("ReceiptInvalid")
    return snapshot


def isolated_environment(private, parent):
    if not parent.get("RESTIC_REPOSITORY") or not parent.get("RESTIC_PASSWORD_FILE"):
        raise AcceptanceError("ResticEnvironmentMissing")
    return {
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "HOME": str(private), "TMPDIR": str(private),
        "SINEGOR_ENV_FILE": "/dev/null", "PYTHONDONTWRITEBYTECODE": "1",
        "RESTIC_REPOSITORY": parent["RESTIC_REPOSITORY"],
        "RESTIC_PASSWORD_FILE": parent["RESTIC_PASSWORD_FILE"],
        "RESTIC_CACHE_DIR": str(private / "restic-cache"),
    }


def call(command, *, env=None, data=None, timeout=900):
    process = None
    try:
        process = subprocess.Popen(
            [str(item) for item in command], env=env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
        )
        output, _ = process.communicate(data, timeout=timeout)
        if process.returncode:
            raise AcceptanceError("ToolFailed")
        return output
    except BaseException as error:
        if process is not None:
            # The parent may already have exited while descendants retain its pipes.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
        if isinstance(error, AcceptanceError):
            raise
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        raise AcceptanceError("ToolTimeout" if isinstance(error, subprocess.TimeoutExpired)
                              else "ToolUnavailable") from None


def write_private(path, value):
    with path.open("x", encoding="utf-8") as output:
        os.chmod(path, 0o600)
        output.write(value)


def make_private(root, run_id):
    if not re.fullmatch(r"[0-9a-f]{12}", run_id):
        raise AcceptanceError("RunIdentityInvalid")
    root = private_root(root)
    private = root / ("sinegor-restore-" + run_id)
    private.mkdir(mode=0o700)
    write_private(private / MARKER, run_id)
    return private


def remove_private(root, private, run_id):
    root = private_root(root)
    expected = root / ("sinegor-restore-" + run_id)
    private = Path(private)
    if private != expected or private.resolve() != expected or not private.is_dir():
        raise AcceptanceError("CleanupPathInvalid")
    marker = private / MARKER
    if (marker.is_symlink() or not marker.is_file() or marker.stat().st_size != 12
            or marker.read_text() != run_id
            or private.stat().st_uid != os.geteuid()
            or stat.S_IMODE(private.stat().st_mode) != 0o700
            or not shutil.rmtree.avoids_symlink_attacks):
        raise AcceptanceError("CleanupMarkerInvalid")
    shutil.rmtree(private)


def container_base(run_id, name, image, network, env_file):
    return [
        "docker", "create", "--pull=never", "--name", name,
        "--label", LABEL + "=" + run_id, "--network=" + network,
        "--log-driver=none", "--no-healthcheck", "--memory=768m", "--pids-limit=128",
        "--security-opt=no-new-privileges", "--env-file", str(env_file),
    ]


def postgres_command(run_id, image, env_file):
    return [
        *container_base(run_id, "sinegor-backup-test-" + run_id, image, "none", env_file),
        "--mount", "type=tmpfs,destination=" + PGDATA + ",tmpfs-size=536870912",
        image,
    ]


def validate_container(inspected, expected, run_id):
    host = inspected["HostConfig"]
    actual_mounts = sorted(
        (item["Type"], item.get("Source", ""), item["Destination"], item["RW"])
        for item in inspected.get("Mounts", [])
    )
    networks = inspected.get("NetworkSettings", {}).get("Networks") or {}
    if any(name != "none" or any(settings.get(key) for key in (
            "IPAddress", "Gateway", "GlobalIPv6Address", "IPv6Gateway"))
           for name, settings in networks.items()):
        raise AcceptanceError("ContainerOutsideNetwork")
    ports = inspected.get("NetworkSettings", {}).get("Ports") or {}
    if (
        inspected["Id"] != expected["id"]
        or inspected["Name"] != "/" + expected["name"]
        or inspected["Config"].get("Labels", {}).get(LABEL) != run_id
        or inspected["Config"]["Image"] != expected["image"]
        or host["NetworkMode"] != expected["network"]
        or host.get("PortBindings") or host.get("Binds") or host.get("Privileged")
        or any(value for value in ports.values())
        or actual_mounts != sorted(expected["mounts"])
    ):
        raise AcceptanceError("ContainerIsolationMismatch")


class Fixture:
    def __init__(self, run_id, private, environment):
        self.run_id, self.private, self.environment = run_id, private, environment
        self.containers = []
        self.pending_create = False
        self.postgres = None

    def inspect(self, expected):
        results = json.loads(call(["docker", "inspect", expected["id"]], env=self.environment))
        if not isinstance(results, list) or len(results) != 1:
            raise AcceptanceError("ContainerInspectionInvalid")
        validate_container(results[0], expected, self.run_id)

    def create(self, command, *, name, image, network, mounts):
        # Creation before start allows verifying isolation before executing image code.
        self.pending_create = True
        identity = call(command, env=self.environment).decode().strip()
        if not re.fullmatch(r"[0-9a-f]{64}", identity):
            raise AcceptanceError("ContainerIdentityInvalid")
        expected = {"id": identity, "name": name, "image": image,
                    "network": network, "mounts": mounts}
        self.containers.append(expected)
        self.pending_create = False
        self.inspect(expected)
        return expected

    def start(self, expected, *, attached=False):
        self.inspect(expected)
        command = ["docker", "start"]
        if attached:
            command.append("-a")
        output = call([*command, expected["id"]], env=self.environment, timeout=600)
        self.inspect(expected)
        if attached:
            code = call(
                ["docker", "inspect", "--format", "{{.State.ExitCode}}", expected["id"]],
                env=self.environment,
            )
            if code.strip() != b"0":
                raise AcceptanceError("ApplicationCompatibilityFailed")
        return output

    def sql(self, database, query, *, readonly=True):
        if not re.fullmatch(r"[a-z0-9_]+", database):
            raise AcceptanceError("FixtureDatabaseInvalid")
        self.inspect(self.postgres)
        sql = "BEGIN READ ONLY;\n" + query + ";\nCOMMIT;" if readonly else query
        return call(
            ["docker", "exec", "-i", self.postgres["id"], "timeout", "180",
             "psql", "-X", "-w", "-qAt", "-v", "ON_ERROR_STOP=1",
             "-U", "fixture", "-d", database],
            env=self.environment, data=sql.encode(), timeout=200,
        )

    def query(self, database, query):
        return json.loads(self.sql(database, query))


def cleanup(fixture, work_root):
    try:
        # Validate every owned identity before beginning destructive cleanup.
        for expected in reversed(fixture.containers):
            fixture.inspect(expected)
        for expected in reversed(fixture.containers):
            call(["docker", "rm", "-f", expected["id"]], env=fixture.environment)
            remaining = call(
                ["docker", "ps", "-aq", "--no-trunc", "--filter", "id=" + expected["id"]],
                env=fixture.environment,
            )
            if remaining.strip():
                raise AcceptanceError("ContainerRemovalUnconfirmed")
        remaining = call(
            ["docker", "ps", "-aq", "--no-trunc", "--filter", "label=" + LABEL + "=" + fixture.run_id],
            env=fixture.environment,
        )
        if fixture.pending_create or remaining.strip():
            raise AcceptanceError("UntrackedFixtureContainer")
        remove_private(work_root, fixture.private, fixture.run_id)
        return True
    except BaseException:
        # Uncertainty retains all confidential files in the exact private directory.
        return False


def new_report():
    return {"version": 1, "success": False, "stages": [], "counts": {}, "cleanup": False}


def record_failure(report, error):
    report["error_type"] = type(error).__name__


def check_schema(fixture, database, tables):
    names = ",".join("'" + name + "'" for name in tables)
    result = fixture.query(database, """
        SELECT json_build_object(
          'tables', (SELECT count(*) FROM pg_tables WHERE schemaname='public'),
          'missing_tables', (SELECT count(*) FROM unnest(ARRAY[%s]) x
                            WHERE to_regclass('public.' || x) IS NULL),
          'constraints', (SELECT count(*) FROM pg_constraint c JOIN pg_namespace n
                         ON n.oid=c.connamespace WHERE n.nspname='public'),
          'foreign_keys', (SELECT count(*) FROM pg_constraint c JOIN pg_namespace n
                          ON n.oid=c.connamespace WHERE n.nspname='public' AND c.contype='f'),
          'invalid_constraints', (SELECT count(*) FROM pg_constraint c JOIN pg_namespace n
                                 ON n.oid=c.connamespace WHERE n.nspname='public'
                                 AND NOT c.convalidated))
    """ % names)
    if result["missing_tables"] or result["invalid_constraints"] or not result["foreign_keys"]:
        raise AcceptanceError("RestoredSchemaInvalid")
    # Read-only orphan checks include every restored public-schema foreign key.
    checks = fixture.query(database, """
        SELECT coalesce(json_agg(q), '[]') FROM (
          SELECT format(
            'SELECT count(*) FROM %%I.%%I c WHERE %%s AND NOT EXISTS '
            '(SELECT 1 FROM %%I.%%I p WHERE %%s)',
            nc.nspname, child.relname,
            string_agg(format('c.%%I IS NOT NULL', ac.attname), ' AND ' ORDER BY k.ordinality),
            np.nspname, parent.relname,
            string_agg(format('c.%%I = p.%%I', ac.attname, ap.attname),
                       ' AND ' ORDER BY k.ordinality)) q
          FROM pg_constraint fk
          JOIN pg_class child ON child.oid=fk.conrelid
          JOIN pg_namespace nc ON nc.oid=child.relnamespace
          JOIN pg_class parent ON parent.oid=fk.confrelid
          JOIN pg_namespace np ON np.oid=parent.relnamespace
          CROSS JOIN LATERAL unnest(fk.conkey, fk.confkey)
               WITH ORDINALITY AS k(childkey, parentkey, ordinality)
          JOIN pg_attribute ac ON ac.attrelid=child.oid AND ac.attnum=k.childkey
          JOIN pg_attribute ap ON ap.attrelid=parent.oid AND ap.attnum=k.parentkey
          WHERE fk.contype='f' AND nc.nspname='public'
          GROUP BY fk.oid, nc.nspname, child.relname, np.nspname, parent.relname
        ) checks
    """.replace("%%", "%"))
    invalid = sum(int(fixture.sql(database, check).strip()) for check in checks)
    if invalid:
        raise AcceptanceError("RestoredForeignKeysInvalid")
    result["orphan_rows"] = invalid
    return result


def application_environment(password, api_database, cms_database):
    api = {
        "APP_ENV": "test", "SINEGOR_ENV_FILE": "/dev/null", "LOG_LEVEL": "CRITICAL",
        "DATABASE_URL": "postgresql+psycopg://fixture:" + password + "@127.0.0.1:5432/" + api_database,
        "SESSION_SECRET": secrets.token_urlsafe(48),
        "AUTH_ENCRYPTION_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        "AGREEMENT_STORAGE_DIR": "/var/lib/sinegor/agreements",
        "DESTRUCTION_ARCHIVE_DIR": "/var/lib/sinegor/destruction",
        "SMTP_HOST": "127.0.0.1", "SMTP_USERNAME": "", "SMTP_PASSWORD": "",
        "SMTP_FROM": "", "NOTIFICATION_ADMIN_EMAIL": "", "TELEGRAM_BOT_TOKEN": "",
        "TELEGRAM_ADMIN_CHAT_ID": "", "YANDEX_DISK_TOKEN": "", "YANDEX_DISK_ROOT": "",
    }
    cms = {
        "ENV_PATH": "/dev/null", "NODE_ENV": "production", "HOST": "127.0.0.1", "PORT": "1337",
        "CMS_PUBLIC_ORIGIN": "http://127.0.0.1:1337", "CMS_BEHIND_PROXY": "false",
        "DATABASE_HOST": "127.0.0.1", "DATABASE_PORT": "5432", "DATABASE_NAME": cms_database,
        "DATABASE_USERNAME": "fixture", "DATABASE_PASSWORD": password, "DATABASE_SSL": "false",
        "STRAPI_TELEMETRY_DISABLED": "true", "STRAPI_DISABLE_UPDATE_NOTIFICATION": "true",
    }
    for key in ("APP_KEYS", "ADMIN_JWT_SECRET", "API_TOKEN_SALT", "TRANSFER_TOKEN_SALT",
                "ENCRYPTION_KEY", "JWT_SECRET"):
        cms[key] = secrets.token_urlsafe(48)
    return api, cms


def env_text(values):
    if any("\n" in str(value) or "\r" in str(value) for value in values.values()):
        raise AcceptanceError("SyntheticEnvironmentInvalid")
    return "".join(key + "=" + str(value) + "\n" for key, value in values.items())


def restore_environment(private, environment, container, project_root):
    return environment | {
        "PATH": str(private / "bin") + os.pathsep + environment["PATH"],
        "PGSERVICEFILE": str(private / "pg_service.conf"),
        "PGPASSFILE": str(private / "pgpass"),
        "SINEGOR_BACKUP_TEST_CONTAINER": container,
        "PYTHONPATH": str(project_root / "apps/api/src"),
    }


def acceptance(args, fixture, report):
    private, run_id = fixture.private, fixture.run_id
    env = fixture.environment
    for image in (args.postgres_image, args.api_image, args.cms_image):
        metadata = json.loads(call(["docker", "image", "inspect", image], env=env))
        if len(metadata) != 1 or metadata[0]["Id"] != image:
            raise AcceptanceError("LocalImageMismatch")
    report["stages"].append("exact_local_images_available")
    password = secrets.token_urlsafe(36)
    write_private(private / "postgres.env",
                  env_text({"POSTGRES_USER": "fixture", "POSTGRES_PASSWORD": password, "POSTGRES_DB": "postgres"}))
    pg = fixture.create(
        postgres_command(run_id, args.postgres_image, private / "postgres.env"),
        name="sinegor-backup-test-" + run_id, image=args.postgres_image,
        network="none", mounts=[("tmpfs", "", PGDATA, True)],
    )
    fixture.postgres = pg
    fixture.start(pg)
    deadline = time.monotonic() + 60
    while True:
        try:
            if fixture.sql("postgres", "SELECT 1").strip() == b"1":
                break
        except AcceptanceError:
            if time.monotonic() >= deadline:
                raise AcceptanceError("PostgresReadinessTimeout") from None
            time.sleep(0.25)
    api_db = "api_" + run_id + "_restore_test"
    cms_db = "cms_" + run_id + "_restore_test"
    fixture.sql("postgres", "CREATE DATABASE " + api_db + ";\nCREATE DATABASE " + cms_db + ";", readonly=False)
    services = "".join(
        "[" + service + "]\nhost=127.0.0.1\nport=5432\nuser=fixture\ndbname=" + database + "\n"
        for service, database in (("restore_api", api_db), ("restore_cms", cms_db))
    )
    write_private(private / "pg_service.conf", services)
    write_private(private / "pgpass", "127.0.0.1:5432:*:fixture:" + password + "\n")
    for name in ("pg_service.conf", "pgpass"):
        call(["docker", "cp", str(private / name), pg["id"] + ":/tmp/" + name], env=env)
    binaries = private / "bin"
    binaries.mkdir(mode=0o700)
    transport = (HERE / "tests/postgres_cli.py").read_text()
    # A Docker exec client timeout alone does not terminate the daemon-side CLI.
    transport = transport.replace('        program,\n', '        "timeout",\n        "600",\n        program,\n')
    for program in ("psql", "pg_dump", "pg_restore"):
        wrapper = binaries / program
        write_private(wrapper, "#!" + sys.executable + "\n" + transport)
        wrapper.chmod(0o700)
    (binaries / "restic").symlink_to(args.restic)
    restore_env = restore_environment(private, env, pg["name"], args.project_root)
    report["stages"].append("offline_fixture_identity_and_empty_databases")
    restored = private / "restored"
    call([sys.executable, args.backup_tool, "restore-test", "--receipt", args.receipt,
          "--api-service", "restore_api", "--cms-service", "restore_cms", "--target", restored],
         env=restore_env, timeout=1800)
    report["stages"].append("existing_restore_test_exact_snapshot_files_and_database_hashes")
    manifest = json.loads((restored / "manifest.json").read_text())
    report["counts"]["agreement_files"] = sum(name.startswith("agreements/") for name in manifest["files"])
    report["counts"]["media_files"] = sum(name.startswith("media/") for name in manifest["files"])
    report["counts"]["api_schema"] = check_schema(fixture, api_db, API_TABLES)
    report["counts"]["cms_schema"] = check_schema(fixture, cms_db, CMS_TABLES)
    revision = fixture.query(api_db, "SELECT coalesce(json_agg(version_num), '[]') FROM alembic_version")
    if len(revision) != 1 or not isinstance(revision[0], str) or not revision[0]:
        raise AcceptanceError("AlembicRevisionInvalid")
    # Revision values stay private; alembic check below verifies the current image head.
    report["counts"]["alembic_revisions"] = len(revision)
    report["stages"].append("expected_tables_constraints_foreign_keys_and_alembic_revision")
    api_env, cms_env = application_environment(password, api_db, cms_db)
    for role, values in (("api", api_env), ("cms", cms_env)):
        write_private(private / (role + ".env"), env_text(values))
    network = "container:" + pg["id"]
    api_name = "sinegor-restore-api-" + run_id
    api = fixture.create(
        [*container_base(run_id, api_name, args.api_image, network, private / "api.env"),
         "--cap-drop=ALL", "--entrypoint", "python", args.api_image, "-m", "alembic", "check"],
        name=api_name, image=args.api_image, network=network, mounts=[],
    )
    fixture.start(api, attached=True)
    report["stages"].append("current_api_image_alembic_check_no_migration")
    media = private / "cms-media"
    shutil.copytree(restored / "media", media)
    media.chmod(0o755)
    for item in media.rglob("*"):
        if item.is_symlink():
            raise AcceptanceError("RestoredMediaSymlink")
        item.chmod(0o755 if item.is_dir() else 0o644)
    helper = HERE / "restore_cms.cjs"
    cms_name = "sinegor-restore-cms-" + run_id
    cms = fixture.create(
        [*container_base(run_id, cms_name, args.cms_image, network, private / "cms.env"),
         "--cap-drop=ALL",
         "--mount", "type=bind,source=" + str(media) + ",destination=/app/public/uploads,readonly",
         "--mount", "type=bind,source=" + str(helper) + ",destination=/tmp/restore_cms.cjs,readonly",
         "--entrypoint", "node", args.cms_image, "/tmp/restore_cms.cjs"],
        name=cms_name, image=args.cms_image, network=network,
        mounts=[("bind", str(media), "/app/public/uploads", False),
                ("bind", str(helper), "/tmp/restore_cms.cjs", False)],
    )
    fixture.start(cms, attached=True)
    report["stages"].append("current_cms_image_start_and_all_original_derivative_http_hashes")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("receipt", "restic", "work-root", "report"):
        parser.add_argument("--" + name, type=Path, required=True)
    for role in ("postgres", "api", "cms"):
        parser.add_argument("--" + role + "-image", required=True)
    parser.add_argument("--backup-tool", type=Path, default=HERE / "backup.py")
    parser.add_argument("--project-root", type=Path,
                        default=Path("/home/sinegoradmin/apps/sinegor-app"))
    args = parser.parse_args()
    report, fixture, work_root = new_report(), None, None
    os.umask(0o077)
    try:
        require_root()
        for role in ("postgres", "api", "cms"):
            image_id(getattr(args, role + "_image"))
        work_root = private_root(args.work_root)
        snapshot_from_receipt(args.receipt)
        args.receipt = args.receipt.resolve(strict=True)
        args.backup_tool = args.backup_tool.resolve(strict=True)
        args.project_root = args.project_root.resolve(strict=True)
        if (not args.backup_tool.is_file()
                or not (args.project_root / "apps/api/src/sinegor/modules/retention/archive.py").is_file()
                or not (HERE / "tests/postgres_cli.py").is_file()
                or not (HERE / "restore_cms.cjs").is_file()):
            raise AcceptanceError("HelperInstallationInvalid")
        args.restic = args.restic.resolve(strict=True)
        if not args.restic.is_file() or not os.access(args.restic, os.X_OK):
            raise AcceptanceError("ResticExecutableInvalid")
        args.report = args.report.absolute()
        if (args.report.resolve() != args.report or args.report.exists()
                or not args.report.parent.is_dir()
                or args.report.is_relative_to(work_root)):
            raise AcceptanceError("ReportPathInvalid")
        private = make_private(work_root, secrets.token_hex(6))
        fixture = Fixture(private.name.removeprefix("sinegor-restore-"), private, {})
        fixture.environment = isolated_environment(private, os.environ)
        acceptance(args, fixture, report)
        report["success"] = True
    except BaseException as error:
        record_failure(report, error)
    finally:
        if fixture is not None:
            report["cleanup"] = cleanup(fixture, work_root)
        if not report["cleanup"]:
            report["success"] = False
        try:
            with args.report.open("x", encoding="utf-8") as output:
                os.chmod(args.report, 0o600)
                json.dump(report, output, indent=2)
                output.write("\n")
        except (OSError, ValueError):
            report["success"] = False
            report["report_write_failed"] = True
    print(json.dumps(report, sort_keys=True))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    def interrupted(_signum, _frame):
        raise InterruptedError()
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    raise SystemExit(main())
