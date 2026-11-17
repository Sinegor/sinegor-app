"""Real filesystem/lock and safe recovery regressions, without production access."""

import fcntl
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
API = "a" * 64
IMAGE = "sha256:" + "b" * 64


class ProductionTests(unittest.TestCase):
    def module(self):
        path = HERE / "production.py"
        self.assertTrue(path.is_file(), "production controller must be implemented")
        sys.path.insert(0, str(HERE))
        spec = importlib.util.spec_from_file_location("production_backup", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def probe(self, path):
        code = """
import fcntl,os,sys
fd=os.open(sys.argv[1],os.O_RDWR)
try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
except BlockingIOError:sys.exit(75)
"""
        return subprocess.run([sys.executable, "-c", code, str(path)],
                              capture_output=True, timeout=5).returncode

    def test_shared_job_lock_blocks_another_process_until_release(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with tool.JobLocks(root, uid=os.geteuid(), timeout=0.02):
                path = root / ".jobs" / "process_orders.lock"
                self.assertEqual(self.probe(path), 75)
            self.assertEqual(self.probe(path), 0)

    def test_partial_lock_timeout_releases_every_previously_acquired_lock(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            jobs = root / ".jobs"
            jobs.mkdir(mode=0o700)
            path = jobs / "process_notifications.lock"
            path.touch(mode=0o600)
            fd = os.open(path, os.O_RDWR)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                with self.assertRaises(tool.BackupError):
                    with tool.JobLocks(root, uid=os.geteuid(), timeout=0.02):
                        self.fail("busy job must prevent capture")
                self.assertEqual(self.probe(jobs / "process_orders.lock"), 0)
            finally:
                os.close(fd)

    def test_private_journal_refuses_symlink_and_publishes_complete_json(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root / "outside"
            outside.write_text("must remain")
            pending = root / "pending.json"
            pending.symlink_to(outside)
            with self.assertRaises(tool.BackupError):
                tool.atomic_json(pending, {"stage": "stopped"})
            self.assertEqual(outside.read_text(), "must remain")
            pending.unlink()
            tool.atomic_json(pending, {"stage": "stopped"})
            self.assertEqual(json.loads(pending.read_text()), {"stage": "stopped"})
            self.assertEqual(stat.S_IMODE(pending.stat().st_mode), 0o600)

    def test_watchdog_detects_stale_failed_and_disabled_runs(self):
        tool = self.module()
        timer = {"LoadState": "loaded", "ActiveState": "active", "UnitFileState": "enabled"}
        state = {"status": "success", "finished_at": "2026-11-17T00:00:00+00:00",
                 "verified": True, "rotation": "success", "snapshot": "c" * 64}
        now = datetime(2026, 11, 17, 12, tzinfo=UTC).timestamp()
        self.assertEqual(tool.evaluate(timer, state, now=now)["status"], "ok")
        later = datetime(2026, 11, 18, 3, tzinfo=UTC).timestamp()
        self.assertEqual(tool.evaluate(timer, state, now=later)["reason"], "run_stale")
        self.assertEqual(tool.evaluate(timer, state | {"status": "failed"}, now=now)["reason"],
                         "run_failed")
        self.assertEqual(tool.evaluate(timer | {"ActiveState": "inactive"}, state, now=now)["reason"],
                         "timer_inactive")
        self.assertEqual(tool.evaluate(timer, state | {"verified": False}, now=now)["reason"],
                         "snapshot_unverified")

    def pending(self, root):
        path = root / "pending.json"
        path.write_text(json.dumps({"version": 1, "entries": [{
            "id": API, "image": IMAGE, "service": "api", "stop_issued": True,
            "observed_exited": False, "started_at": "old",
        }]}))
        path.chmod(0o600)
        return path

    def test_recovery_settles_delayed_stop_before_start_and_journal_clear(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pending = self.pending(root)

            class Docker:
                def __init__(self):
                    self.calls = 0
                    self.exited = False
                    self.started = False

                def inspect(self, reference):
                    self.calls += 1
                    running = self.started or self.calls < 3
                    if not running:
                        self.exited = True
                    return {"id": API, "image": IMAGE, "running": running,
                            "health": "healthy" if running else None,
                            "started_at": "new" if self.started else "old"}

                def start(self, reference):
                    if not self.exited:
                        raise AssertionError("cannot race an outstanding daemon stop")
                    self.started = True

            docker = Docker()
            tool.recover_pending({"state_dir": str(root), "resume_timeout": 2}, docker=docker)
            self.assertTrue(docker.exited)
            self.assertTrue(docker.started)
            self.assertFalse(pending.exists())

    def test_recovery_keeps_journal_when_graceful_stop_never_exits(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pending = self.pending(root)

            class Docker:
                def inspect(self, reference):
                    return {"id": API, "image": IMAGE, "running": True,
                            "health": "healthy", "started_at": "old"}

                def start(self, reference):
                    raise AssertionError("do not restart or force-kill a running container")

            with self.assertRaises(tool.BackupError):
                tool.recover_pending({"state_dir": str(root), "resume_timeout": 0.01},
                                     docker=Docker())
            self.assertTrue(pending.exists())

    def test_activation_gate_refuses_backup_before_any_docker_access(self):
        tool = self.module()
        self.assertTrue(callable(getattr(tool, "run_backup", None)), "backup orchestration missing")
        with self.assertRaises(tool.BackupError):
            tool.run_backup({"activation_approved": False})

    def test_partial_stop_failure_resumes_only_the_service_we_stopped(self):
        tool = self.module()
        self.assertTrue(callable(getattr(tool, "capture_backup", None)), "capture orchestration missing")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agreements = root / "agreements"
            agreements.mkdir(mode=0o700)
            api = {"id": API, "image": IMAGE, "service": "api",
                   "running": True, "health": "healthy", "started_at": "old"}
            cms = api | {"id": "c" * 64, "service": "cms"}
            items = [api, cms]

            class Docker:
                def __init__(self):
                    self.stopped = False
                    self.started = []

                def assert_no_extra_writers(self, items):
                    return None

                def stop(self, reference):
                    self.stopped = True
                    raise tool.BackupError("synthetic client failure after daemon stop")

                def inspect(self, reference):
                    return api | {"running": not self.stopped,
                                  "started_at": "new" if self.started else "old"}

                def start(self, reference):
                    self.started.append(reference)
                    self.stopped = False

            docker = Docker()
            with self.assertRaises(tool.BackupError):
                tool.capture_backup({"state_dir": str(root), "writer_uid": os.geteuid(),
                                     "resume_timeout": 1}, docker, items, None, agreements)
            self.assertEqual(docker.started, [API])
            self.assertFalse((root / "pending.json").exists())
            self.assertEqual(self.probe(agreements / ".jobs" / "process_orders.lock"), 0)

    def test_independent_email_filters_payload_and_requires_verified_tls(self):
        from unittest.mock import patch
        tool = self.module()
        self.assertTrue(callable(getattr(tool, "notify", None)), "independent email missing")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tool.atomic_json(root / "mail.json", {
                "host": "smtp.example.invalid", "port": 465, "use_ssl": True,
                "username": "synthetic-user", "password": "synthetic-secret",
                "from": "backup@example.invalid", "recipient": "owner@example.invalid",
            })
            sent = []

            class SMTP:
                def __init__(self, host, port, **kwargs):
                    import ssl
                    self.context = kwargs["context"]
                    if self.context.verify_mode != ssl.CERT_REQUIRED:
                        raise AssertionError("SMTP must verify TLS")
                def __enter__(self):
                    return self
                def __exit__(self, *args):
                    return None
                def login(self, username, password):
                    return None
                def send_message(self, message):
                    sent.append(message)
                    return {}

            with patch.object(tool.smtplib, "SMTP_SSL", SMTP):
                result = tool.notify({"private_dir": str(root), "state_dir": str(root)}, {
                    "event": "backup_failed", "stage": "capture", "error_type": "BackupError",
                    "run_id": "synthetic-run", "details": "SQL document or password",
                })
            self.assertTrue(result)
            self.assertEqual(len(sent), 1)
            body = sent[0].get_content()
            self.assertIn("capture", body)
            self.assertNotIn("SQL document", body)
            self.assertNotIn("synthetic-secret", body)

    def test_controller_uses_real_capture_interface_and_resumes_before_snapshot(self):
        from unittest.mock import patch
        from contextlib import ExitStack
        tool = self.module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("runs", "receipts", "agreements", "uploads", "destruction"):
                (root / name).mkdir(mode=0o700)
            items = [{"id": ref * 64, "image": IMAGE, "service": service,
                      "running": True, "health": "healthy", "started_at": "original"}
                     for service, ref in (("api", "a"), ("cms", "c"), ("postgres", "d"))]
            events = []
            class Docker:
                def assert_no_extra_writers(self, entries):
                    return None
                def stop(self, reference):
                    next(i for i in items if i["id"] == reference)["running"] = False
                def inspect(self, reference):
                    return dict(next(i for i in items if i["id"] == reference))
                def start(self, reference):
                    item = next(i for i in items if i["id"] == reference)
                    item.update(running=True, started_at="new")
                    events.append("resume_" + item["service"])
                def sql(self, *args):
                    return 0
            def run(command, **kwargs):
                if command[0] == "pg_dump":
                    self.assertFalse(any(i["running"] for i in items[:2]))
                    Path(command[-1]).write_bytes(b"synthetic dump")
                    return b""
                self.assertEqual(command[:2], ["restic", "backup"])
                self.assertTrue(all(i["running"] for i in items))
                events.append("snapshot")
                return json.dumps({"message_type": "summary", "snapshot_id": "f" * 64}).encode()
            cfg = {"activation_approved": True, "state_dir": str(root), "writer_uid": os.geteuid(),
                   "resume_timeout": 1, "restic": "unused"}
            sources = {name: root / name for name in ("agreements", "uploads", "destruction")}
            with ExitStack() as stack:
                stack.enter_context(patch.object(tool, "configure_environment"))
                stack.enter_context(patch.object(tool, "Docker", return_value=Docker()))
                stack.enter_context(patch.object(tool, "preflight", return_value=(items, sources, {})))
                stack.enter_context(patch.object(tool, "install_libpq"))
                stack.enter_context(patch.object(tool, "notify", return_value=False))
                stack.enter_context(patch.object(tool.backup, "restic_environment"))
                stack.enter_context(patch.object(tool.backup, "database_info", side_effect=lambda role: {"name": role}))
                stack.enter_context(patch.object(tool.backup, "agreement_files", return_value={}))
                stack.enter_context(patch.object(tool.backup, "media_files", return_value={}))
                stack.enter_context(patch.object(tool.backup, "archive_files", return_value={}))
                stack.enter_context(patch.object(tool.backup, "run", side_effect=run))
                stack.enter_context(patch.object(tool.backup, "verify_snapshot"))
                rotation = stack.enter_context(patch.object(tool.backup, "rotate"))
                outcome = tool.run_backup(cfg)
                self.assertEqual(outcome, 0, tool.read_private(root / "last-run.json"))
                rotation.assert_called_once()
            state = tool.read_private(root / "last-run.json")
            self.assertEqual(state["status"], "success")
            self.assertEqual(state["snapshot"], "f" * 64)
            self.assertEqual(events, ["resume_api", "resume_cms", "snapshot"])
            self.assertFalse((root / "pending.json").exists())

    def test_watchdog_checks_receipt_and_actual_snapshot(self):
        from unittest.mock import patch
        tool = self.module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "receipts").mkdir(mode=0o700)
            state = {"version": 1, "run_id": "a" * 32, "status": "success", "verified": True,
                     "rotation": "success", "snapshot": "f" * 64, "finished_at": tool.now_iso()}
            tool.atomic_json(root / "last-run.json", state)
            cfg = {"state_dir": str(root)}
            timer = {"LoadState": "loaded", "ActiveState": "active", "UnitFileState": "enabled"}
            with patch.object(tool, "timer_properties", return_value=timer), \
                 patch.object(tool, "notify", return_value=False) as alert, \
                 patch.object(tool.backup, "managed_snapshot_ids", side_effect=tool.BackupError("missing")):
                self.assertEqual(tool.watchdog(cfg), 1)
                self.assertTrue(alert.called)
                receipt = root / "receipts" / (state["run_id"] + ".json")
                tool.atomic_json(receipt, {"version": 1, "verified": True, "snapshot": "e" * 64})
                self.assertEqual(tool.watchdog(cfg), 1)
                tool.atomic_json(receipt, {"version": 1, "verified": True, "snapshot": "f" * 64})
                self.assertEqual(tool.watchdog(cfg), 1)

    def test_startup_directory_failure_uses_mail_without_staging(self):
        from unittest.mock import patch
        tool = self.module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = {"state_dir": str(root), "private_dir": str(root)}
            with patch.object(sys, "argv", ["production.py", "show"]), \
                 patch.object(tool.os, "geteuid", return_value=0), \
                 patch.object(tool, "load_config", return_value=cfg), \
                 patch.dict(os.environ, dict(os.environ), clear=True), \
                 patch.object(tool, "notify", return_value=True) as alert:
                self.assertEqual(tool.main(), 1)
                alert.assert_called_once()
                self.assertEqual(alert.call_args.args[0]["private_dir"], str(root))
                self.assertEqual(alert.call_args.args[1]["event"], "control_failed")

    def test_initial_state_write_failure_uses_independent_mail(self):
        from unittest.mock import patch
        tool = self.module()
        cfg = {"state_dir": "/unused", "private_dir": "/private", "activation_approved": True}
        with patch.object(sys, "argv", ["production.py", "run"]), \
             patch.object(tool.os, "geteuid", return_value=0), \
             patch.object(tool, "load_config", return_value=cfg), \
             patch.object(tool, "configure_environment"), \
             patch.object(tool, "RunLock"), \
             patch.object(tool, "recover_pending"), \
             patch.object(tool, "atomic_json", side_effect=OSError("synthetic write failure")), \
             patch.object(tool, "notify", return_value=True) as alert:
            self.assertEqual(tool.main(), 1)
            alert.assert_called_once()
            self.assertEqual(alert.call_args.args[1]["event"], "control_failed")

    def test_failure_history_has_closed_reason_without_exception_contents(self):
        from unittest.mock import patch
        tool=self.module()
        for message,reason in (("Insufficient free disk space before capture","disk_space_low"),
                               ("SELECT customer document and synthetic-secret","backup_failure")):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as directory:
                root=Path(directory);(root/"runs").mkdir(mode=0o700)
                cfg={"state_dir":str(root),"activation_approved":True}
                with patch.object(tool,"configure_environment"), \
                     patch.object(tool,"preflight",side_effect=tool.BackupError(message)), \
                     patch.object(tool,"notify",return_value=False) as alert:
                    self.assertEqual(tool.run_backup(cfg),1)
                state=tool.read_private(root/"last-run.json")
                self.assertEqual(state.get("reason"),reason)
                self.assertNotIn("synthetic-secret",json.dumps(state))
                self.assertNotIn("SELECT customer",json.dumps(state))
                self.assertNotIn("synthetic-secret",json.dumps(alert.call_args.args[1]))
