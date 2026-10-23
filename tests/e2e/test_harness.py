"""Safety of the disposable runner; no application or Docker is needed."""

import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from api import isolated_lookup
from configuration import load_config
from harness import ProcessStack, isolated_environment, snapshot
from run import remove_container


class HarnessSafetyTests(unittest.TestCase):
    def test_signal_during_cleanup_still_forces_stubborn_child_to_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ready, stopping = root / "ready", root / "stopping"
            code = (
                "import signal,time,pathlib,sys; "
                "signal.signal(signal.SIGTERM, lambda *_: pathlib.Path(sys.argv[2]).touch()); "
                "pathlib.Path(sys.argv[1]).touch(); time.sleep(60)"
            )
            stack = ProcessStack(root)
            child = None
            interrupted = False
            delivered = threading.Event()

            def interrupt_cleanup():
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline and not stopping.exists():
                    time.sleep(0.01)
                if stopping.exists():
                    os.kill(os.getpid(), signal.SIGTERM)
                    delivered.set()

            def handle_signal(*_):
                raise InterruptedError()

            previous = signal.signal(signal.SIGTERM, handle_signal)
            sender = threading.Thread(target=interrupt_cleanup)
            try:
                try:
                    with stack:
                        child = stack.start(
                            "stubborn",
                            [sys.executable, "-c", code, str(ready), str(stopping)],
                            root,
                            isolated_environment(),
                        )
                        deadline = time.monotonic() + 3
                        while time.monotonic() < deadline and not ready.exists():
                            time.sleep(0.01)
                        self.assertTrue(ready.exists())
                        sender.start()
                except InterruptedError:
                    interrupted = True
                self.assertFalse(interrupted, "signal aborted process cleanup")
                self.assertTrue(delivered.is_set())
                self.assertIsNotNone(child.poll(), "stubborn child survived cleanup")
                self.assertTrue(stack.cleanup_complete)
                self.assertIs(signal.getsignal(signal.SIGTERM), handle_signal)
            finally:
                if sender.ident is not None:
                    sender.join(timeout=4)
                signal.signal(signal.SIGTERM, previous)
                if child is not None and child.poll() is None:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()

    def test_ambient_credentials_and_runtime_hooks_are_not_inherited(self):
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "a-working-database",
                "SMTP_PASSWORD": "a-working-password",
                "YANDEX_DISK_TOKEN": "a-working-token",
                "NODE_OPTIONS": "--require=unexpected-hook",
                "PYTHONPATH": "/unexpected/code",
            },
        ):
            env = isolated_environment()
        for name in (
            "DATABASE_URL",
            "SMTP_PASSWORD",
            "YANDEX_DISK_TOKEN",
            "NODE_OPTIONS",
            "PYTHONPATH",
        ):
            self.assertNotIn(name, env)
        self.assertIn("PATH", env)

    def test_snapshot_excludes_private_data_but_keeps_storage_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, destination = root / "source", root / "snapshot"
            source.mkdir()
            for name in (
                ".env",
                "apps/api/.env",
                "apps/cms/.env.local",
                "apps/api/storage/agreements/private.pdf",
                "apps/cms/public/uploads/private.jpg",
            ):
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("private")
            module = Path("apps/api/src/sinegor/integrations/storage/__init__.py")
            (source / module).parent.mkdir(parents=True)
            (source / module).write_text("# source, not document storage\n")
            snapshot(source, destination)
            self.assertTrue((destination / module).is_file())
            self.assertFalse(list(destination.rglob(".env*")))
            self.assertFalse(list(destination.rglob("private.*")))
            self.assertTrue((destination / "apps/cms/public/uploads").is_dir())

    def test_startup_failure_still_stops_processes_already_started(self):
        with tempfile.TemporaryDirectory() as directory:
            stack = ProcessStack(Path(directory))
            with self.assertRaises(FileNotFoundError), stack:
                child = stack.start(
                    "first",
                    [sys.executable, "-c", "import time; time.sleep(60)"],
                    Path(directory),
                    isolated_environment(),
                )
                stack.start("missing", ["/no-such-e2e-executable"], Path(directory), {})
            self.assertIsNotNone(child.poll())

    def test_context_cleanup_stops_descendants_not_only_the_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pid_file = root / "child.pid"
            code = (
                "import subprocess,sys,time,pathlib; "
                "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
                "pathlib.Path(sys.argv[1]).write_text(str(child.pid)); time.sleep(60)"
            )
            with ProcessStack(root) as stack:
                stack.start(
                    "tree",
                    [sys.executable, "-c", code, str(pid_file)],
                    root,
                    isolated_environment(),
                )
                subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        "import pathlib,sys,time; p=pathlib.Path(sys.argv[1]); "
                        "\nfor _ in range(100):\n if p.exists():break\n time.sleep(.01)\n"
                        "else:sys.exit(1)",
                        str(pid_file),
                    ],
                    check=True,
                )
                child_pid = int(pid_file.read_text())
            status = Path(f"/proc/{child_pid}/stat")
            self.assertTrue(not status.exists() or status.read_text().split()[2] == "Z")


class BoundarySafetyTests(unittest.TestCase):
    def test_configuration_rejects_working_database_before_importing_application(self):
        with tempfile.TemporaryDirectory(prefix="sinegor-e2e-private-") as directory:
            root = Path(directory)
            config = {
                "run_id": "012345abcdef",
                "private": str(root),
                "api_env": {
                    "APP_ENV": "test",
                    "DATABASE_URL": "postgresql+psycopg://role:secret@127.0.0.1/work",
                },
            }
            file = root / "run.json"
            file.write_text(json.dumps(config))
            with patch.dict(os.environ, {"SINEGOR_E2E_CONFIG": str(file)}):
                with self.assertRaisesRegex(RuntimeError, "non-E2E database"):
                    load_config()

    def test_provider_resolution_is_local_and_unrelated_networking_is_blocked(self):
        lookup = isolated_lookup(socket.getaddrinfo, 23456)
        for host in ("cloud-api.yandex.net", "api.telegram.org"):
            addresses = lookup(host, 443, type=socket.SOCK_STREAM)
            self.assertEqual(addresses[0][4], ("127.0.0.1", 23456))
        self.assertEqual(
            lookup("127.0.0.1", 5432, type=socket.SOCK_STREAM)[0][4], ("127.0.0.1", 5432)
        )
        with self.assertRaises(socket.gaierror):
            lookup("unrelated.example.org", 443)

    def test_cleanup_refuses_foreign_container_even_when_name_matches(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sentinel = root / "container-still-exists"
            sentinel.touch()
            executable = root / "docker"
            executable.write_text(
                "#!" + sys.executable + "\nimport sys,pathlib\n"
                "if sys.argv[1]=='ps':print('container-id')\n"
                "elif sys.argv[1]=='inspect':print('another-run')\n"
                "elif sys.argv[1]=='rm':pathlib.Path(" + repr(str(sentinel)) + ").unlink()\n"
            )
            executable.chmod(0o700)
            with patch.dict(os.environ, {"PATH": str(root) + os.pathsep + os.environ["PATH"]}):
                with self.assertRaisesRegex(RuntimeError, "another run"):
                    remove_container("sinegor-e2e-012345abcdef", "012345abcdef")
            self.assertTrue(sentinel.exists())


if __name__ == "__main__":
    unittest.main()
