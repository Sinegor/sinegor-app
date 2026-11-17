"""Single-host production backup controls. Activation requires reviewed private config."""

import argparse
import fcntl
import json
import os
import re
import signal
import smtplib
import ssl
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path
from types import SimpleNamespace

import backup

BackupError = backup.BackupError
JOB_NAMES = (
    "process_orders", "process_notifications", "cleanup_agreements", "purge_auth",
    "purge_analytics", "purge_security_events", "cleanup_business", "process_destructions",
)
GIB = 1024 ** 3


def failure_reason(error):
    """Return only closed operator codes; arbitrary exception text is never logged."""
    if isinstance(error, BackupError):
        reasons = {
            "Insufficient free disk space before capture": "disk_space_low",
            "Writer job drain timed out": "writer_drain_timeout",
            "Consistent capture deadline exceeded": "capture_timeout",
            "Writer did not stop gracefully": "writer_shutdown_failed",
            "Unexpected database writer connection": "unexpected_writer",
            "Unexpected container can write protected data": "unexpected_writer",
            "Graceful stop or service recovery did not finish": "resume_timeout",
            "Source service is not canonical and healthy": "source_unhealthy",
            "Source path differs from approved configuration": "source_identity_changed",
            "Another backup or recovery operation is active": "concurrent_operation",
            "Unresolved recovery journal": "recovery_pending",
            "Control command unavailable or timed out": "control_timeout",
            "Control command failed": "control_failed",
            "Required backup tool is unavailable": "tool_unavailable",
            "Backup source must be a real directory": "source_unavailable",
            "Referenced file failed SHA-256 verification": "file_checksum_mismatch",
            "Snapshot manifest differs from the captured manifest": "snapshot_manifest_mismatch",
            "Snapshot identity or backup namespace verification failed": "snapshot_identity_mismatch",
            "Snapshot inventory changed during retention verification": "rotation_inventory_changed",
            "Snapshot receipt is not verified": "snapshot_not_verified",
        }
        for tool, code in (("psql", "database_query"), ("pg_dump", "database_dump"), ("restic", "restic")):
            reasons[tool + " failed; no successful result was recorded"] = code + "_failed"
            reasons[tool + " timed out; no success was recorded"] = code + "_timeout"
        return reasons.get(str(error), "backup_failure")
    if isinstance(error, PermissionError):
        return "permission_denied"
    if isinstance(error, FileNotFoundError):
        return "file_or_tool_missing"
    if isinstance(error, OSError):
        return "filesystem_or_process_error"
    return "unexpected_failure"


def now_iso():
    return datetime.now(UTC).isoformat()


def private(info, *, uid=None, directory=False):
    uid = os.geteuid() if uid is None else uid
    predicate = stat.S_ISDIR if directory else stat.S_ISREG
    if (not predicate(info.st_mode) or info.st_uid != uid
            or stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600)
            or (not directory and info.st_nlink != 1)):
        raise BackupError("Unsafe private file or directory")


def read_private(path):
    path = Path(path)
    private(path.parent.lstat(), directory=True)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd) as source:
        private(os.fstat(source.fileno()))
        return json.load(source)


def atomic_json(path, value):
    path = Path(path)
    private(path.parent.lstat(), directory=True)
    if path.exists() or path.is_symlink():
        private(path.lstat())
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as output:
            temporary = Path(output.name)
            json.dump(value, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class JobLocks:
    """The same lock inodes held by the eight existing backend CLI workers."""

    def __init__(self, root, *, uid=10001, timeout=120):
        self.root, self.uid, self.timeout, self.descriptors = Path(root), uid, timeout, []

    def __enter__(self):
        try:
            private(self.root.lstat(), uid=self.uid, directory=True)
            directory = self.root / ".jobs"
            try:
                directory.mkdir(mode=0o700)
                if self.uid != os.geteuid():
                    os.chown(directory, self.uid, -1)
            except FileExistsError:
                pass
            private(directory.lstat(), uid=self.uid, directory=True)
            deadline = time.monotonic() + self.timeout
            for name in JOB_NAMES:
                path = directory / f"{name}.lock"
                try:
                    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW, 0o600)
                    if self.uid != os.geteuid():
                        os.fchown(fd, self.uid, -1)
                except FileExistsError:
                    fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
                self.descriptors.append(fd)
                private(os.fstat(fd), uid=self.uid)
                while True:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if time.monotonic() >= deadline:
                            raise BackupError("Writer job drain timed out") from None
                        time.sleep(min(0.05, max(0, deadline - time.monotonic())))
            return self
        except BaseException:
            self.close()
            raise

    def close(self):
        while self.descriptors:
            os.close(self.descriptors.pop())

    def __exit__(self, *args):
        self.close()


def evaluate(timer, state, *, now):
    if (timer.get("LoadState") != "loaded" or timer.get("ActiveState") != "active"
            or timer.get("UnitFileState") != "enabled"):
        return {"status": "critical", "reason": "timer_inactive"}
    if not isinstance(state, dict):
        return {"status": "critical", "reason": "never_completed"}
    if state.get("status") == "running":
        try:
            age = now - datetime.fromisoformat(state["started_at"]).timestamp()
        except (KeyError, ValueError, TypeError):
            age = -1
        return {"status": "ok" if 0 <= age <= 1800 else "critical",
                "reason": "running" if 0 <= age <= 1800 else "run_stuck"}
    if state.get("status") != "success":
        return {"status": "critical", "reason": "run_failed"}
    if (state.get("verified") is not True or state.get("rotation") != "success"
            or not re.fullmatch(r"[0-9a-f]{64}", str(state.get("snapshot", "")))):
        return {"status": "critical", "reason": "snapshot_unverified"}
    try:
        age = now - datetime.fromisoformat(state["finished_at"]).timestamp()
    except (KeyError, ValueError, TypeError):
        age = -1
    return {"status": "ok" if 0 <= age <= 26 * 3600 else "critical",
            "reason": "completed" if 0 <= age <= 26 * 3600 else "run_stale"}


def command(argv, *, input_text=None, timeout=60):
    """Never forward Docker/tool output to journals, including on failure."""
    process = None
    try:
        process = subprocess.Popen(argv, stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        output, _ = process.communicate(input_text, timeout=timeout)
        if process.returncode:
            raise BackupError("Control command failed")
        return output
    except (OSError, subprocess.TimeoutExpired):
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
        raise BackupError("Control command unavailable or timed out") from None



class Docker:
    def __init__(self, configuration):
        self.configuration = configuration

    def inspect(self, reference):
        items = json.loads(command(["docker", "inspect", reference], timeout=15))
        if not isinstance(items, list) or len(items) != 1:
            raise BackupError("Expected one exact container")
        item = items[0]
        return {
            "id": item["Id"], "image": item["Image"],
            "running": item["State"]["Running"],
            "health": item["State"].get("Health", {}).get("Status"),
            "started_at": item["State"]["StartedAt"],
            "exit_code": item["State"].get("ExitCode"),
            "oom_killed": item["State"].get("OOMKilled", False),
            "labels": item["Config"].get("Labels", {}),
            "user": item["Config"].get("User"),
            "mounts": [{key: mount.get(key) for key in
                        ("Type", "Name", "Source", "Destination", "RW")}
                       for mount in item["Mounts"]],
        }

    def service(self, service):
        project = self.configuration["project"]
        ids = command(["docker", "ps", "-a", "--filter",
                       f"label=com.docker.compose.project={project}", "--filter",
                       f"label=com.docker.compose.service={service}", "--format", "{{.ID}}"]).split()
        if len(ids) != 1:
            raise BackupError("Expected one canonical service container")
        item = self.inspect(ids[0])
        if (item["labels"].get("com.docker.compose.project") != project
                or item["labels"].get("com.docker.compose.service") != service):
            raise BackupError("Unexpected Compose container identity")
        return item

    def start(self, reference):
        command(["docker", "start", reference], timeout=30)

    def stop(self, reference):
        # Never let Docker escalate to SIGKILL. Recovery must settle actual exit.
        command(["docker", "stop", "--timeout", "-1", reference], timeout=90)

    def sql(self, database, statement):
        postgres = self.service("postgres")
        output = command([
            "docker", "exec", "-i", "--user", "postgres",
            "-e", "PGOPTIONS=-c default_transaction_read_only=on -c statement_timeout=5000",
            postgres["id"], "psql", "-X", "-qAt", "-v", "ON_ERROR_STOP=1",
            "-U", "postgres", "-d", database,
        ], input_text="BEGIN READ ONLY;\n" + statement.rstrip(";") + ";\nROLLBACK;\n", timeout=15)
        return json.loads(output)


def recover_pending(configuration, *, docker=None):
    """Settle issued daemon-side stops before starting and acknowledging recovery."""
    path = Path(configuration["state_dir"]) / "pending.json"
    if not path.exists() and not path.is_symlink():
        return
    pending = read_private(path)
    if pending.get("version") != 1 or not isinstance(pending.get("entries"), list):
        raise BackupError("Invalid recovery journal")
    docker = docker or Docker(configuration)
    deadline = time.monotonic() + configuration.get("resume_timeout", 180)
    for entry in pending["entries"]:
        if (entry.get("service") not in ("api", "cms")
                or not re.fullmatch(r"[0-9a-f]{64}", entry.get("id", ""))
                or not re.fullmatch(r"sha256:[0-9a-f]{64}", entry.get("image", ""))):
            raise BackupError("Invalid recovery container reference")
        if not entry.get("stop_issued"):
            continue
        while True:
            item = docker.inspect(entry["id"])
            if item["id"] != entry["id"] or item["image"] != entry["image"]:
                raise BackupError("Recovery container identity changed")
            # A new start timestamp also proves that the original run actually exited.
            if not item["running"] or item["started_at"] != entry["started_at"]:
                if not entry.get("observed_exited"):
                    entry["observed_exited"] = True
                    atomic_json(path, pending)
            if entry.get("observed_exited"):
                if not item["running"]:
                    docker.start(entry["id"])
                elif item["health"] == "healthy":
                    break
            if time.monotonic() >= deadline:
                raise BackupError("Graceful stop or service recovery did not finish")
            time.sleep(min(0.05, max(0, deadline - time.monotonic())))
    path.unlink()
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class RunLock:
    def __init__(self, configuration):
        self.path = Path(configuration["state_dir"]) / "run.lock"
        self.fd = None

    def __enter__(self):
        private(self.path.parent.lstat(), directory=True)
        self.fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            private(os.fstat(self.fd))
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            os.close(self.fd)
            self.fd = None
            raise BackupError("Another backup or recovery operation is active") from None
        return self

    def __exit__(self, *args):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def notify(configuration, event):
    """Independent host SMTP. Only closed technical fields enter the message."""
    try:
        mail = read_private(Path(configuration["private_dir"]) / "mail.json")
        for key in ("host", "from", "recipient"):
            if not isinstance(mail.get(key), str) or not mail[key] or any(c in mail[key] for c in "\r\n"):
                raise BackupError("Invalid mail configuration")
        fields = {}
        for key in ("event", "stage", "error_type", "reason", "run_id"):
            value = str(event.get(key, "unknown"))
            fields[key] = value if re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", value) else "redacted"
        message = EmailMessage()
        message["From"], message["To"] = mail["from"], mail["recipient"]
        message["Subject"] = "SINEGOR backup: " + fields["event"]
        message.set_content("SINEGOR LAB backup control\n" + "\n".join(
            f"{key}: {value}" for key, value in fields.items()) + "\nUTC: " + now_iso() +
            "\nInspect the private backup state on the VPS.\n")
        context = ssl.create_default_context()
        if mail.get("use_ssl") is True:
            client = smtplib.SMTP_SSL(mail["host"], int(mail["port"]), timeout=15, context=context)
        else:
            client = smtplib.SMTP(mail["host"], int(mail["port"]), timeout=15)
        with client:
            if mail.get("use_ssl") is not True:
                client.ehlo()
                client.starttls(context=context)
                client.ehlo()
            if mail.get("username"):
                client.login(mail["username"], mail["password"])
            return not bool(client.send_message(message))
    except Exception:
        return False


def capture_backup(configuration, docker, items, args, agreements, *, on_resumed=None):
    """The callback releases writers after immutable capture, before repository work."""
    path = Path(configuration["state_dir"]) / "pending.json"
    if path.exists() or path.is_symlink():
        raise BackupError("Unresolved recovery journal")
    locks = JobLocks(agreements, uid=configuration.get("writer_uid", 10001))
    previous_handler = signal.getsignal(signal.SIGALRM)
    def expired(*_):
        raise BackupError("Consistent capture deadline exceeded")
    def resumed():
        signal.alarm(0)
        recover_pending(configuration, docker=docker)
        locks.close()
        if on_resumed is not None:
            on_resumed()
    try:
        locks.__enter__()
        docker.assert_no_extra_writers(items)
        pending = {"version": 1, "created_at": now_iso(), "entries": [
            {"service": item["service"], "id": item["id"], "image": item["image"],
             "started_at": item["started_at"], "stop_issued": False, "observed_exited": False}
            for item in items if item["service"] in ("api", "cms")]}
        atomic_json(path, pending)
        signal.signal(signal.SIGALRM, expired)
        signal.alarm(300)
        for entry in pending["entries"]:
            entry["stop_issued"] = True
            atomic_json(path, pending)
            docker.stop(entry["id"])
            item = docker.inspect(entry["id"])
            if item["running"] or item.get("oom_killed") or item.get("exit_code") == 137:
                raise BackupError("Writer did not stop gracefully")
            entry["observed_exited"] = True
            atomic_json(path, pending)
        clients = docker.sql("postgres", "SELECT count(*) FROM pg_stat_activity WHERE "
                             "datname IN ('sinegor','sinegor_cms') AND backend_type='client backend'")
        if clients != 0:
            raise BackupError("Unexpected database writer connection")
        return backup.backup(args, on_captured=resumed)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous_handler)
        try:
            if path.exists() or path.is_symlink():
                recover_pending(configuration, docker=docker)
        finally:
            locks.close()


def mount_source(item, volume, destination):
    mounts = [m for m in item["mounts"] if m["Destination"] == destination]
    if len(mounts) != 1:
        raise BackupError("Expected one canonical data mount")
    mount = mounts[0]
    if mount["Type"] != "volume" or mount["Name"] != volume or mount["RW"] is not True:
        raise BackupError("Unexpected data mount")
    source = Path(mount["Source"])
    if not source.is_absolute() or source.resolve() != source or not source.is_dir():
        raise BackupError("Unsafe data source")
    return source


def assert_no_extra_writers(self, items):
    permitted = {item["id"] for item in items}
    protected = [Path(m["Source"]) for item in items for m in item["mounts"]
                 if m.get("Source") and m.get("Destination") in (
                     "/var/lib/sinegor/agreements", "/var/lib/sinegor/destruction",
                     "/app/public/uploads", "/var/lib/postgresql/data")]
    for reference in command(["docker", "ps", "-q", "--no-trunc"]).split():
        if reference in permitted:
            continue
        candidate = self.inspect(reference)
        for mount in candidate["mounts"]:
            if not mount.get("RW") or not mount.get("Source"):
                continue
            source = Path(mount["Source"]).resolve()
            if any(source == p or source in p.parents or p in source.parents for p in protected):
                raise BackupError("Unexpected container can write protected data")


Docker.assert_no_extra_writers = assert_no_extra_writers


def configure_environment(configuration):
    for name in list(os.environ):
        if name.startswith(("PG", "RESTIC_")):
            os.environ.pop(name)
    state = Path(configuration["state_dir"])
    for name in ("tmp", "cache", "receipts", "runs", "restore"):
        private((state / name).lstat(), directory=True)
    os.environ.update({
        "RESTIC_REPOSITORY": configuration["repository"],
        "RESTIC_PASSWORD_FILE": configuration["restic_password_file"],
        "RESTIC_CACHE_DIR": str(state / "cache"),
        "SINEGOR_BACKUP_CONFIG": configuration.get("config_path", "/etc/sinegor/backup/config.json"),
        "PGSERVICEFILE": "/tmp/sinegor-backup/pg_service.conf",
        "PGPASSFILE": "/tmp/sinegor-backup/pgpass",
        "TMPDIR": str(state / "tmp"),
        "PATH": str(Path(__file__).resolve().parent / "bin") + ":/usr/local/bin:/usr/bin:/bin",
        "SINEGOR_ENV_FILE": "/dev/null",
    })
    tempfile.tempdir = str(state / "tmp")
    sys.path.insert(0, str(Path(configuration["project_root"]) / "apps/api/src"))


def install_libpq(configuration, postgres):
    for name in ("pg_service.conf", "pgpass"):
        path = Path(configuration["private_dir"]) / name
        private(path.lstat())
        value = path.read_text()
        command(["docker", "exec", "-i", "--user", "postgres", postgres["id"], "sh", "-c",
                 "umask 077; test ! -L /tmp/sinegor-backup && mkdir -p /tmp/sinegor-backup && "
                 "chmod 700 /tmp/sinegor-backup && test ! -L /tmp/sinegor-backup/" + name +
                 " && cat > /tmp/sinegor-backup/" + name + " && chmod 600 /tmp/sinegor-backup/" + name],
                input_text=value, timeout=15)


def preflight(configuration, docker):
    items = []
    for service in ("api", "cms", "postgres"):
        item = docker.service(service)
        if (item["image"] != configuration["images"][service] or not item["running"]
                or item["health"] != "healthy"):
            raise BackupError("Source service is not canonical and healthy")
        item["service"] = service
        items.append(item)
    api, cms, postgres = items
    if api["user"] != "10001:10001":
        raise BackupError("Unexpected writer UID")
    jobs = json.loads(command(["docker", "exec", api["id"], "python", "-c",
        "import json; from sinegor.jobs.runtime import PERIODIC_JOBS; print(json.dumps(sorted(PERIODIC_JOBS)))"], timeout=15))
    if sorted(jobs) != sorted(JOB_NAMES):
        raise BackupError("Writer job inventory changed")
    prefix = configuration["project"] + "_"
    sources = {
        "agreements": mount_source(api, prefix + "agreements", "/var/lib/sinegor/agreements"),
        "destruction": mount_source(api, prefix + "destruction", "/var/lib/sinegor/destruction"),
        "uploads": mount_source(cms, prefix + "cms_uploads", "/app/public/uploads"),
    }
    mount_source(postgres, prefix + "postgres_data", "/var/lib/postgresql/data")
    if any(str(value) != configuration["sources"][key] for key, value in sources.items()):
        raise BackupError("Source path differs from approved configuration")
    database_bytes = docker.sql("postgres", "SELECT pg_database_size('sinegor') + pg_database_size('sinegor_cms')")
    file_bytes = sum(p.lstat().st_size for source in sources.values() for p in source.rglob("*") if p.is_file())
    payload = max(256 * 1024 ** 2, file_bytes + 2 * database_bytes + 64 * 1024 ** 2)
    free = os.statvfs(configuration["state_dir"])
    available = free.f_bavail * free.f_frsize
    required = 5 * GIB + 4 * payload + 2 * database_bytes
    if available < required:
        raise BackupError("Insufficient free disk space before capture")
    return items, sources, {"database_bytes": database_bytes, "file_bytes": file_bytes,
                            "payload_budget": payload, "free_before": available, "required_free": required}


def run_backup(configuration):
    if configuration.get("activation_approved") is not True:
        raise BackupError("Production availability window has not been approved")
    configure_environment(configuration)
    with RunLock(configuration):
        recover_pending(configuration)
        state_root = Path(configuration["state_dir"])
        run_id = uuid.uuid4().hex
        state = {"version": 1, "run_id": run_id, "started_at": now_iso(), "status": "running",
                 "stage": "preflight", "verified": False, "rotation": "not_started"}
        def save():
            atomic_json(state_root / "last-run.json", state)
            atomic_json(state_root / "runs" / (run_id + ".json"), state)
        save()
        try:
            docker = Docker(configuration)
            items, sources, metrics = preflight(configuration, docker)
            state["metrics"] = metrics
            install_libpq(configuration, next(item for item in items if item["service"] == "postgres"))
            receipt = state_root / "receipts" / (run_id + ".json")
            args = SimpleNamespace(api_service="sinegor_backup_api", cms_service="sinegor_backup_cms",
                agreements=sources["agreements"], uploads=sources["uploads"],
                destruction_archive=sources["destruction"], receipt=receipt, writers_stopped=True,
                restic=configuration["restic"], capture_timeout=120)
            state["stage"] = "capture"
            save()
            def resumed():
                state["stage"] = "snapshot"
                save()
            capture_backup(configuration, docker, items, args, sources["agreements"], on_resumed=resumed)
            accepted = read_private(receipt)
            if accepted.get("verified") is not True:
                raise BackupError("Snapshot receipt is not verified")
            state.update(snapshot=accepted["snapshot"], verified=True, stage="rotation", rotation="running")
            save()
            backup.rotate(SimpleNamespace(restic=configuration["restic"], execute=True))
            free = os.statvfs(state_root)
            state.update(status="success", stage="complete", rotation="success",
                         free_after=free.f_bavail * free.f_frsize)
        except Exception as exc:
            state.update(status="failed", error_type=type(exc).__name__, reason=failure_reason(exc),
                         recovery_pending=(state_root / "pending.json").exists())
            state["alert_sent"] = notify(configuration, {"event": "backup_failed", "stage": state["stage"],
                                                          "error_type": type(exc).__name__, "reason": failure_reason(exc), "run_id": run_id})
        finally:
            state["finished_at"] = now_iso()
            save()
        print(json.dumps({key: state[key] for key in ("run_id", "status", "stage", "verified", "rotation")}))
        return 0 if state["status"] == "success" else 1


def load_config(path):
    path = Path(path)
    cfg = read_private(path)
    if (cfg.get("version") != 1 or cfg.get("project") != "sinegor-lab-prod"
            or not isinstance(cfg.get("activation_approved"), bool) or cfg.get("writer_uid") != 10001):
        raise BackupError("Invalid production configuration")
    for name in ("project_root", "private_dir", "state_dir", "repository", "restic", "restic_password_file"):
        item = Path(cfg[name])
        if not item.is_absolute() or item.resolve() != item:
            raise BackupError("Configuration paths must be canonical")
    if (Path(cfg["repository"]) != Path(cfg["state_dir"]) / "repository"
            or Path(cfg["restic_password_file"]).parent != Path(cfg["private_dir"])):
        raise BackupError("Invalid private path boundaries")
    for name in ("private_dir", "state_dir", "repository"):
        private(Path(cfg[name]).lstat(), directory=True)
    private(Path(cfg["restic_password_file"]).lstat())
    cfg["config_path"] = str(path)
    return cfg


def timer_properties():
    output = command(["systemctl", "show", "sinegor-backup.timer", "--property=LoadState,ActiveState,UnitFileState"])
    return dict(line.split("=", 1) for line in output.splitlines() if "=" in line)


def watchdog(configuration):
    root = Path(configuration["state_dir"])
    state = read_private(root / "last-run.json") if (root / "last-run.json").exists() else None
    verdict = evaluate(timer_properties(), state, now=time.time())
    if verdict["reason"] == "completed":
        try:
            lock = RunLock(configuration)
            lock.__enter__()
        except BackupError:
            # An active manual backup/restore owns the repository. Retry next tick.
            verdict = {"status": "ok", "reason": "operation_active"}
        else:
            try:
                state = read_private(root / "last-run.json")
                verdict = evaluate(timer_properties(), state, now=time.time())
                if verdict["reason"] == "completed":
                    if not re.fullmatch(r"[0-9a-f]{32}", str(state.get("run_id", ""))):
                        raise BackupError("Invalid accepted run identity")
                    receipt = read_private(root / "receipts" / (state["run_id"] + ".json"))
                    if (receipt.get("version") != 1 or receipt.get("verified") is not True
                            or receipt.get("snapshot") != state["snapshot"]):
                        raise BackupError("Receipt differs from accepted result")
                    backup.managed_snapshot_ids(state["snapshot"])
            except (BackupError, OSError, ValueError, KeyError, TypeError):
                verdict = {"status": "critical", "reason": "accepted_result_missing"}
            finally:
                lock.__exit__()
    if (root / "pending.json").exists():
        try:
            with RunLock(configuration):
                recover_pending(configuration)
        except BackupError:
            pass
        if (root / "pending.json").exists():
            verdict = {"status": "critical", "reason": "recovery_pending"}
    if verdict["status"] != "ok":
        alert_path = root / "alert-state.json"
        previous = read_private(alert_path) if alert_path.exists() else {}
        token = verdict["reason"] + ":" + str((state or {}).get("run_id", "none"))
        if token != previous.get("token") or time.time() - previous.get("sent_at", 0) > 6 * 3600:
            sent = notify(configuration, {"event": verdict["reason"], "stage": "watchdog",
                                          "error_type": "StateError", "run_id": (state or {}).get("run_id", "none")})
            if sent:
                atomic_json(alert_path, {"token": token, "sent_at": time.time()})
            verdict["alert_sent"] = sent
    print(json.dumps(verdict))
    return 0 if verdict["status"] == "ok" else 1


def latest_receipt(configuration, supplied=None):
    if supplied is not None:
        path = Path(supplied)
    else:
        state = read_private(Path(configuration["state_dir"]) / "last-run.json")
        if state.get("verified") is not True or not re.fullmatch(r"[0-9a-f]{32}", str(state.get("run_id", ""))):
            raise BackupError("No verified production receipt")
        path = Path(configuration["state_dir"]) / "receipts" / (state["run_id"] + ".json")
    receipt = read_private(path)
    if receipt.get("version") != 1 or receipt.get("verified") is not True or not re.fullmatch(r"[0-9a-f]{64}", str(receipt.get("snapshot", ""))):
        raise BackupError("Invalid accepted receipt")
    return path


def restore_acceptance(configuration, supplied=None):
    with RunLock(configuration):
        receipt = latest_receipt(configuration, supplied)
        docker = Docker(configuration)
        for service in ("api", "cms", "postgres"):
            if docker.service(service)["image"] != configuration["images"][service]:
                raise BackupError("Application image differs from accepted source")
        state = Path(configuration["state_dir"])
        report = state / "runs" / ("restore-" + uuid.uuid4().hex + ".json")
        args = [sys.executable, "-B", str(Path(__file__).resolve().with_name("restore_acceptance.py")),
                "--receipt", str(receipt), "--restic", configuration["restic"],
                "--work-root", str(state / "restore"), "--report", str(report),
                "--project-root", configuration["project_root"]]
        for service in ("postgres", "api", "cms"):
            args.extend(["--" + service + "-image", configuration["images"][service]])
        command(args, timeout=900)
        result = read_private(report)
        atomic_json(state / "last-restore.json", result)
        print(json.dumps(result))
        return 0


def controlled_failure(configuration):
    with RunLock(configuration):
        state = Path(configuration["state_dir"])
        detected = False
        with tempfile.TemporaryDirectory(prefix="failure-test-", dir=state / "tmp") as directory:
            try:
                backup.run([configuration["restic"], "--repo", str(Path(directory) / "missing"), "check"], timeout=30)
            except BackupError:
                detected = True
        sent = notify(configuration, {"event": "controlled_failure", "stage": "acceptance",
                                      "error_type": "SyntheticResticFailure", "run_id": "selftest"}) if detected else False
        result = {"version": 1, "at": now_iso(), "detected": detected, "alert_sent": sent}
        atomic_json(state / "failure-selftest.json", result)
        print(json.dumps(result))
        return 0 if detected and sent else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("run", "watchdog", "recover", "show", "snapshots", "check", "rotate", "restore-test", "test-alert", "test-failure"))
    parser.add_argument("--config", type=Path, default=Path("/etc/sinegor/backup/config.json"))
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise BackupError("Production controls require root")
    os.umask(0o077)
    cfg = {"private_dir": "/etc/sinegor/backup"}
    try:
        cfg = load_config(args.config)
        configure_environment(cfg)
        if args.action == "run":
            return run_backup(cfg)
        if args.action == "watchdog":
            return watchdog(cfg)
        if args.action == "recover":
            with RunLock(cfg):
                recover_pending(cfg)
            return 0
        if args.action == "show":
            print(json.dumps(read_private(Path(cfg["state_dir"]) / "last-run.json")))
            return 0
        if args.action == "restore-test":
            return restore_acceptance(cfg, args.receipt)
        if args.action == "test-alert":
            sent = notify(cfg, {"event": "channel_test", "stage": "acceptance", "error_type": "None", "run_id": "selftest"})
            print(json.dumps({"alert_sent": sent}))
            return 0 if sent else 1
        if args.action == "test-failure":
            return controlled_failure(cfg)
        with RunLock(cfg):
            if args.action == "snapshots":
                snapshots = json.loads(backup.run(["restic", "snapshots", "--json"]))
                print(json.dumps([{key: item.get(key) for key in ("id", "time", "hostname", "tags")} for item in snapshots]))
            elif args.action == "check":
                backup.run([cfg["restic"], "check", "--read-data"], timeout=600)
                print(json.dumps({"check_read_data": "success"}))
            elif args.action == "rotate":
                receipt = read_private(latest_receipt(cfg, args.receipt))
                backup.verify_snapshot(receipt["snapshot"])
                backup.rotate(SimpleNamespace(restic=cfg["restic"], execute=True))
                print(json.dumps({"rotation": "success"}))
        return 0
    except Exception as error:
        sent = notify(cfg, {"event": "control_failed", "stage": args.action,
                            "error_type": type(error).__name__, "reason": failure_reason(error), "run_id": "startup_or_control"})
        print(json.dumps({"status": "failed", "action": args.action,
                          "error_type": type(error).__name__, "reason": failure_reason(error), "alert_sent": sent}), file=sys.stderr)
        return 1



if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (BackupError, OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"status": "failed", "error_type": type(error).__name__}), file=sys.stderr)
        raise SystemExit(1)
