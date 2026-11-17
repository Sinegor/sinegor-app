#!/usr/bin/python3
"""Prepare reviewed host backup support. No prepare action stops services or enables timers."""
import argparse
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = "sinegor-lab-prod"
PROJECT_ROOT = Path("/home/sinegoradmin/apps/sinegor-app")
PRIVATE = Path("/etc/sinegor/backup")
STATE = Path("/var/lib/sinegor-backup")
LIB = Path("/usr/local/lib/sinegor/backup")
RESTIC = Path("/usr/local/bin/restic")
RESTIC_SOURCE = Path("/home/sinegoradmin/apps/sinegor-app-artifacts/diagnostics/production-iii9-20261117/restic-compatibility/restic")
RESTIC_SHA256 = "20d4142678d0d95ec11a4759def1b73fd9190abc9ca19e4b62d067c0b387e639"
REQUIRED_FREE_BYTES = int(17.75 * 1024 ** 3)  # 4.75GiB plan + 8GiB growth + 5GiB operating floor.
IMAGES = {
    "api": "sha256:5e0106f6a5b0c99b693301dc31c8b872afcbeac76248a1c81d66b068cd4a7488",
    "cms": "sha256:7dce90c402009116cea26cb36c4eb615862274f138fbd14bd7c7c2774eef3802",
    "postgres": "sha256:4b7183ac05f8ef417db21fd72d71047a4238340c261d3cc3ddb6d579ab5071ae",
    "web": "sha256:14974bbd98593514e92a9fe0f229598d3fb075cc153ea576524a014565998b81",
    "proxy": "sha256:c97ff0bf7cbae369953c6da1232ec14ad9f971d66360c5698db0856a4cd657a0",
}
VOLUMES = {
    "api": {"agreements": "/var/lib/sinegor/agreements", "destruction": "/var/lib/sinegor/destruction"},
    "cms": {"cms_uploads": "/app/public/uploads"},
    "postgres": {"postgres_data": "/var/lib/postgresql/data"},
}
UNIT_NAMES = (
    "sinegor-backup.service", "sinegor-backup.timer",
    "sinegor-backup-watchdog.service", "sinegor-backup-watchdog.timer",
    "sinegor-backup-recovery.service",
)
MODULES = ("backup.py", "production.py", "postgres_cli.py", "restore_acceptance.py",
           "restore_cms.cjs", "tests/postgres_cli.py")
ENV_ROOT = Path("/home/sinegoradmin/apps/sinegor-app-private")
ENV_NAMES = ("api.env", "cms.env", "compose.env", "security-cleanup.env")


class InstallError(Exception):
    """Sanitized operator diagnostic; subprocess output and secrets are excluded."""


def configuration():
    return {
        "version": 1, "project": PROJECT, "project_root": str(PROJECT_ROOT),
        "private_dir": str(PRIVATE), "state_dir": str(STATE),
        "repository": str(STATE / "repository"), "restic": str(RESTIC),
        "restic_password_file": str(PRIVATE / "restic-password"),
        "activation_approved": False, "resume_timeout": 180, "writer_uid": 10001,
        "postgres_container": PROJECT + "-postgres-1", "images": dict(IMAGES),
        "sources": {
            key: "/var/lib/docker/volumes/" + PROJECT + "_" + volume + "/_data"
            for key, volume in (("agreements", "agreements"), ("uploads", "cms_uploads"),
                                ("destruction", "destruction"))
        },
    }


def require_absent(path):
    if Path(path).exists() or Path(path).is_symlink():
        raise InstallError("Unrelated or partial target already exists; manual inspection required")


def check_space(free):
    if free < REQUIRED_FREE_BYTES:
        raise InstallError("Free space is below the 17.75 GiB preparation budget")


def file_bytes(path, *, private=False, owners=(0,)):
    path = Path(path)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as source:
            info = os.fstat(source.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or (private and (info.st_uid not in owners
                                     or stat.S_IMODE(info.st_mode) != 0o600))
                    or info.st_size > 32 * 1024 ** 2):
                raise InstallError("Unsafe installation source or private file")
            return source.read()
    except OSError:
        raise InstallError("Required installation source or private file is unavailable") from None


def digest(path):
    return hashlib.sha256(file_bytes(path)).hexdigest()


def write_new(path, content, *, mode=0o600):
    path = Path(path)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
        with os.fdopen(fd, "wb") as output:
            output.write(content.encode() if isinstance(content, str) else content)
            os.fchmod(output.fileno(), mode)
            output.flush()
            os.fsync(output.fileno())
    except OSError:
        raise InstallError("Cannot exclusively create an installation target") from None


def atomic_json(path, value):
    path = Path(path)
    name = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False, mode="w") as output:
            name = Path(output.name)
            json.dump(value, output, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if name is not None:
            name.unlink(missing_ok=True)


def command(argv, *, input_text=None, timeout=30, env=None):
    process = None
    try:
        process = subprocess.Popen(argv, stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, start_new_session=True, env=env)
        output, _ = process.communicate(input_text, timeout=timeout)
        if process.returncode:
            raise InstallError("Preparation command failed; tool output suppressed")
        return output
    except (OSError, subprocess.TimeoutExpired):
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
        raise InstallError("Preparation command unavailable or timed out") from None


def mail_settings(env):
    recipient = env.get("NOTIFICATION_ADMIN_EMAIL", "").strip()
    sender = (env.get("SMTP_FROM_EMAIL") or env.get("SMTP_FROM") or "").strip()
    if not recipient or "\n" in recipient or "\r" in recipient or "@" not in recipient:
        raise InstallError("Administrator email recipient is missing or invalid")
    if not sender or "\n" in sender or "\r" in sender or "@" not in sender:
        raise InstallError("SMTP sender is missing or invalid")
    try:
        port = int(env.get("SMTP_PORT", ""))
    except ValueError:
        raise InstallError("SMTP port is invalid") from None
    boolean = str(env.get("SMTP_USE_SSL", "")).lower()
    if (not env.get("SMTP_HOST") or not 1 <= port <= 65535
            or boolean not in {"true", "false", "1", "0"}
            or not env.get("SMTP_USERNAME") or not env.get("SMTP_PASSWORD")):
        raise InstallError("SMTP configuration is incomplete")
    return {"host": env["SMTP_HOST"], "port": port, "use_ssl": boolean in {"true", "1"},
            "username": env["SMTP_USERNAME"], "password": env["SMTP_PASSWORD"],
            "from": sender, "recipient": recipient}


def validate_container(item, service):
    try:
        labels = item["Config"]["Labels"]
        if (item["Name"] != "/" + PROJECT + "-" + service + "-1"
                or not re.fullmatch(r"[0-9a-f]{64}", item["Id"])
                or item["Image"] != IMAGES[service]
                or labels.get("com.docker.compose.project") != PROJECT
                or labels.get("com.docker.compose.service") != service
                or item["State"]["Running"] is not True
                or item["State"].get("Health", {}).get("Status") != "healthy"):
            raise InstallError("Canonical production container identity, image, or health changed")
        for volume, destination in VOLUMES.get(service, {}).items():
            matches = [mount for mount in item["Mounts"] if mount.get("Destination") == destination]
            name = PROJECT + "_" + volume
            expected = {"Type": "volume", "Name": name, "Destination": destination, "RW": True,
                        "Source": "/var/lib/docker/volumes/" + name + "/_data"}
            if len(matches) != 1 or any(matches[0].get(key) != value for key, value in expected.items()):
                raise InstallError("Canonical production volume mount changed")
        return item
    except (KeyError, TypeError):
        raise InstallError("Incomplete production container identity") from None


def inspect_containers():
    result = {}
    for service in IMAGES:
        items = json.loads(command(["/usr/bin/docker", "inspect", PROJECT + "-" + service + "-1"]))
        if not isinstance(items, list) or len(items) != 1:
            raise InstallError("Expected exactly one canonical production container")
        result[service] = validate_container(items[0], service)
    ids = command(["/usr/bin/docker", "ps", "-a", "--filter",
                   "label=com.docker.compose.project=" + PROJECT, "--format", "{{.ID}}"]).split()
    expected = {item["Id"][:12] for item in result.values()}
    if set(ids) != expected or len(ids) != 5:
        raise InstallError("Unexpected additional Compose containers require inspection")
    return result


def sql(container, database, statement):
    return command([
        "/usr/bin/docker", "exec", "--user", "postgres", "-i", container,
        "/usr/bin/timeout", "--signal=TERM", "--kill-after=5s", "20s",
        "psql", "-X", "-qAt", "-v", "ON_ERROR_STOP=1",
        "-U", "postgres", "-d", database,
    ], input_text=statement, timeout=27)


def role_sql(kind, password):
    if kind not in {"api", "cms"} or not re.fullmatch(r"[A-Za-z0-9_-]{24,}", password):
        raise InstallError("Invalid generated backup role credentials")
    role = "sinegor_backup_" + kind
    database = "sinegor" if kind == "api" else "sinegor_cms"
    owner = "sinegor_owner" if kind == "api" else "sinegor_cms"
    return (
        "SET log_statement = 'none'; SET log_min_error_statement = 'panic';\n"
        "SET log_error_verbosity = 'terse'; SET statement_timeout = '10000'; SET lock_timeout = '2000';\n"
        "BEGIN;\n"
        f"CREATE ROLE {role} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
        f"NOINHERIT NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 2 PASSWORD '{password}';\n"
        f"ALTER ROLE {role} SET default_transaction_read_only = on;\n"
        f"ALTER ROLE {role} SET statement_timeout = '95000';\n"
        f"ALTER ROLE {role} SET lock_timeout = '3000';\n"
        f"GRANT CONNECT ON DATABASE {database} TO {role};\n"
        f"GRANT USAGE ON SCHEMA public TO {role};\n"
        f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {role};\n"
        f"GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO {role};\n"
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {owner} IN SCHEMA public GRANT SELECT ON TABLES TO {role};\n"
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {owner} IN SCHEMA public GRANT SELECT ON SEQUENCES TO {role};\n"
        "COMMIT;\n"
    )


def installed_sources():
    return {LIB / name: HERE / name for name in MODULES} | {
        Path("/etc/systemd/system") / name: PROJECT_ROOT / "infra/scheduler" / name
        for name in UNIT_NAMES
    }


def trusted_parent(path):
    info = Path(path).lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o022:
        raise InstallError("Installation parent must be a real root-owned directory")


def verify_prepared():
    marker = json.loads(file_bytes(PRIVATE / "managed.json", private=True))
    if (marker.get("version") != 1 or marker.get("project") != PROJECT
            or marker.get("status") != "prepared"):
        raise InstallError("Unrelated or partial installation requires manual inspection")
    for path in (PRIVATE, STATE, LIB, LIB / "tests", LIB / "bin",
                 *(STATE / name for name in ("cache", "tmp", "receipts", "runs", "restore", "repository"))):
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o700:
            raise InstallError("Managed directory permissions differ")
    for path, record in marker["files"].items():
        target = Path(path)
        info = target.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != record["mode"] or digest(target) != record["sha256"]):
            raise InstallError("Managed installation file differs")
    for name in ("psql", "pg_dump", "pg_restore"):
        if os.readlink(LIB / "bin" / name) != "../postgres_cli.py":
            raise InstallError("Managed PostgreSQL transport symlink differs")
    config = json.loads(file_bytes(PRIVATE / "config.json", private=True))
    expected = configuration()
    expected["activation_approved"] = config.get("activation_approved")
    if config != expected or not isinstance(config["activation_approved"], bool):
        raise InstallError("Managed production configuration differs")
    source_hashes = {str(source): digest(source) for source in installed_sources().values()}
    if marker["source_hashes"] != source_hashes:
        raise InstallError("Source files changed; managed installation requires a reviewed upgrade")
    return marker, config


def recovery_kit(env_data):
    target = PRIVATE / "recovery.tar"
    with os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb") as output:
        with tarfile.open(fileobj=output, mode="w") as archive:
            contents = {
                name: file_bytes(PRIVATE / name, private=True)
                for name in ("restic-password", "pg_service.conf", "pgpass", "config.json", "mail.json")
            }
            contents.update(env_data)
            contents["recovery.json"] = json.dumps({
                "version": 1, "project": PROJECT,
                "note": "Restic password cannot be recovered from the encrypted repository. "
                        "Keep this private recovery kit off the VPS; it contains application secrets, no data dumps.",
                "restic_version": "0.19.1", "restic_sha256": RESTIC_SHA256,
                "created_at": datetime.now(UTC).isoformat(),
            }).encode()
            for name, data in contents.items():
                info = tarfile.TarInfo(name)
                info.size, info.mode, info.uid, info.gid = len(data), 0o600, 0, 0
                archive.addfile(info, io.BytesIO(data))
        output.flush()
        os.fsync(output.fileno())


def check_target_conflicts():
    for name in UNIT_NAMES:
        properties = command(["/usr/bin/systemctl", "show", name,
                              "--property=LoadState,FragmentPath,ActiveState,UnitFileState"])
        values = dict(line.split("=", 1) for line in properties.splitlines() if "=" in line)
        if (values.get("LoadState") != "not-found" or values.get("FragmentPath")
                or values.get("ActiveState") not in {"inactive", "failed"}):
            raise InstallError("Existing backup unit requires inspection before installation")


def prepare():
    if PRIVATE.exists() or PRIVATE.is_symlink():
        verify_prepared()
        return "Existing managed preparation verified; no changes made"
    check_target_conflicts()
    for path in (PRIVATE, STATE, LIB):
        require_absent(path)
    for target in installed_sources():
        require_absent(target)
    for parent in (Path("/etc"), Path("/var/lib"), Path("/usr/local/bin"), Path("/etc/systemd/system"),
                   Path("/usr/local/lib")):
        trusted_parent(parent)
    for parent in (PRIVATE.parent, LIB.parent):
        if parent.exists() or parent.is_symlink():
            trusted_parent(parent)
    sources = installed_sources()
    source_data = {target: file_bytes(source) for target, source in sources.items()}
    restic_data = file_bytes(RESTIC_SOURCE)
    if hashlib.sha256(restic_data).hexdigest() != RESTIC_SHA256:
        raise InstallError("Pinned Restic 0.19.1 SHA-256 differs; no GPG signature verification is claimed")
    if RESTIC.exists() or RESTIC.is_symlink():
        info = RESTIC.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                or stat.S_IMODE(info.st_mode) != 0o755 or digest(RESTIC) != RESTIC_SHA256):
            raise InstallError("Existing Restic binary is unrelated")
    owner = PROJECT_ROOT.stat().st_uid
    private_info = ENV_ROOT.lstat()
    if (not stat.S_ISDIR(private_info.st_mode) or private_info.st_uid not in {0, owner}
            or stat.S_IMODE(private_info.st_mode) != 0o700):
        raise InstallError("Application private configuration directory is unsafe")
    env_data = {name: file_bytes(ENV_ROOT / name, private=True, owners=(0, owner)) for name in ENV_NAMES}
    containers = inspect_containers()
    pg = containers["postgres"]["Id"]
    for program in ("psql", "pg_dump", "pg_restore"):
        version = command(["/usr/bin/docker", "exec", "--user", "postgres", pg,
                           program, "--version"])
        if "16.14" not in version or "PostgreSQL" not in version:
            raise InstallError("PostgreSQL capture tools must match audited 16.14")
    timeout_version = command(["/usr/bin/docker", "exec", "--user", "postgres", pg,
                               "/usr/bin/timeout", "--version"])
    if "GNU coreutils" not in timeout_version:
        raise InstallError("Bounded daemon-side capture requires existing GNU timeout")
    roles = sql(pg, "postgres", "SET statement_timeout='5000'; SET lock_timeout='1000';\n"
                "SELECT count(*) FROM pg_roles WHERE rolname IN ('sinegor_backup_api','sinegor_backup_cms');\n")
    if roles.strip() != "0":
        raise InstallError("Backup roles already exist; refusing unrelated credentials")
    api_env = dict(item.split("=", 1) for item in containers["api"]["Config"]["Env"] if "=" in item)
    mail = mail_settings(api_env)
    check_space(shutil.disk_usage("/var/lib").free)
    config = configuration()
    passwords = {kind: secrets.token_urlsafe(36) for kind in ("api", "cms")}
    restic_password = secrets.token_urlsafe(64)
    # All checks above precede the first persistent change. A partial marker never authorizes reuse.
    PRIVATE.parent.mkdir(mode=0o755, exist_ok=True)
    LIB.parent.mkdir(mode=0o755, exist_ok=True)
    for path in (PRIVATE, STATE, LIB, LIB / "tests", LIB / "bin",
                 *(STATE / name for name in ("cache", "tmp", "receipts", "runs", "restore"))):
        path.mkdir(mode=0o700)
    marker = {"version": 1, "project": PROJECT, "status": "preparing",
              "created_at": datetime.now(UTC).isoformat(),
              "source_hashes": {str(source): hashlib.sha256(source_data[target]).hexdigest()
                                for target, source in sources.items()}}
    write_new(PRIVATE / "managed.json", json.dumps(marker))
    for target, data in source_data.items():
        write_new(target, data, mode=0o755 if target == LIB / "postgres_cli.py" else 0o644)
    if not RESTIC.exists():
        write_new(RESTIC, restic_data, mode=0o755)
    for name in ("psql", "pg_dump", "pg_restore"):
        (LIB / "bin" / name).symlink_to("../postgres_cli.py")
    write_new(PRIVATE / "config.json", json.dumps(config, sort_keys=True))
    write_new(PRIVATE / "mail.json", json.dumps(mail, sort_keys=True))
    write_new(PRIVATE / "restic-password", restic_password + "\n")
    service = ""
    pgpass = ""
    for kind, database in (("api", "sinegor"), ("cms", "sinegor_cms")):
        role = "sinegor_backup_" + kind
        service += (f"[{role}]\nhost=127.0.0.1\nport=5432\ndbname={database}\nuser={role}\n"
                    "connect_timeout=5\noptions=-c default_transaction_read_only=on "
                    "-c statement_timeout=95000 -c lock_timeout=3000\n\n")
        pgpass += f"127.0.0.1:5432:{database}:{role}:{passwords[kind]}\n"
    write_new(PRIVATE / "pg_service.conf", service)
    write_new(PRIVATE / "pgpass", pgpass)
    for kind, database in (("api", "sinegor"), ("cms", "sinegor_cms")):
        sql(pg, database, role_sql(kind, passwords[kind]))
    # Disk was checked before creation. Nothing existing is removed or pruned.
    (STATE / "repository").mkdir(mode=0o700)
    command([str(RESTIC), "init"], timeout=120, env={
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "RESTIC_REPOSITORY": str(STATE / "repository"),
        "RESTIC_PASSWORD_FILE": str(PRIVATE / "restic-password"),
        "RESTIC_CACHE_DIR": str(STATE / "cache"), "TMPDIR": str(STATE / "tmp"),
    })
    recovery_kit(env_data)
    command(["/usr/bin/systemctl", "daemon-reload"])
    # No systemctl enable/start and no backup run are allowed in preparation.
    paths = [*sources, RESTIC, *(PRIVATE / name for name in
             ("mail.json", "restic-password", "pg_service.conf", "pgpass", "recovery.tar"))]
    marker["files"] = {str(path): {"sha256": digest(path), "mode": stat.S_IMODE(path.stat().st_mode)}
                       for path in paths}
    marker["status"] = "prepared"
    atomic_json(PRIVATE / "managed.json", marker)
    verify_prepared()
    return "Prepared inactive backup support; timers remain disabled and production was not stopped"


def activate():
    marker, config = verify_prepared()
    inspect_containers()
    check_space(shutil.disk_usage(STATE).free)
    # --activate is a separate explicit owner action. It does not start services or timers.
    if config["activation_approved"] is not True:
        config["activation_approved"] = True
        atomic_json(PRIVATE / "config.json", config)
    command(["/usr/bin/systemctl", "enable", "sinegor-backup-recovery.service",
             "sinegor-backup.timer", "sinegor-backup-watchdog.timer"])
    return "Activation approved and units enabled; no timer or backup run was started"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--activate", action="store_true", help="Separate owner-approved activation; enables units without starting them")
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise InstallError("Installation requires root")
    if HERE != PROJECT_ROOT / "scripts/backup":
        raise InstallError("Run the installer from the canonical VPS checkout")
    os.umask(0o077)
    print(prepare() if args.prepare else activate())
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except InstallError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
    except (OSError, ValueError, KeyError, TypeError):
        print("Preparation refused or incomplete; inspect private state without exposing secrets", file=sys.stderr)
        raise SystemExit(1)
