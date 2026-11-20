"""Guarded native journald cutover. Apply requires an approved availability window."""

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import retention as lifecycle

ROOT = Path("/home/sinegoradmin/apps/sinegor-app")
BASE = ROOT / "infra/compose/production.yaml"
SERVICES = ("postgres", "api", "cms", "web", "proxy")
OLD_LOGGING = 'driver: json-file\n  options:\n    max-size: "10m"\n    max-file: "3"'
NEW_LOGGING = 'driver: journald\n  options:\n    tag: "{{.Name}}"'


def run(args, timeout=60):
    p = subprocess.run(
        args, capture_output=True, text=True, timeout=timeout, check=False
    )
    if p.returncode:
        raise RuntimeError("Cutover command failed")
    return p.stdout


def inspect(reference):
    return json.loads(run(["docker", "inspect", reference]))[0]


def archive_closed(item, root, state, observer):
    """Only stopped sources; final copies are immutable and publication shares cleanup lock."""
    if item["State"]["Running"]:
        raise ValueError("Archive source is running")
    identifier = item["Id"]
    service = item["Config"]["Labels"]["com.docker.compose.service"]
    if service not in SERVICES or not re.fullmatch(r"[0-9a-f]{64}", identifier):
        raise ValueError("Unknown archive source")
    source = Path(item["LogPath"])
    if not source.is_absolute():
        raise ValueError("Invalid source path")
    copied = []
    with lifecycle.archive_lock(state):
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        lifecycle.private(root.lstat(), directory=True)
        for index in range(3):
            path = source if index == 0 else Path(str(source) + "." + str(index))
            if not path.exists():
                continue
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, "rb") as f:
                before = os.fstat(f.fileno())
                if (
                    not stat.S_ISREG(before.st_mode)
                    or before.st_nlink != 1
                    or before.st_size > 32 * 1024**2
                ):
                    raise ValueError("Invalid source file")
                data = f.read(32 * 1024**2 + 1)
                after = os.fstat(f.fileno())
            if (before.st_ino, before.st_size, before.st_mtime_ns) != (
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            ):
                raise ValueError("Source changed during copy")
            lifecycle.filter_lines(
                data.decode().splitlines(keepends=True), datetime.now(UTC)
            )
            if observer(identifier)["State"]["Running"]:
                raise ValueError("Source resumed during copy")
            target = root / (service + "-" + identifier + "-" + str(index) + ".jsonl")
            checksum = hashlib.sha256(data).hexdigest()
            if target.exists():
                lifecycle.private(target.lstat())
                if hashlib.sha256(target.read_bytes()).hexdigest() != checksum:
                    raise ValueError("Existing immutable archive differs")
            else:
                temp = root / ("." + uuid.uuid4().hex + ".tmp")
                try:
                    fd = os.open(
                        temp,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                        0o600,
                    )
                    with os.fdopen(fd, "wb") as out:
                        out.write(data)
                        out.flush()
                        os.fsync(out.fileno())
                    os.link(temp, target)
                finally:
                    temp.unlink(missing_ok=True)
            copied.append(
                {
                    "service": service,
                    "index": index,
                    "bytes": len(data),
                    "sha256": checksum,
                }
            )
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    return copied


def replace_base(text, ownership):
    temp = BASE.parent / (".iii10-" + uuid.uuid4().hex)
    try:
        temp.write_text(text)
        os.chmod(temp, stat.S_IMODE(ownership.st_mode))
        os.chown(temp, ownership.st_uid, ownership.st_gid)
        os.replace(temp, BASE)
    finally:
        temp.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "apply"))
    parser.add_argument("--approved-window", action="store_true")
    args = parser.parse_args()
    if os.geteuid() != 0 or (args.action == "apply" and not args.approved_window):
        return 2
    os.umask(0o077)
    sys.path.insert(0, "/usr/local/lib/sinegor/backup")
    import production as controls

    cfg = controls.load_config(Path("/etc/sinegor/backup/config.json"))
    items = {s: inspect("sinegor-lab-prod-" + s + "-1") for s in SERVICES}
    for service, item in items.items():
        assert (
            item["State"]["Status"] == "running"
            and item["State"]["Health"]["Status"] == "healthy"
        )
        assert (
            item["Config"]["Labels"]["com.docker.compose.project"] == "sinegor-lab-prod"
        )
        assert item["Config"]["Labels"]["com.docker.compose.service"] == service
        assert item["HostConfig"]["LogConfig"] == {
            "Type": "json-file",
            "Config": {"max-file": "3", "max-size": "10m"},
        }
        assert Path(item["LogPath"]) == Path("/var/lib/docker/containers") / item[
            "Id"
        ] / (item["Id"] + "-json.log")
    original, ownership = BASE.read_text(), BASE.stat()
    assert original.count(OLD_LOGGING) == 1
    compose = [
        "docker",
        "compose",
        "-p",
        "sinegor-lab-prod",
        "--env-file",
        str(ROOT.parent / "sinegor-app-private/compose.env"),
        "-f",
        str(BASE),
        "-f",
        str(ROOT / "infra/compose/production.https.yaml"),
    ]
    configuration = json.loads(run([*compose, "config", "--format", "json"]))
    for service, item in items.items():
        image = json.loads(
            run(
                [
                    "docker",
                    "image",
                    "inspect",
                    configuration["services"][service]["image"],
                ]
            )
        )[0]
        assert image["Id"] == item["Image"]
    assert not (Path(cfg["state_dir"]) / "pending.json").exists()
    plan = {
        "services": list(SERVICES),
        "images_unchanged": True,
        "volume_deletion": False,
        "legacy_logs_preserved": True,
        "backup_and_jobs_locks": True,
        "expected_outage_minutes": "3-5",
        "rollback_prepared": True,
    }
    if args.action == "plan":
        print(json.dumps(plan))
        return 0
    assert (
        Path("/etc/systemd/journald.conf.d/90-sinegor-retention.conf").read_bytes()
        == (ROOT / "infra/logging/journald-90-days.conf").read_bytes()
    )
    work = lifecycle.STATE / ("cutover-" + uuid.uuid4().hex)
    work.mkdir(mode=0o700, parents=True)
    (work / "previous-production.yaml").write_text(original)
    copied = []
    with (
        controls.RunLock(cfg),
        controls.JobLocks(cfg["sources"]["agreements"], uid=cfg["writer_uid"]),
    ):
        assert not (Path(cfg["state_dir"]) / "pending.json").exists()
        try:
            replace_base(original.replace(OLD_LOGGING, NEW_LOGGING), ownership)
            # Drain app writes before stopping PostgreSQL. No volume/image deletion or build/pull.
            for service in ("api", "cms", "web", "proxy", "postgres"):
                run(
                    ["docker", "stop", "--timeout", "-1", items[service]["Id"]],
                    timeout=90,
                )
                stopped = inspect(items[service]["Id"])
                copied.extend(
                    archive_closed(stopped, lifecycle.ROOT, lifecycle.STATE, inspect)
                )
            for service in SERVICES:
                run(
                    [
                        *compose,
                        "up",
                        "-d",
                        "--no-deps",
                        "--force-recreate",
                        "--no-build",
                        "--pull",
                        "never",
                        service,
                    ],
                    timeout=120,
                )
                deadline = time.monotonic() + 120
                while True:
                    current = inspect("sinegor-lab-prod-" + service + "-1")
                    assert current["Image"] == items[service]["Image"]
                    if current["State"].get("Health", {}).get("Status") == "healthy":
                        break
                    if time.monotonic() > deadline:
                        raise TimeoutError("Health deadline exceeded")
                    time.sleep(1)
                assert current["HostConfig"]["LogConfig"]["Type"] == "journald"
                assert {
                    v["Name"] for v in current["Mounts"] if v["Type"] == "volume"
                } == {
                    v["Name"] for v in items[service]["Mounts"] if v["Type"] == "volume"
                }
        except Exception:
            replace_base(original, ownership)
            recovery = []
            for service in SERVICES:
                try:
                    run(
                        [
                            *compose,
                            "up",
                            "-d",
                            "--no-deps",
                            "--no-build",
                            "--pull",
                            "never",
                            service,
                        ],
                        timeout=120,
                    )
                    recovery.append(service)
                except (RuntimeError, subprocess.SubprocessError):
                    pass
            (work / "failure.json").write_text(
                json.dumps({"recovery_attempted": recovery, "logs_preserved": copied})
            )
            raise
    result = {
        "cutover_complete": True,
        "images_unchanged": True,
        "volumes_preserved": True,
        "legacy_copies": copied,
    }
    (work / "result.json").write_text(json.dumps(result))
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:  # noqa: BLE001 - closed top-level diagnostic
        print(json.dumps({"cutover_failed": True, "error_type": type(error).__name__}))
        raise SystemExit(1)
