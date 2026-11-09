"""Disposable PostgreSQL/Strapi/Restic restore test, with no project dotenv or live data."""

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
LABEL = "sinegor.backup-test.run"


def call(command, *, env=None, cwd=None, data=None, success=True):
    result = subprocess.run(command, env=env, cwd=cwd, input=data, capture_output=True, timeout=180)
    if (result.returncode == 0) != success:
        if len(command) > 1 and str(command[1]).endswith("/backup.py"):
            print(result.stderr.decode(errors="replace"))
        raise RuntimeError(f"Test stage failed ({Path(command[0]).name})")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=HERE.parents[2])
    parser.add_argument("--restic", default="restic")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    root = args.project_root.resolve()
    sys.path.insert(0, str(root / "tests/e2e"))
    from harness import isolated_environment, snapshot

    run_id = uuid.uuid4().hex[:12]
    container = f"sinegor-backup-test-{run_id}"
    result = {"run_id": run_id, "passed": [], "cleanup": False}
    created = False
    try:
        with tempfile.TemporaryDirectory(prefix="sinegor-backup-test-") as temporary:
            private = Path(temporary)
            private.chmod(0o700)
            env = isolated_environment() | {
                "SINEGOR_ENV_FILE": "/dev/null",
                "TMPDIR": str(private),
                "SINEGOR_BACKUP_PRIVATE": str(private),
                "SINEGOR_BACKUP_PROJECT": str(root),
                "RESTIC_REPOSITORY": str(private / "repository"),
                "RESTIC_PASSWORD_FILE": str(private / "restic-password"),
                "RESTIC_CACHE_DIR": str(private / "cache"),
                "PGSERVICEFILE": str(private / "pg_service.conf"),
                "PGPASSFILE": str(private / "pgpass"),
            }
            (private / "restic-password").write_text(secrets.token_urlsafe(32))
            password = secrets.token_urlsafe(32)
            (private / "postgres.env").write_text(
                f"POSTGRES_USER=fixture\nPOSTGRES_PASSWORD={password}\nPOSTGRES_DB=postgres\n"
            )
            for file in private.iterdir():
                file.chmod(0o600)
            call(["docker", "image", "inspect", "postgres:16"])
            call(
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    container,
                    "--label",
                    f"{LABEL}={run_id}",
                    "--env-file",
                    str(private / "postgres.env"),
                    "-p",
                    "127.0.0.1::5432",
                    "--mount",
                    "type=tmpfs,destination=/var/lib/postgresql/data,tmpfs-size=1073741824",
                    "postgres:16",
                ]
            )
            created = True
            for _ in range(100):
                check = subprocess.run(
                    [
                        "docker",
                        "exec",
                        container,
                        "pg_isready",
                        "-h",
                        "127.0.0.1",
                        "-U",
                        "fixture",
                    ],
                    capture_output=True,
                )
                if check.returncode == 0:
                    break
                time.sleep(0.2)
            else:
                raise RuntimeError("Disposable PostgreSQL readiness timed out")
            port = (
                call(["docker", "port", container, "5432/tcp"])
                .stdout.decode()
                .strip()
                .rsplit(":", 1)[1]
            )
            names = {
                "api": "source_api",
                "cms": "source_cms",
                "restore_api": "api_restore_test",
                "restore_cms": "cms_restore_test",
                "guard_api": "guard_api_restore_test",
                "busy_function": "function_restore_test",
                "busy_type": "type_restore_test",
                "busy_schema": "schema_restore_test",
                "busy_domain": "domain_restore_test",
                "busy_namespace": "namespace_restore_test",
            }
            sql = "\n".join(f"CREATE DATABASE {name};" for name in names.values())
            call(
                [
                    "docker",
                    "exec",
                    "-i",
                    container,
                    "psql",
                    "-X",
                    "-U",
                    "fixture",
                    "-d",
                    "postgres",
                    "-v",
                    "ON_ERROR_STOP=1",
                ],
                data=sql.encode(),
            )
            services = "\n".join(
                f"[{service}]\nhost=127.0.0.1\nport=5432\nuser=fixture\ndbname={name}\n"
                for service, name in names.items()
            )
            (private / "pg_service.conf").write_text(services)
            (private / "pgpass").write_text(f"127.0.0.1:5432:*:fixture:{password}\n")
            (private / "pgpass").chmod(0o600)
            for name in ("pg_service.conf", "pgpass"):
                call(["docker", "cp", str(private / name), f"{container}:/tmp/{name}"])
            binaries = private / "bin"
            binaries.mkdir()
            env["SINEGOR_BACKUP_TEST_CONTAINER"] = container
            for program in ("psql", "pg_dump", "pg_restore"):
                wrapper = binaries / program
                wrapper.write_text(f"#!{sys.executable}\n" + (HERE / "postgres_cli.py").read_text())
                wrapper.chmod(0o700)
            (binaries / "restic").symlink_to(
                Path(shutil.which(args.restic) or args.restic).resolve()
            )
            env["PATH"] = str(binaries) + os.pathsep + env["PATH"]
            probe = subprocess.run(
                [
                    "psql",
                    "-X",
                    "-w",
                    "--dbname",
                    "service=api",
                    "-At",
                    "-c",
                    "SELECT 1",
                ],
                env=env,
                capture_output=True,
            )
            if probe.returncode:
                for marker in (
                    b"password authentication failed",
                    b"no password supplied",
                    b"service file",
                    b"not found",
                    b"Permission denied",
                    b"connection refused",
                    b"does not exist",
                    b"could not",
                ):
                    if marker.lower() in probe.stderr.lower():
                        print("PostgreSQL fixture connection category:", marker.decode())
                raise RuntimeError("PostgreSQL fixture service connection failed")
            busy_objects = {
                "busy_function": "CREATE FUNCTION public.restore_marker() RETURNS integer "
                "LANGUAGE sql AS 'SELECT 1'",
                "busy_type": "CREATE TYPE public.restore_marker AS ENUM ('fixture')",
                "busy_schema": "CREATE SCHEMA pgx; CREATE TABLE pgx.keep(id integer)",
                "busy_domain": "CREATE DOMAIN public.restore_marker AS integer",
                "busy_namespace": "CREATE SCHEMA standalone",
            }
            for service, sql in busy_objects.items():
                call(
                    [
                        "psql",
                        "-X",
                        "--dbname",
                        f"service={service}",
                        "-v",
                        "ON_ERROR_STOP=1",
                        "-c",
                        sql,
                    ],
                    env=env,
                )
                # A relation-only check used to miss these otherwise nonempty databases.
                call(
                    [
                        sys.executable,
                        "-c",
                        "import sys;sys.path.insert(0,sys.argv[1]);"
                        "from backup import database_info;"
                        "assert database_info(sys.argv[2])['objects'] > 0",
                        str(HERE.parent),
                        service,
                    ],
                    env=env,
                )
            result["passed"].append("nonempty_function_type_domain_namespace_and_pgx_guards")
            api_env = env | {
                "APP_ENV": "test",
                "DATABASE_URL": f"postgresql+psycopg://fixture:{password}@127.0.0.1:{port}/source_api",
                "AGREEMENT_STORAGE_DIR": str(private / "agreements"),
            }
            call(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                env=api_env,
                cwd=root / "apps/api",
            )
            call([sys.executable, str(HERE / "api_fixture.py"), "seed"], env=api_env)
            workspace = private / "source"
            snapshot(root, workspace)
            cms_env = env | {
                "NODE_ENV": "production",
                "HOST": "127.0.0.1",
                "PORT": "1337",
                "DATABASE_HOST": "127.0.0.1",
                "DATABASE_PORT": port,
                "DATABASE_NAME": "source_cms",
                "DATABASE_USERNAME": "fixture",
                "DATABASE_PASSWORD": password,
                "STRAPI_TELEMETRY_DISABLED": "true",
            }
            for key in (
                "APP_KEYS",
                "ADMIN_JWT_SECRET",
                "API_TOKEN_SALT",
                "TRANSFER_TOKEN_SALT",
                "ENCRYPTION_KEY",
                "JWT_SECRET",
            ):
                cms_env[key] = secrets.token_urlsafe(32)
            call(
                ["node", str(HERE / "cms_fixture.cjs"), "seed"],
                env=cms_env,
                cwd=workspace / "apps/cms",
            )
            result["passed"].append("real_api_migrations_and_strapi_upload_document_services")
            call(["restic", "init"], env=env)
            tool = [sys.executable, str(HERE.parent / "backup.py")]
            receipt = private / "receipt.json"
            create = [
                *tool,
                "backup",
                "--writers-stopped",
                "--api-service",
                "api",
                "--cms-service",
                "cms",
                "--agreements",
                str(private / "agreements"),
                "--uploads",
                str(workspace / "apps/cms/public/uploads"),
            ]
            sys.path.insert(0, str(workspace / "apps/api/src"))
            from datetime import UTC, datetime

            from sinegor.modules.retention.archive import RetentionArchive

            archive = RetentionArchive(private / "destruction")
            archive_key = archive.store(
                datetime(2026, 11, 8, tzinfo=UTC),
                {"act.pdf": b"synthetic act", "export.csv": b"synthetic rows"},
            )
            create += ["--destruction-archive", str(archive.root)]
            call([*create, "--receipt", str(receipt)], env=env)
            result["passed"].append("pg_dump_both_databases_and_restic_snapshot")
            restore = [
                *tool,
                "restore-test",
                "--receipt",
                str(receipt),
                "--api-service",
                "restore_api",
                "--cms-service",
                "restore_cms",
            ]
            target = private / "restored"
            call([*restore, "--target", str(target)], env=env)
            result["passed"].append("pg_restore_both_empty_databases_and_manifest_sha256")
            restored_archive = RetentionArchive(target / "destruction")
            assert restored_archive.references() == archive.references()
            assert (
                target / "destruction" / archive_key / "act.pdf"
            ).read_bytes() == b"synthetic act"
            result["passed"].append("destruction_archive_manifest_bytes_and_hashes_restored")
            call(
                [sys.executable, str(HERE / "api_fixture.py"), "verify"],
                env=api_env
                | {
                    "DATABASE_URL": api_env["DATABASE_URL"].replace(
                        "/source_api", "/api_restore_test"
                    ),
                    "AGREEMENT_STORAGE_DIR": str(target / "agreements"),
                },
            )
            result["passed"].append(
                "final_and_pending_pdf_original_bytes_and_database_hashes_orphans_excluded"
            )
            restored_workspace = private / "restored-project"
            snapshot(root, restored_workspace)
            shutil.copytree(
                target / "media",
                restored_workspace / "apps/cms/public/uploads",
                dirs_exist_ok=True,
            )
            call(
                ["node", str(HERE / "cms_fixture.cjs"), "verify"],
                env=cms_env | {"DATABASE_NAME": "cms_restore_test"},
                cwd=restored_workspace / "apps/cms",
            )
            result["passed"].append(
                "restored_strapi_public_document_pdf_link_image_formats_and_public_controller"
            )
            call([*restore, "--target", str(target)], env=env, success=False)
            call(
                [*restore, "--target", str(private / "nonempty-db")],
                env=env,
                success=False,
            )
            call(
                [
                    *tool,
                    "restore-test",
                    "--receipt",
                    str(receipt),
                    "--api-service",
                    "api",
                    "--cms-service",
                    "restore_cms",
                    "--target",
                    str(private / "source-db"),
                ],
                env=env,
                success=False,
            )
            result["passed"].append(
                "existing_directory_nonempty_databases_and_source_database_refused"
            )
            for service in busy_objects:
                call(
                    [
                        *tool,
                        "restore-test",
                        "--receipt",
                        str(receipt),
                        "--api-service",
                        "guard_api",
                        "--cms-service",
                        service,
                        "--target",
                        str(private / service),
                    ],
                    env=env,
                    success=False,
                )
                untouched = call(
                    [
                        "psql",
                        "-X",
                        "--dbname",
                        "service=guard_api",
                        "-At",
                        "-c",
                        "SELECT to_regclass('public.agreements') IS NULL",
                    ],
                    env=env,
                )
                assert untouched.stdout.strip() == b"t"
            result["passed"].append("nonempty_second_database_refused_before_first_is_written")
            failed_receipt = private / "failed.json"
            failure = call(
                [*create, "--receipt", str(failed_receipt)],
                env=env | {"RESTIC_REPOSITORY": str(private / "missing-repository")},
                success=False,
            )
            assert not failed_receipt.exists()
            assert b"Backup completed" not in failure.stdout
            assert password.encode() not in failure.stdout + failure.stderr
            assert b"restore-fixture@example.org" not in failure.stdout + failure.stderr
            result["passed"].append("failed_restic_has_no_receipt_success_message_or_secret_output")
            call(["restic", "check", "--read-data"], env=env)
            result["passed"].append("restic_check_read_data")
            call(
                [sys.executable, str(HERE / "api_fixture.py"), "verify-source"],
                env=api_env,
            )
            result["passed"].append("source_pdf_bytes_hashes_and_obsolete_file_unchanged")
            result["restic"] = call(["restic", "version"], env=env).stdout.decode().strip()
            result["postgres"] = (
                call(
                    [
                        "psql",
                        "--dbname",
                        "service=api",
                        "-At",
                        "-c",
                        "SHOW server_version",
                    ],
                    env=env,
                )
                .stdout.decode()
                .strip()
            )
    except Exception as exc:
        result["failure"] = (
            type(exc).__name__ + ": " + str(exc)
            if isinstance(exc, RuntimeError)
            else type(exc).__name__
        )
    finally:
        if created:
            owner = (
                call(
                    [
                        "docker",
                        "inspect",
                        "-f",
                        '{{ index .Config.Labels "' + LABEL + '" }}',
                        container,
                    ]
                )
                .stdout.decode()
                .strip()
            )
            if owner == run_id:
                call(["docker", "rm", "-f", container])
                result["cleanup"] = True
        else:
            result["cleanup"] = True
        args.report.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
    return 1 if "failure" in result or not result["cleanup"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
