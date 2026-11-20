"""Ninety-day expiry for private, closed legacy Docker log copies only."""

import argparse
import fcntl
import json
import os
import re
import sqlite3
import stat
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path("/var/log/sinegor/docker-legacy")
STATE = Path("/var/lib/sinegor-log-retention")
NAME = re.compile(r"(?:api|cms|postgres|web|proxy)-[0-9a-f]{64}-[012]\.jsonl")


def filter_lines(lines, now):
    if now.tzinfo is None:
        raise ValueError("Timezone required")
    cutoff = now.astimezone(UTC) - timedelta(days=90)
    kept, removed = [], 0
    for line in lines:
        value = json.loads(line)
        at = datetime.fromisoformat(value["time"])
        if at.tzinfo is None:
            raise ValueError("Timezone required")
        if not isinstance(value["log"], str) or value["stream"] not in (
            "stdout",
            "stderr",
        ):
            raise ValueError("Unknown log record")
        if at <= cutoff:
            removed += 1
        else:
            kept.append(line)
    return kept, removed


def private(info, directory=False):
    expected = 0o700 if directory else 0o600
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    if (
        not kind(info.st_mode)
        or stat.S_IMODE(info.st_mode) != expected
        or info.st_uid != os.geteuid()
        or (not directory and info.st_nlink != 1)
    ):
        raise PermissionError("Unsafe legacy log permissions")


def process(root, now, apply=False):
    try:
        info = root.lstat()
    except FileNotFoundError:
        return {"files": 0, "expired_records": 0, "applied": apply}
    private(info, directory=True)
    plans = []
    for path in sorted(root.iterdir()):
        if not NAME.fullmatch(path.name):
            raise ValueError("Unexpected legacy archive entry")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, encoding="utf-8") as source:
            info = os.fstat(source.fileno())
            private(info)
            if info.st_size > 32 * 1024**2:
                raise ValueError("Legacy archive exceeds bounded reader")
            kept, expired = filter_lines(source, now)
        plans.append((path, info, kept, expired))
    # Validate every file before mutating any file; unknown data is preserved.
    if apply:
        for path, info, kept, expired in plans:
            if not expired:
                continue
            current = path.lstat()
            if (current.st_ino, current.st_size, current.st_mtime_ns) != (
                info.st_ino,
                info.st_size,
                info.st_mtime_ns,
            ):
                raise ValueError("Archive changed during assessment")
            temp = root / ("." + uuid.uuid4().hex + ".tmp")
            try:
                fd = os.open(
                    temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
                )
                with os.fdopen(fd, "w", encoding="utf-8") as output:
                    output.writelines(kept)
                    output.flush()
                    os.fsync(output.fileno())
                if kept:
                    os.replace(temp, path)
                else:
                    path.unlink()
                directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            finally:
                temp.unlink(missing_ok=True)
    return {
        "files": len(plans),
        "expired_records": sum(v[3] for v in plans),
        "applied": apply,
    }


def prune_wtmp(path, now, apply=False):
    """Closed OS login records only; preserve active sessions and recent logout events."""
    private(path.lstat())
    mode = "rw" if apply else "ro"
    cutoff = int((now.astimezone(UTC) - timedelta(days=90)).timestamp() * 1_000_000)
    with sqlite3.connect(
        "file:" + str(path) + "?mode=" + mode, uri=True, timeout=5
    ) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(wtmp)")}
        if columns != {
            "ID",
            "Type",
            "User",
            "Login",
            "Logout",
            "TTY",
            "RemoteHost",
            "Service",
        }:
            raise ValueError("Unknown login journal schema")
        if apply:
            connection.execute("PRAGMA secure_delete=ON")
            connection.execute("BEGIN IMMEDIATE")
        where = "Login <= ? AND Logout IS NOT NULL AND Logout > 0 AND Logout <= ?"
        expired = connection.execute(
            "SELECT count(*) FROM wtmp WHERE " + where, (cutoff, cutoff)
        ).fetchone()[0]
        if apply:
            connection.execute("DELETE FROM wtmp WHERE " + where, (cutoff, cutoff))
        return {"expired_closed_records": expired, "applied": apply}


@contextmanager
def archive_lock(directory=STATE):
    """Publisher and cleanup use this same lock; published files are never appended.

    Cutover publishes a complete private copy only after Docker reports stopped,
    verifies the source did not change, and never replaces an existing archive.
    Production writers may not modify final files outside this protocol.
    """
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    private(directory.lstat(), directory=True)
    fd = os.open(directory / "run.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        private(os.fstat(fd))
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("scan", "cleanup"))
    args = parser.parse_args()
    if os.geteuid() != 0:
        return 2
    os.umask(0o077)
    try:
        with archive_lock():
            result = process(ROOT, datetime.now(UTC), args.action == "cleanup")
            result["os_login_journal"] = prune_wtmp(
                Path("/var/log/wtmp.db"), datetime.now(UTC), args.action == "cleanup"
            )
        print(json.dumps(result))
        return 0
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
        print(
            json.dumps(
                {
                    "event": "legacy_log_retention_failed",
                    "reason": "assessment_or_cleanup_failed",
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
