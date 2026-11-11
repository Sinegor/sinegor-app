#!/usr/bin/env python3
"""Run the live suite on disposable resources; never load developer dotenv."""

import argparse
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from harness import (
    HarnessError,
    ProcessStack,
    isolated_environment,
    snapshot,
    wait_http,
)

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "postgres:16"
LABEL = "sinegor.e2e.run"


def docker(*arguments: str, data: str | None = None) -> str:
    result = subprocess.run(
        ["docker", *arguments],
        input=data,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise HarnessError("Docker operation failed; check daemon access and postgres:16 image")
    return result.stdout.strip()


def remove_container(name: str, run_id: str) -> None:
    found = docker("ps", "-aq", "--filter", f"name=^{name}$")
    if not found:
        return
    owner = docker("inspect", "-f", '{{ index .Config.Labels "' + LABEL + '" }}', name)
    if owner != run_id:
        raise HarnessError("Refused to remove a container owned by another run")
    docker("rm", "-f", name)


def ports(count: int) -> dict[str, int]:
    names = ("web", "proxy", "api", "cms", "cms_control", "external", "control", "smtp")
    reservations = []
    try:
        for _ in range(count):
            connection = socket.socket()
            connection.bind(("127.0.0.1", 0))
            reservations.append(connection)
        return {
            name: connection.getsockname()[1]
            for name, connection in zip(names, reservations, strict=True)
        }
    finally:
        for connection in reservations:
            connection.close()


def certificate(private: Path) -> None:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName(name)
                    for name in (
                        "localhost",
                        "cloud-api.yandex.net",
                        "api.telegram.org",
                    )
                ]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    (private / "tls.key").write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    (private / "tls.crt").write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def configuration(
    private: Path,
    workspace: Path,
    run_id: str,
    allocated: dict[str, int],
    pg_port: int,
    password: str,
) -> dict:
    from cryptography.fernet import Fernet

    env = isolated_environment()
    origin = f"http://localhost:{allocated['proxy']}"
    database = f"sinegor_e2e_{run_id}_test"
    api = env | {
        "APP_ENV": "test",
        "SINEGOR_ENV_FILE": "/dev/null",
        "LOG_LEVEL": "WARNING",
        "DATABASE_URL": f"postgresql+psycopg://e2e_api:{password}@127.0.0.1:{pg_port}/{database}",
        "PYTHONPATH": str(workspace / "apps/api/src"),
        "PUBLIC_ORIGIN": origin,
        "SESSION_SECRET": secrets.token_urlsafe(48),
        "AUTH_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "AGREEMENT_STORAGE_DIR": str(private / "agreements"),
        "SMTP_HOST": "localhost",
        "SMTP_PORT": str(allocated["smtp"]),
        "SMTP_USE_SSL": "true",
        "SMTP_USERNAME": "e2e",
        "SMTP_PASSWORD": secrets.token_urlsafe(24),
        "SMTP_FROM_EMAIL": "sender@example.org",
        "NOTIFICATION_ADMIN_EMAIL": "admin@example.org",
        "YANDEX_DISK_TOKEN": "synthetic-e2e",
        "YANDEX_DISK_ROOT": "disk:/E2E",
        "TELEGRAM_BOT_TOKEN": "synthetic-e2e",
        "TELEGRAM_ADMIN_CHAT_ID": "synthetic-e2e",
        "SSL_CERT_FILE": str(private / "tls.crt"),
    }
    cms = env | {
        "NODE_ENV": "production",
        "HOST": "127.0.0.1",
        "PORT": str(allocated["cms"]),
        "CMS_PUBLIC_ORIGIN": f"http://localhost:{allocated['cms']}",
        "DATABASE_HOST": "127.0.0.1",
        "DATABASE_PORT": str(pg_port),
        "DATABASE_NAME": f"sinegor_e2e_{run_id}_cms_test",
        "DATABASE_USERNAME": "e2e_cms",
        "DATABASE_PASSWORD": password,
        "APP_KEYS": secrets.token_urlsafe(32),
        "STRAPI_TELEMETRY_DISABLED": "true",
    }
    for key in (
        "ADMIN_JWT_SECRET",
        "API_TOKEN_SALT",
        "TRANSFER_TOKEN_SALT",
        "ENCRYPTION_KEY",
        "JWT_SECRET",
    ):
        cms[key] = secrets.token_urlsafe(32)
    return {
        "run_id": run_id,
        "private": str(private),
        "workspace": str(workspace),
        "python": sys.executable,
        "ports": allocated,
        "origin": origin,
        "control_key": secrets.token_urlsafe(32),
        "api_env": api,
        "cms_env": cms,
        "admin": {"email": "admin@example.org", "password": secrets.token_urlsafe(24)},
        "service_pids": {},
    }


def write_config(path: Path, config: dict) -> None:
    path.write_text(json.dumps(config), encoding="utf-8")
    path.chmod(0o600)


def preflight() -> None:
    if os.name != "posix" or sys.version_info < (3, 12):
        raise HarnessError("Use Python >=3.12 on a POSIX host with Docker")
    for command in ("docker", "node", "npm"):
        if shutil.which(command) is None:
            raise HarnessError(f"Missing command: {command}")
    for app in ("web", "cms"):
        if not (ROOT / "apps" / app / "node_modules").is_dir():
            raise HarnessError(f"Install apps/{app} dependencies with npm ci first")
    version = subprocess.check_output(["node", "-p", "process.versions.node"], text=True).strip()
    if tuple(map(int, version.split(".")[:2])) < (22, 12):
        raise HarnessError("Node >=22.12 is required")
    docker("image", "inspect", IMAGE)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite",
        choices=("all", "workflow", "cms", "notifications", "resilience", "scheduler"),
        default="all",
    )
    parser.add_argument(
        "--no-scheduler",
        action="store_true",
        help="Disable periodic notification CLI for diagnosis",
    )
    parser.add_argument("--output", type=Path, help="New or empty directory for safe result JSON")
    args = parser.parse_args()
    run_id = uuid.uuid4().hex[:12]
    artifacts = args.output or Path(tempfile.mkdtemp(prefix="sinegor-e2e-results-"))
    if artifacts.exists() and any(artifacts.iterdir()):
        parser.error("--output must be a new or empty directory")
    artifacts.mkdir(parents=True, exist_ok=True)
    artifacts = artifacts.resolve()
    private = Path(tempfile.mkdtemp(prefix="sinegor-e2e-private-"))
    workspace = private / "source"
    container = f"sinegor-e2e-{run_id}"
    attempted_container = False
    summary = {
        "run_id": run_id,
        "suite": args.suite,
        "container": container,
        "passed": False,
        "cleanup": False,
    }
    code = 1
    old_handlers = {}
    stack = None

    def interrupted(*_):
        raise InterruptedError()

    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            old_handlers[signum] = signal.signal(signum, interrupted)
        preflight()
        snapshot(ROOT, workspace)
        allocated = ports(8)
        password = secrets.token_hex(24)
        pg_env = private / "postgres.env"
        pg_env.write_text(
            f"POSTGRES_USER=e2e_root\nPOSTGRES_PASSWORD={password}\nPOSTGRES_DB=postgres\n"
        )
        pg_env.chmod(0o600)
        attempted_container = True
        docker(
            "run",
            "-d",
            "--name",
            container,
            "--label",
            f"{LABEL}={run_id}",
            "--env-file",
            str(pg_env),
            "--tmpfs",
            "/var/lib/postgresql/data:rw,nosuid,size=1g",
            "-p",
            "127.0.0.1::5432",
            "--health-cmd",
            "pg_isready -U e2e_root -d postgres",
            "--health-interval",
            "1s",
            "--health-timeout",
            "2s",
            "--health-retries",
            "30",
            IMAGE,
        )
        import time

        for _ in range(100):
            if docker("inspect", "-f", "{{.State.Health.Status}}", container) == "healthy":
                break
            time.sleep(0.2)
        else:
            raise HarnessError("PostgreSQL readiness timed out")
        pg_port = int(docker("port", container, "5432/tcp").rsplit(":", 1)[1])
        config = configuration(private, workspace, run_id, allocated, pg_port, password)
        sql = (
            f"CREATE ROLE e2e_api LOGIN PASSWORD '{password}';\n"
            f"CREATE ROLE e2e_cms LOGIN PASSWORD '{password}';\n"
            "GRANT SET ON PARAMETER sinegor.security_retention_days TO e2e_api;\n"
            f"CREATE DATABASE sinegor_e2e_{run_id}_test OWNER e2e_api;\n"
            f"CREATE DATABASE sinegor_e2e_{run_id}_cms_test OWNER e2e_cms;\n"
        )
        docker(
            "exec",
            "-i",
            container,
            "psql",
            "-U",
            "e2e_root",
            "-d",
            "postgres",
            "-q",
            "-v",
            "ON_ERROR_STOP=1",
            data=sql,
        )
        certificate(private)
        config["scheduler_enabled"] = not args.no_scheduler
        summary["scheduler_enabled"] = config["scheduler_enabled"]
        config_path = private / "run.json"
        write_config(config_path, config)
        control_env = isolated_environment() | {"SINEGOR_E2E_CONFIG": str(config_path)}
        api_env = config["api_env"] | control_env
        cms_env = config["cms_env"] | control_env
        web_env = control_env | {
            "HOST": "127.0.0.1",
            "PORT": str(allocated["web"]),
            "CMS_ORIGIN": f"http://127.0.0.1:{allocated['cms']}",
            "CMS_MEDIA_ORIGIN": f"http://localhost:{allocated['cms']}",
        }
        test_dir = workspace / "tests/e2e"
        with ProcessStack(private) as stack:
            print("E2E: building isolated apps and applying fresh migrations", flush=True)
            stack.stage(
                "migrations",
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                workspace / "apps/api",
                api_env,
            )
            stack.stage(
                "bootstrap",
                [sys.executable, str(test_dir / "data.py"), "bootstrap"],
                workspace,
                api_env,
            )
            # data.py writes the freshly created TOTP into the private configuration.
            config = json.loads(config_path.read_text())
            stack.stage("web-build", ["npm", "run", "build"], workspace / "apps/web", web_env)
            stack.stage("cms-build", ["npm", "run", "build"], workspace / "apps/cms", cms_env)
            services = [
                (
                    "external",
                    [sys.executable, str(test_dir / "external.py")],
                    workspace,
                    control_env,
                ),
                ("api", [sys.executable, str(test_dir / "api.py")], workspace, api_env),
                (
                    "cms",
                    ["node", str(test_dir / "cms.cjs")],
                    workspace / "apps/cms",
                    cms_env,
                ),
                ("web", ["npm", "start"], workspace / "apps/web", web_env),
                (
                    "proxy",
                    ["node", str(test_dir / "proxy.cjs")],
                    workspace,
                    control_env,
                ),
            ]
            processes = {}
            for name, command, cwd, env in services:
                processes[name] = stack.start(name, command, cwd, env)
                config["service_pids"][name] = processes[name].pid
            write_config(config_path, config)
            wait_http(f"http://127.0.0.1:{allocated['control']}/health", processes["external"])
            wait_http(
                f"http://127.0.0.1:{allocated['api']}/api/health/ready",
                processes["api"],
            )
            wait_http(
                f"http://127.0.0.1:{allocated['cms']}/_health",
                processes["cms"],
                expected=204,
            )
            wait_http(config["origin"] + "/", processes["proxy"])
            if config["scheduler_enabled"]:
                process = stack.start(
                    "scheduler",
                    [sys.executable, str(test_dir / "scheduler.py")],
                    workspace,
                    control_env,
                )
                config["service_pids"]["scheduler"] = process.pid
                write_config(config_path, config)
            print("E2E: real frontend / FastAPI / PostgreSQL / Strapi ready", flush=True)
            command = [
                "node",
                str(workspace / "apps/web/node_modules/@playwright/test/cli.js"),
                "test",
                "--config",
                str(test_dir / "playwright.config.cjs"),
            ]
            if args.suite != "all":
                command.append(f"{args.suite}.spec.cjs")
            process = stack.start(
                "playwright",
                command,
                workspace,
                control_env | {"SINEGOR_E2E_OUTPUT": str(artifacts)},
            )
            code = process.wait(timeout=240)
            summary["passed"] = code == 0
            if (artifacts / "results.json").exists():
                result = json.loads((artifacts / "results.json").read_text())
                for test in result["tests"]:
                    print(f"{test['status']}: {test['title']}", flush=True)
                    if test.get("error"):
                        print(test["error"], flush=True)
    except HarnessError as error:
        summary["passed"] = False
        summary["error"] = str(error)
        print(f"E2E: {error}", file=sys.stderr)
    except (KeyboardInterrupt, InterruptedError):
        summary["passed"] = False
        summary["error"] = "Interrupted"
        code = 130
    except Exception as error:
        summary["passed"] = False
        # Exception messages from drivers/frameworks can contain SQL values or credentials.
        summary["error"] = f"Preparation failed ({type(error).__name__})"
        print(summary["error"], file=sys.stderr)
    finally:
        for signum in old_handlers:
            signal.signal(signum, signal.SIG_IGN)
        try:
            if attempted_container:
                remove_container(container, run_id)
            shutil.rmtree(private)
            summary["cleanup"] = stack is None or stack.cleanup_complete
            if not summary["cleanup"]:
                summary["cleanup_error"] = "Could not stop all owned test processes"
                code = 1
        except Exception:
            summary["cleanup_error"] = f"Could not clean owned test resources: {container}"
            code = 1
        for signum, old in old_handlers.items():
            signal.signal(signum, old)
        (artifacts / "run.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(f"E2E artifacts: {artifacts}", flush=True)
    return code if summary["passed"] and summary["cleanup"] else (code or 1)


if __name__ == "__main__":
    raise SystemExit(main())
