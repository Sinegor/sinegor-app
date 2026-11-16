"""Single-host CLI exclusion and durable safe run state on the shared private volume."""

import fcntl
import json
import os
import stat
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from sinegor.core.config import Settings
from sinegor.core.logging import configure_logging

PERIODIC_JOBS = (
    "process_orders",
    "process_notifications",
    "cleanup_agreements",
    "purge_auth",
    "purge_analytics",
    "purge_security_events",
    "cleanup_business",
    "process_destructions",
)
SCHEDULED_JOBS = PERIODIC_JOBS[:-1]


class JobBusy(Exception):
    pass


def _private(info: os.stat_result, *, directory: bool = False) -> None:
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    mode = 0o700 if directory else 0o600
    if not kind(info.st_mode) or stat.S_IMODE(info.st_mode) != mode or info.st_uid != os.geteuid():
        raise PermissionError("Unsafe job state permissions")
    if not directory and info.st_nlink != 1:
        raise PermissionError("Unsafe job state link")


class JobLock:
    def __init__(self, root: Path, name: str):
        if name not in PERIODIC_JOBS:
            raise ValueError("Unknown periodic job")
        self.root, self.name, self.fd = root, name, None

    def __enter__(self):
        try:
            self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
            _private(self.root.lstat(), directory=True)
            directory = self.root / ".jobs"
            directory.mkdir(mode=0o700, exist_ok=True)
            _private(directory.lstat(), directory=True)
            self.fd = os.open(
                directory / f"{self.name}.lock",
                os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
            )
            _private(os.fstat(self.fd))
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise JobBusy from None
            return self
        except BaseException:
            if self.fd is not None:
                os.close(self.fd)
                self.fd = None
            raise

    def __exit__(self, *args):
        if self.fd is not None:
            os.close(self.fd)  # Never unlink: all contenders must lock the same inode.
            self.fd = None


def read_state(root: Path, name: str) -> dict:
    if name not in PERIODIC_JOBS:
        raise ValueError("Unknown periodic job")
    directory = root / ".jobs"
    _private(root.lstat(), directory=True)
    _private(directory.lstat(), directory=True)
    fd = os.open(directory / f"{name}.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(fd) as source:
        _private(os.fstat(source.fileno()))
        value = json.loads(source.read(8193))
    if not isinstance(value, dict) or value.get("job") != name:
        raise ValueError("Invalid job state")
    return value


def _write_state(root: Path, name: str, value: dict) -> None:
    directory = root / ".jobs"
    temp = directory / f".{name}.{uuid4().hex}.tmp"
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as output:
            json.dump(value, output)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp, directory / f"{name}.json")
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        temp.unlink(missing_ok=True)


def _event(name: str, event: str, **safe_fields) -> None:
    print(json.dumps({"event": event, "job": name, **safe_fields}), file=sys.stderr, flush=True)


def run_job(
    name: str,
    settings_loader: Callable[[], Settings],
    work: Callable[[Settings], int | None],
    *,
    record: bool = True,
) -> int:
    configure_logging("INFO")  # Settings errors and SQL diagnostics may contain secrets.
    if name not in PERIODIC_JOBS:
        _event("unknown", "job_run_failed", error_type="UnknownJob")
        return 1
    try:
        settings = settings_loader()
        with JobLock(settings.agreement_storage_dir, name):
            previous = {}
            if record:
                try:
                    previous = read_state(settings.agreement_storage_dir, name)
                except FileNotFoundError:
                    pass
            state = {
                "job": name,
                "run_id": uuid4().hex,
                "status": "running",
                "started_at": datetime.now(UTC).isoformat(),
                "finished_at": None,
                "last_success_at": previous.get("last_success_at"),
                "duration_ms": None,
                "exit_code": None,
                "error_type": None,
            }
            if record:
                _write_state(settings.agreement_storage_dir, name, state)
            _event(name, "job_run_started" if record else "job_preview_started")
            started = perf_counter()
            code, error = 1, None
            try:
                code = work(settings) or 0
                if type(code) is not int or code not in (0, 1):
                    raise ValueError("Invalid job exit code")
            except Exception as exc:
                code, error = 1, type(exc).__name__
            state.update(
                status="success" if code == 0 else "failed",
                finished_at=datetime.now(UTC).isoformat(),
                duration_ms=round((perf_counter() - started) * 1000, 2),
                exit_code=code,
                error_type=error,
            )
            if code == 0:
                state["last_success_at"] = state["finished_at"]
            if record:
                _write_state(settings.agreement_storage_dir, name, state)
            _event(
                name,
                "job_run_completed" if code == 0 else "job_run_failed",
                exit_code=code,
                duration_ms=state["duration_ms"],
                error_type=error,
            )
            return code
    except JobBusy:
        _event(name, "job_lock_busy", exit_code=75)
        return 75
    except Exception as exc:
        _event(name, "job_run_failed", exit_code=1, error_type=type(exc).__name__)
        return 1
