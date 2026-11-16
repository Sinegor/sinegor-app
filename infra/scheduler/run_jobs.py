"""Host launcher, not a scheduler: systemd supplies the calendar and process lifecycle."""

import argparse
import json
import os
import re
import shlex
import stat
import subprocess
from pathlib import Path
from time import perf_counter
from urllib.parse import urlsplit

OPERATIONS = {
    "minute": ("process_orders", "process_notifications"),
    "cleanup_agreements": ("cleanup_agreements",),
    "purge_auth": ("purge_auth",),
    "purge_analytics": ("purge_analytics",),
    "purge_security_events": ("purge_security_events",),
    "cleanup_business": ("cleanup_business",),
}


def event(name, **fields):
    print(json.dumps({"event": name, **fields}), flush=True)


def forward_errors(name, response):
    allowed_events = {
        "job_run_failed",
        "job_lock_busy",
        "notifications_run_failed",
        "notification_delivery_failed",
        "notification_worker_failed",
        "agreement_file_cleanup_failed",
        "business_retention_customer_failed",
        "retention_pdf_cleanup_failed",
    }
    allowed_types = {
        "ValueError",
        "RuntimeError",
        "OperationalError",
        "ProgrammingError",
        "IntegrityError",
        "PermissionError",
        "OSError",
        "FileNotFoundError",
        "MailDeliveryError",
        "TelegramDeliveryError",
        "AgreementStorageError",
        "TimeoutError",
        "DBAPIError",
    }
    for line in (response.stdout + "\n" + response.stderr).splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if not isinstance(value, dict) or value.get("event") not in allowed_events:
            continue
        error = value.get("exception_type", value.get("error_type"))
        event(
            "host_worker_error",
            job=name,
            source_event=value["event"],
            error_type=error if error in allowed_types else "OtherError",
        )


def configuration(env):
    directory = Path(env["SINEGOR_PROJECT_DIR"])
    project = env["SINEGOR_PROJECT_NAME"]
    if not directory.is_absolute() or not directory.is_dir():
        raise ValueError("Invalid project directory")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", project):
        raise ValueError("Invalid project name")
    args = [
        "/usr/bin/docker",
        "compose",
        "--project-name",
        project,
    ]
    for key, flag in (
        ("SINEGOR_COMPOSE_ENV_FILE", "--env-file"),
        ("SINEGOR_COMPOSE_FILE", "-f"),
        ("SINEGOR_COMPOSE_OVERRIDE", "-f"),
    ):
        path = Path(env[key])
        if not path.is_absolute() or not path.is_file():
            raise ValueError("Invalid configuration path")
        args.extend([flag, str(path)])
    return args


def security_environment(env):
    path = Path(env["SECURITY_CLEANUP_ENV_FILE"])
    info = path.lstat()
    if (
        not path.is_absolute()
        or not stat.S_ISREG(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o600
    ):
        raise ValueError("Unsafe maintenance environment")
    lines = [
        line
        for line in path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if len(lines) != 1 or not lines[0].startswith("DATABASE_URL="):
        raise ValueError("Maintenance environment must only override DATABASE_URL")
    value = shlex.split(lines[0].split("=", 1)[1])
    if len(value) != 1:
        raise ValueError("Invalid maintenance database")
    url = urlsplit(value[0])
    if (
        url.scheme != "postgresql+psycopg"
        or url.username != "sinegor_security_cleanup"
        or not url.password
        or url.hostname != "postgres"
        or url.path != "/sinegor"
        or url.port not in (None, 5432)
        or url.query
        or url.fragment
    ):
        raise ValueError("Expected restricted production maintenance role")
    return str(path)


def _host_checks(runner):
    issues = []
    for operation in OPERATIONS:
        for suffix in ("timer", "service"):
            unit = (
                f"sinegor-job-{operation}.timer"
                if suffix == "timer"
                else (f"sinegor-job@{operation}.service")
            )
            result = runner(
                [
                    "/usr/bin/systemctl",
                    "show",
                    unit,
                    "--no-pager",
                    "-p",
                    "LoadState",
                    "-p",
                    "ActiveState",
                    "-p",
                    "Result",
                    "-p",
                    "ExecMainStatus",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            state = dict(
                line.split("=", 1) for line in result.stdout.splitlines() if "=" in line
            )
            if result.returncode or state.get("LoadState") != "loaded":
                issues.append(f"{operation}:{suffix}_missing")
            elif suffix == "timer" and state.get("ActiveState") != "active":
                issues.append(f"{operation}:timer_inactive")
            elif suffix == "service" and state.get("Result") not in (None, "success"):
                issues.append(f"{operation}:service_failed")
    legacy = runner(
        ["/usr/bin/systemctl", "is-active", "sinegor-notifications.timer"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if legacy.stdout.strip() == "active":
        issues.append("legacy_notification_timer_active")
    return issues


def run(operation, env, *, runner=subprocess.run):
    try:
        if operation not in (*OPERATIONS, "check"):
            raise ValueError("Unknown operation")
        if operation != "check" and env.get("JOBS_ACTIVATION_REVIEWED") != "yes":
            raise PermissionError("Activation review required")
        prefix = configuration(env)
        # Only selectors are inherited. Channel credentials remain in container env files.
        process_env = {
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "COMPOSE_ANSI": "never",
        }
        service = env.get("SINEGOR_API_SERVICE", "api")
        python = env.get("SINEGOR_PYTHON", "/app/.venv/bin/python")
        if service != "api" or python != "/app/.venv/bin/python":
            raise ValueError("Unexpected application command")
        if operation == "check":
            issues = _host_checks(runner)
            response = runner(
                [
                    *prefix,
                    "exec",
                    "--interactive=false",
                    "-T",
                    service,
                    python,
                    "-m",
                    "sinegor.jobs.check_status",
                ],
                capture_output=True,
                text=True,
                env=process_env,
                timeout=30,
            )
            status = json.loads(response.stdout)
            if status.get("event") != "jobs_status" or status.get("status") not in (
                "ok",
                "critical",
            ):
                raise ValueError("Invalid status response")
            # The application diagnostic's schema contains no contact data or payloads.
            event("host_jobs_check", host_issues=issues, application=status)
            return int(
                bool(issues) or response.returncode != 0 or status["status"] != "ok"
            )
        failed = False
        busy = False
        for name in OPERATIONS[operation]:
            args = [
                *prefix,
                "exec",
                "--interactive=false",
                "-T",
                service,
                python,
                "-m",
                f"sinegor.jobs.{name}",
            ]
            if name == "purge_security_events":
                process_env["SECURITY_CLEANUP_ENV_FILE"] = security_environment(env)
                args = [
                    *prefix,
                    "run",
                    "--rm",
                    "--no-deps",
                    "--interactive=false",
                    "-T",
                    "security_cleanup",
                ]
            if name == "cleanup_business":
                args.extend(["--execute", "--limit", "100"])
            started = perf_counter()
            event("host_job_started", job=name)
            try:
                response = runner(args, capture_output=True, text=True, env=process_env)
                code = response.returncode
                forward_errors(name, response)
            except Exception as exc:  # noqa: BLE001 -- do not leak subprocess/config payloads.
                event("host_job_launch_failed", job=name, error_type=type(exc).__name__)
                code = 1
            # Never forward arbitrary Docker stdout/stderr (it can contain env/SQL values).
            event(
                "host_job_finished",
                job=name,
                exit_code=code,
                duration_ms=round((perf_counter() - started) * 1000, 2),
            )
            failed |= code not in (0, 75)
            busy |= code == 75
        return 1 if failed else 75 if busy else 0
    except Exception as exc:  # noqa: BLE001 -- outer boundary exposes exception type only.
        event("host_jobs_failed", error_type=type(exc).__name__)
        return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=[*OPERATIONS, "check"])
    return run(parser.parse_args().operation, os.environ)


if __name__ == "__main__":
    raise SystemExit(main())
