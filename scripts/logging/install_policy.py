"""Approved 90-day technical host policy; no application data or backup pruning."""

import argparse
import importlib.util
import json
import os
import re
import subprocess
import uuid
from pathlib import Path

ROOT = Path("/home/sinegoradmin/apps/sinegor-app")
STATE = Path("/var/lib/sinegor-log-retention")
PACKAGES = (
    "alternatives",
    "apt",
    "dpkg",
    "certbot",
    "ufw",
    "clamav-freshclam",
    "wtmp",
    "btmp",
)


def render(source):
    source = re.sub(
        r"(?m)^(\s*)(?:weekly|monthly|yearly|hourly)\s*$", r"\1daily", source
    )
    source = re.sub(r"(?m)^(\s*)rotate\s+\d+\s*$", r"\1rotate 90", source)
    source = re.sub(r"(?m)^\s*minsize\s+[^\n]+\n", "", source)
    source = source.replace("notifempty", "ifempty")
    source = re.sub(r"(?m)^\s*maxage\s+\d+\s*\n", "", source)
    source = source.replace("{\n", "{\n    maxage 90\n")
    return source


def run(args):
    p = subprocess.run(args, capture_output=True, text=True, timeout=60, check=False)
    if p.returncode:
        raise RuntimeError("Policy command failed")
    return p.stdout


def publish(path, data, mode=0o644):
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    temp = path.parent / (".iii10-" + uuid.uuid4().hex)
    try:
        temp.write_bytes(data)
        temp.chmod(mode)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approve-existing-one", action="store_true")
    args = parser.parse_args()
    if os.geteuid() != 0:
        return 2
    os.umask(0o077)
    spec = importlib.util.spec_from_file_location(
        "log_lifecycle", ROOT / "scripts/logging/retention.py"
    )
    lifecycle = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lifecycle)
    now = lifecycle.datetime.now(lifecycle.UTC)
    assessment = lifecycle.prune_wtmp(Path("/var/log/wtmp.db"), now)
    if args.approve_existing_one:
        assert assessment["expired_closed_records"] <= 1
    old = run(
        ["journalctl", "--no-pager", "-o", "json", "-n", "1", "--until", "90 days ago"]
    )
    assert not any(line.startswith("{") for line in old.splitlines()), (
        "existing_old_journal_requires_assessment"
    )
    STATE.mkdir(mode=0o700, exist_ok=True)
    work = STATE / ("policy-" + uuid.uuid4().hex)
    work.mkdir(mode=0o700)
    changed = {}

    def save(path, data):
        previous = path.read_bytes() if path.exists() else None
        changed[path] = previous
        if previous is not None:
            (work / (path.name + ".previous")).write_bytes(previous)
        publish(path, data)

    try:
        for package in PACKAGES:
            path = Path("/etc/logrotate.d") / package
            if path.exists():
                save(path, render(path.read_text()).encode())
        extra = b"/var/log/disk.log {\n daily\n rotate 90\n maxage 90\n missingok\n ifempty\n compress\n copytruncate\n}\n/var/log/apt/eipp.log.xz {\n daily\n rotate 90\n maxage 90\n missingok\n ifempty\n nocompress\n}\n"
        save(Path("/etc/logrotate.d/sinegor-host"), extra)
        run(["/usr/sbin/logrotate", "--debug", "/etc/logrotate.conf"])
        save(
            Path("/etc/systemd/journald.conf.d/90-sinegor-retention.conf"),
            (ROOT / "infra/logging/journald-90-days.conf").read_bytes(),
        )
        run(["systemctl", "restart", "systemd-journald.service"])
        run(["systemctl", "is-active", "systemd-journald.service"])
    except Exception:
        for path, data in changed.items():
            if data is None:
                path.unlink(missing_ok=True)
            else:
                publish(path, data)
        raise
    cleanup = False
    if args.approve_existing_one:
        folder = Path("/usr/local/lib/sinegor/logging")
        folder.mkdir(mode=0o700, exist_ok=True)
        publish(
            folder / "retention.py",
            (ROOT / "scripts/logging/retention.py").read_bytes(),
            0o600,
        )
        lifecycle.ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
        for suffix in ("service", "timer"):
            publish(
                Path("/etc/systemd/system/sinegor-log-retention." + suffix),
                (
                    ROOT / ("infra/scheduler/sinegor-log-retention." + suffix)
                ).read_bytes(),
            )
        # Preserve live SQLite inode and active sessions: row TTL replaces file-level rotation.
        publish(
            Path("/etc/logrotate.d/wtmpdb"),
            b"# wtmp.db: 90-day closed-record TTL via sinegor-log-retention.timer; do not rename live SQLite database.\n",
        )
        run(["systemctl", "daemon-reload"])
        run(
            [
                "systemd-analyze",
                "verify",
                "/etc/systemd/system/sinegor-log-retention.service",
                "/etc/systemd/system/sinegor-log-retention.timer",
            ]
        )
        run(["systemctl", "start", "sinegor-log-retention.service"])
        run(["systemctl", "enable", "--now", "sinegor-log-retention.timer"])
        cleanup = True
    result = {
        "journal_max_retention_days": 90,
        "journal_max_file_days": 1,
        "existing_old_journal_deleted": False,
        "host_logrotate_days": 90,
        "logrotate_debug_success": True,
        "cleanup_enabled": cleanup,
        "initial_expired_closed_os_records": assessment["expired_closed_records"],
        "existing_os_records_deleted": assessment["expired_closed_records"]
        if cleanup
        else 0,
        "production_containers_restarted": False,
    }
    (work / "result.json").write_text(json.dumps(result))
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:  # noqa: BLE001 - no private exception messages
        print(
            json.dumps(
                {"policy_install_failed": True, "error_type": type(error).__name__}
            )
        )
        raise SystemExit(1)
