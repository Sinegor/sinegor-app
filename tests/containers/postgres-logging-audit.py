"""Compare native PostgreSQL logging policies using disposable synthetic clusters.

No published ports, application networks, source data, raw log output or new images.
Only resources created by this invocation with its unique label may be removed.
Run from the repository root with apps/api/.venv/bin/python.
"""

import json
import os
import re
import secrets
import selectors
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = ROOT / "storage/pglog-audit-20261112"
PG_IMAGE = "postgres:16.14@sha256:4b7183ac05f8ef417db21fd72d71047a4238340c261d3cc3ddb6d579ab5071ae"
CLIENT_IMAGE = "sinegor-api:vi0-20261111"
LABEL = "sinegor.pglog-audit"
RUN = "20261112-" + secrets.token_hex(4)
STAGE = "preflight"
COMMON = {
    "log_min_error_statement": "panic",
    "log_error_verbosity": "terse",
    "log_statement": "none",
    "log_parameter_max_length_on_error": "0",
}
VARIANTS = {
    "current_fatal": {**COMMON, "log_min_messages": "fatal"},
    "error_terse": {
        **COMMON,
        "log_min_messages": "error",
        "log_parameter_max_length": "0",
        "log_line_prefix": "%m [%p] sqlstate=%e ",
    },
    "warning_terse": {
        **COMMON,
        "log_min_messages": "warning",
        "log_parameter_max_length": "0",
        "log_line_prefix": "%m [%p] sqlstate=%e ",
    },
    "log_terse": {
        **COMMON,
        "log_min_messages": "log",
        "log_parameter_max_length": "0",
        "log_line_prefix": "%m [%p] sqlstate=%e ",
    },
    "error_json": {
        **COMMON,
        "log_min_messages": "error",
        "log_parameter_max_length": "0",
        "log_destination": "jsonlog",
        "logging_collector": "on",
    },
}
CASES = {
    "success": (None, None),
    "unique": ("23505", "ERROR"),
    "foreign_key": ("23503", "ERROR"),
    "syntax": ("42601", "ERROR"),
    "invalid_cast_name": ("22P02", "ERROR"),
    "invalid_cast_email": ("22P02", "ERROR"),
    "invalid_cast_phone": ("22003", "ERROR"),
    "invalid_cast_token": ("22P02", "ERROR"),
    "invalid_cast_password": ("22P02", "ERROR"),
    "permission_denied": ("42501", "ERROR"),
    "auth_bad_password": ("28P01", "FATAL"),
    "auth_sensitive_login": ("28P01", "FATAL"),
    "database_missing": ("3D000", "FATAL"),
    "migration_failure": ("22P02", "ERROR"),
    "plpgsql_detail_context": ("P0001", "ERROR"),
    "raise_warning": (None, "WARNING"),
    "raise_log": (None, "LOG"),
    "connection_terminated": ("57P01", "FATAL"),
    "connection_refused": (None, None),
}


def docker(*args, check=True, **kwargs):
    result = subprocess.run(["docker", *args], capture_output=True, **kwargs)
    if check and result.returncode:
        # stderr may contain a SQL value; never forward it or command arguments.
        raise RuntimeError("Audit Docker operation failed")
    return result


def metadata(kind, name):
    return json.loads(docker(kind, "inspect", name).stdout)[0]


def guard(kind, name):
    obj = metadata(kind, name)
    labels = obj["Config"]["Labels"] if kind == "container" else obj["Labels"]
    assert labels.get(LABEL) == RUN, "Refused operation on an unrelated resource"
    return obj


def protected():
    containers, networks = [], []
    for project in ("battle_deposit_backend", "sinegor-vi0-20261111"):
        ids = docker("ps", "-aq", "--filter", "label=com.docker.compose.project=" + project)
        for ident in ids.stdout.decode().split():
            c = metadata("container", ident)
            containers.append(
                {
                    "id": c["Id"],
                    "started": c["State"]["StartedAt"],
                    "running": c["State"]["Running"],
                    "restarts": c["RestartCount"],
                    "networks": c["NetworkSettings"]["Networks"],
                }
            )
        ids = docker(
            "network", "ls", "-q", "--filter", "label=com.docker.compose.project=" + project
        )
        for ident in ids.stdout.decode().split():
            n = metadata("network", ident)
            networks.append(
                {
                    "id": n["Id"],
                    "containers": n["Containers"],
                    "ipam": n["IPAM"],
                    "options": n["Options"],
                }
            )
    assert containers and networks
    original = metadata("container", "sinegor_f5_postgres_1")
    assert not original["State"]["Running"]
    return {
        "containers": sorted(containers, key=lambda x: x["id"]),
        "networks": sorted(networks, key=lambda x: x["id"]),
        "original_cms": {"id": original["Id"], "state": original["State"]},
    }


class Client:
    def __init__(self, server, name, env_file):
        self.name = name
        source = (ROOT / "tests/containers/postgres-logging-cases.py").read_text()
        self.process = subprocess.Popen(
            [
                "docker",
                "run",
                "--rm",
                "-i",
                "--name",
                name,
                "--label",
                LABEL + "=" + RUN,
                "--network",
                "container:" + server,
                "--env-file",
                str(env_file),
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--read-only",
                "--tmpfs",
                "/tmp:rw,size=32m,mode=1777",
                "--entrypoint",
                "python",
                CLIENT_IMAGE,
                "-u",
                "-c",
                source,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    def call(self, case, values):
        self.process.stdin.write(json.dumps({"case": case, "values": values}) + "\n")
        self.process.stdin.flush()
        with selectors.DefaultSelector() as ready:
            ready.register(self.process.stdout, selectors.EVENT_READ)
            assert ready.select(timeout=40), "Audit client timeout"
        line = self.process.stdout.readline()
        assert line, "Audit client ended without a safe response"
        result = json.loads(line)
        assert "harness_error" not in result, "Audit probe harness failed: " + result.get(
            "harness_error", ""
        )
        return result

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.write('{"case":"exit"}\n')
            self.process.stdin.flush()
        self.process.communicate(timeout=15)
        assert self.process.returncode == 0, "Audit client failed"


def logs(server, variant):
    result = docker("logs", server)
    extra = b""
    if variant == "error_json":
        extra = docker(
            "exec",
            "--user",
            "postgres",
            server,
            "sh",
            "-c",
            "cat /var/lib/postgresql/data/log/*.json",
        ).stdout
    return result.stdout, result.stderr, extra


def delta(before, after):
    return b"\n".join(new[len(old) :] for old, new in zip(before, after, strict=True))


def analyze(content, values, severity):
    records = []
    for line in content.decode(errors="replace").splitlines():
        if line.startswith("{"):
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    decoded = content + json.dumps(records, ensure_ascii=False).encode()
    fields = [name for name, value in values.items() if value.encode() in decoded]
    observed = (
        (
            bool(re.search(rb"\b" + severity.encode() + rb":", content))
            or any(row.get("error_severity") == severity for row in records)
        )
        if severity
        else False
    )
    states = sorted(
        {
            row.get("state_code", row.get("sql_state_code"))
            for row in records
            if row.get("state_code", row.get("sql_state_code"))
        }
        | set(re.findall(r"sqlstate=([0-9A-Z]{5})", content.decode(errors="replace")))
    )
    return {
        "server_error_recorded": observed,
        "server_sqlstates": states,
        "sensitive_fields_found": fields,
        "sensitive_value_found": bool(fields),
    }


def wait_ready(server):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if docker("exec", server, "pg_isready", "-U", "postgres", check=False).returncode == 0:
            return
        time.sleep(0.2)
    raise RuntimeError("Disposable audit PostgreSQL did not become ready")


def run():
    global STAGE
    PRIVATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    initial = protected()
    (PRIVATE / "protected-before.json").write_text(json.dumps(initial, indent=2) + "\n")
    env_file = PRIVATE / (RUN + ".env")
    with open(env_file, "x", opener=lambda path, flags: os.open(path, flags, 0o600)) as env:
        env.write("POSTGRES_PASSWORD=" + secrets.token_hex(24) + "\n")
        env.write(
            "AUDIT_ROLE_PASSWORD=" + secrets.token_hex(24) + "\nSINEGOR_PGLOG_AUDIT=20261112\n"
        )
        env.write("POSTGRES_INITDB_ARGS=--auth-host=scram-sha-256\n")
    results = []
    try:
        for variant, settings in VARIANTS.items():
            STAGE = variant + ": startup"
            server = "sinegor-pglog-" + RUN + "-" + variant.replace("_", "-")
            volume = server + "-data"
            client = None
            created_volume = created_server = False
            try:
                docker("volume", "create", "--label", LABEL + "=" + RUN, volume)
                created_volume = True
                options = [
                    part for key, value in settings.items() for part in ("-c", key + "=" + value)
                ]
                docker(
                    "run",
                    "-d",
                    "--name",
                    server,
                    "--label",
                    LABEL + "=" + RUN,
                    "--network",
                    "none",
                    "--env-file",
                    str(env_file),
                    "--mount",
                    f"type=volume,src={volume},dst=/var/lib/postgresql/data",
                    "--log-driver",
                    "json-file",
                    "--log-opt",
                    "max-size=10m",
                    "--log-opt",
                    "max-file=2",
                    PG_IMAGE,
                    "postgres",
                    *options,
                )
                created_server = True
                wait_ready(server)
                c = guard("container", server)
                assert (
                    c["HostConfig"]["NetworkMode"] == "none" and not c["HostConfig"]["PortBindings"]
                )
                client = Client(server, server + "-client", env_file)
                assert client.call("setup", {})["ok"]
                rows = []
                for case, (expected_state, severity) in CASES.items():
                    STAGE = variant + ": " + case
                    ident = secrets.token_hex(6)
                    values = {
                        "name": "Тестов Аудит" + ident + " Проверочный",
                        "email": "pglog-" + ident + "@example.invalid",
                        "phone": "+7999" + str(secrets.randbelow(10_000_000)).zfill(7),
                        "token": "audit_token_" + ident,
                        "password": "audit_password_" + ident,
                    }
                    before = logs(server, variant)
                    response = client.call(case, values)
                    if case not in ("success", "raise_warning", "raise_log"):
                        assert not response["ok"], "Expected an isolated probe error: " + case
                    if response.get("sqlstate"):
                        assert response["sqlstate"] == expected_state, (
                            "Unexpected SQLSTATE: " + case
                        )
                    time.sleep(0.1)
                    observed = analyze(delta(before, logs(server, variant)), values, severity)
                    rows.append(
                        {
                            "case": case,
                            "expected_sqlstate": expected_state,
                            "client_sqlstate": response.get("sqlstate"),
                            "client_saw_failure": not response["ok"],
                            **observed,
                            **{
                                k: response[k]
                                for k in ("migration_rolled_back", "client_output_has_canary")
                                if k in response
                            },
                        }
                    )
                client.close()
                client = None
                before = logs(server, variant)
                guard("container", server)
                docker("kill", "--signal=QUIT", server)
                deadline = time.monotonic() + 15
                while (
                    guard("container", server)["State"]["Running"] and time.monotonic() < deadline
                ):
                    time.sleep(0.1)
                assert not guard("container", server)["State"]["Running"]
                docker("start", server)
                wait_ready(server)
                recovery = delta(before, logs(server, variant))
                lifecycle = {
                    "own_immediate_shutdown_and_recovery": True,
                    "operational_log_messages_recorded": b"LOG:" in recovery
                    or b'"error_severity":"LOG"' in recovery,
                    "recovery_detail_recorded": b"redo" in recovery or b"recovery" in recovery,
                    "ready_after_recovery": True,
                }
                results.append(
                    {
                        "variant": variant,
                        "settings": settings,
                        "cases": rows,
                        "lifecycle": lifecycle,
                        "sensitive_cases": sum(row["sensitive_value_found"] for row in rows),
                    }
                )
                (PRIVATE / "matrix.json").write_text(json.dumps(results, indent=2) + "\n")
                print(
                    f"PASS: measured {variant}: {len(rows)} scenarios; "
                    f"{results[-1]['sensitive_cases']} expose synthetic values",
                    flush=True,
                )
            finally:
                try:
                    if client:
                        client.close()
                finally:
                    if created_server:
                        guard("container", server)
                        docker("rm", "-f", server)
                    if created_volume:
                        guard("volume", volume)
                        docker("volume", "rm", volume)
    finally:
        unchanged = protected() == initial
        (PRIVATE / "protected-result.json").write_text(
            json.dumps({"protected_projects_unchanged": unchanged}) + "\n"
        )
        assert unchanged, "Protected container/network metadata changed"
    print(
        "PASS: protected application projects and original CMS unchanged; audit resources removed"
    )


if __name__ == "__main__":
    try:
        run()
    except Exception as error:
        # Avoid subprocess args, SQL statements, credentials and original exception text.
        print(
            "FAIL: PostgreSQL logging audit at " + STAGE + " (" + type(error).__name__ + ")",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
