"""Known-secret scan plus a transaction-local PostgreSQL error canary.

Print classifications/counts only. Never print logs, credentials or SQL values.
"""

import json
import re
import secrets
import subprocess
from pathlib import Path

PROJECT = "sinegor-vi0-20261111"
ROOT = Path(__file__).resolve().parents[2]
known = set()
for relative in (
    "apps/cms/.env",
    "apps/api/.env.development",
    "storage/vi0-20261111/api.env",
    "storage/vi0-20261111/cms.env",
    "storage/vi0-20261111/compose.env",
    "storage/vi0-20261111/cms-check.env",
    "storage/vi0-20261112/browser.env",
):
    path = ROOT / relative
    if not path.exists():
        continue
    for line in path.read_text().splitlines():
        name, separator, value = line.partition("=")
        if separator and any(
            part in name.upper() for part in ("SECRET", "PASSWORD", "TOKEN", "KEY")
        ):
            known.update(part.encode() for part in value.strip("\"'").split(",") if len(part) >= 20)

pg = PROJECT + "-postgres-1"
pg_metadata = json.loads(subprocess.check_output(["docker", "inspect", pg]))[0]
assert pg_metadata["Config"]["Labels"]["com.docker.compose.project"] == PROJECT
before = subprocess.run(["docker", "logs", pg], check=True, capture_output=True)
canary = "vi0-private-" + secrets.token_hex(12)
check = subprocess.run(
    [
        "docker",
        "exec",
        "-i",
        pg,
        "psql",
        "-X",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        "postgres",
        "-d",
        "sinegor",
    ],
    input=(
        "BEGIN; CREATE TEMP TABLE vi0_log_check (value text UNIQUE); "
        f"INSERT INTO vi0_log_check VALUES ('{canary}'); "
        f"INSERT INTO vi0_log_check VALUES ('{canary}'); ROLLBACK;"
    ),
    text=True,
    capture_output=True,
)
assert check.returncode != 0 and "duplicate key" in check.stderr
warning = subprocess.run(
    [
        "docker",
        "exec",
        "-i",
        pg,
        "psql",
        "-X",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        "postgres",
        "-d",
        "sinegor",
    ],
    input="DO $$ BEGIN RAISE WARNING 'vi0_pglog_warning_probe'; END $$;",
    text=True,
    capture_output=True,
    check=True,
)
after = subprocess.run(["docker", "logs", pg], check=True, capture_output=True)
new_logs = after.stdout[len(before.stdout) :] + after.stderr[len(before.stderr) :]
assert re.search(rb"ERROR:.*duplicate key value violates unique constraint", new_logs)
assert re.search(rb"WARNING:.*vi0_pglog_warning_probe", new_logs)
assert canary.encode() not in new_logs, "UNIQUE error leaked the synthetic value"
results = {}
for service in ("postgres", "api", "cms", "web", "proxy"):
    name = PROJECT + "-" + service + "-1"
    metadata = json.loads(subprocess.check_output(["docker", "inspect", name]))[0]
    assert metadata["Config"]["Labels"]["com.docker.compose.project"] == PROJECT
    logs = subprocess.run(["docker", "logs", name], check=True, capture_output=True)
    content = logs.stdout + logs.stderr
    hits = sum(value in content for value in known)
    assert not hits, "Known credential found in logs"
    assert canary.encode() not in content, "SQL error value leaked into logs"
    assert not re.search(rb"(?:#token=|[?&]token=|Set-Cookie:|Cookie:)", content, re.I)
    results[service] = {"known_secret_hits": hits, "sensitive_url_cookie_hits": 0}
print(
    json.dumps(
        {
            "postgres_error_recorded": True,
            "postgres_warning_recorded": True,
            "postgres_error_canary_absent": True,
            "services": results,
        },
        indent=2,
    )
)
