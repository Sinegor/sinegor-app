"""Process and filesystem isolation for the live integration suite (POSIX)."""

import os
import shutil
import signal
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


class HarnessError(RuntimeError):
    """A safe diagnostic; never include commands, environment or upstream bodies."""


def isolated_environment() -> dict[str, str]:
    names = ("PATH", "HOME", "USER", "LANG", "LC_ALL", "PLAYWRIGHT_BROWSERS_PATH")
    return {name: os.environ[name] for name in names if name in os.environ} | {
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def snapshot(source: Path, destination: Path) -> None:
    excluded = {
        ".git",
        ".agents",
        ".codex",
        ".aws",
        ".venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".react-router",
        ".strapi",
        ".cache",
        ".tmp",
        "build",
        "dist",
        "test-results",
        "playwright-report",
        "backups",
    }
    private = {"apps/api/storage", "apps/cms/public/uploads", "docs/reports"}

    def ignore(directory: str, names: list[str]) -> list[str]:
        parent = Path(directory).relative_to(source)
        return [
            name
            for name in names
            if name in excluded or name.startswith(".env") or (parent / name).as_posix() in private
        ]

    shutil.copytree(source, destination, ignore=ignore)
    for app in ("web", "cms"):
        modules = source / "apps" / app / "node_modules"
        if modules.is_dir():
            (destination / "apps" / app / "node_modules").symlink_to(modules.resolve(), True)
    (destination / "apps/cms/public/uploads").mkdir(parents=True, exist_ok=True)


class ProcessStack:
    def __init__(self, private: Path):
        self.private = private
        self.processes: list[subprocess.Popen] = []
        self.cleanup_complete = False

    def __enter__(self):
        return self

    def start(
        self, name: str, command: list[str], cwd: Path, env: dict[str, str]
    ) -> subprocess.Popen:
        with (self.private / f"{name}.log").open("wb") as log:
            process = subprocess.Popen(
                command,
                cwd=cwd,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        self.processes.append(process)
        return process

    def stage(
        self,
        name: str,
        command: list[str],
        cwd: Path,
        env: dict[str, str],
        timeout: int = 120,
    ) -> None:
        process = self.start(name, command, cwd, env)
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            raise HarnessError(f"{name}: timed out") from None
        if code:
            raise HarnessError(f"{name}: exit {code}")

    def __exit__(self, *_):
        # The runner's handler raises InterruptedError. A second interrupt must not
        # abort cleanup before stubborn descendants receive SIGKILL.
        previous = {
            number: signal.signal(number, signal.SIG_IGN)
            for number in (signal.SIGINT, signal.SIGTERM)
        }
        try:
            self._stop_processes()
            self.cleanup_complete = True
        finally:
            for number, handler in previous.items():
                signal.signal(number, handler)

    def _stop_processes(self):
        # Kill the process group even if its parent already exited (npm/SSR children).
        for process in reversed(self.processes):
            try:
                os.killpg(process.pid, signal.SIGCONT)
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + 5
        for process in reversed(self.processes):
            try:
                process.wait(timeout=max(0.01, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                pass
        for process in reversed(self.processes):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()


def wait_http(url: str, process: subprocess.Popen, expected: int = 200, timeout: int = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise HarnessError("Service exited before readiness")
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == expected:
                    return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.1)
    raise HarnessError("Service readiness timed out")
