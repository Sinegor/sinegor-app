"""Real Restic retention over a private throwaway repository; no production env."""

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

TOOL = Path(__file__).resolve().parents[1] / "backup.py"


class RealResticRetention(unittest.TestCase):
    def test_real_forget_prune_keeps_expected_daily_weekly_and_foreign_snapshots(self):
        binary = shutil.which("restic")
        if not binary:
            self.skipTest("Restic is required for the real rotation smoke test")
        spec = importlib.util.spec_from_file_location("rotation_tool", TOOL)
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
        with tempfile.TemporaryDirectory(prefix="sinegor-restic-retention-") as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "synthetic.txt").write_text("synthetic backup")
            (source / "api.dump").write_bytes(b"synthetic api dump")
            (source / "cms.dump").write_bytes(b"synthetic cms dump")
            manifest = {
                "version": 1, "databases": ["source_api", "source_cms"],
                "files": {name: hashlib.sha256((source / name).read_bytes()).hexdigest()
                          for name in ("synthetic.txt", "api.dump", "cms.dump")},
            }
            (source / "manifest.json").write_text(json.dumps(manifest))
            password = root / "password"
            password.write_text("synthetic-password")
            password.chmod(0o600)
            env = {
                "PATH": os.environ.get("PATH", ""),
                "RESTIC_REPOSITORY": str(root / "repo"),
                "RESTIC_PASSWORD_FILE": str(password),
                "RESTIC_CACHE_DIR": str(root / "cache"),
                "TZ": "UTC",
                "HOME": str(root),
            }

            def run(*args):
                result = subprocess.run(
                    [binary, *args],
                    env=env,
                    cwd=source,
                    capture_output=True,
                    check=True,
                )
                return result.stdout

            run("init")
            today = datetime(2026, 11, 8, 12, tzinfo=UTC)
            for i in range(40):
                when = today - timedelta(days=39 - i)
                run(
                    "backup",
                    "--host",
                    "sinegor",
                    "--tag",
                    "sinegor-managed-v1",
                    "--time",
                    when.strftime("%Y-%m-%d %H:%M:%S"),
                    ".",
                )
            run("backup", "--host", "foreign", "--tag", "unrelated", ".")
            before = json.loads(run("snapshots", "--json"))
            with patch.dict(os.environ, env, clear=True):
                tool.rotate(SimpleNamespace(execute=False))
            self.assertEqual(len(json.loads(run("snapshots", "--json"))), len(before))
            preview = json.loads(
                run(
                    "forget",
                    "--json",
                    "--dry-run",
                    "--host",
                    "sinegor",
                    "--tag",
                    "sinegor-managed-v1",
                    "--group-by",
                    "host,tags",
                    "--keep-daily",
                    "7",
                    "--keep-weekly",
                    "4",
                )
            )
            expected = {s["id"] for group in preview for s in group["keep"]}
            self.assertLess(len(expected), 40)
            self.assertGreaterEqual(len(expected), 7)
            with patch.dict(os.environ, env, clear=True):
                tool.rotate(SimpleNamespace(execute=True))
            after = json.loads(run("snapshots", "--json"))
            self.assertEqual({s["id"] for s in after if s["hostname"] == "sinegor"}, expected)
            self.assertEqual(sum(s["hostname"] == "foreign" for s in after), 1)
            run("check", "--read-data")
            run("restore", next(iter(expected)), "--target", str(root / "restore"))
            self.assertTrue(
                any(
                    p.read_text() == "synthetic backup"
                    for p in (root / "restore").rglob("synthetic.txt")
                )
            )


    def test_invalid_newer_snapshot_cannot_replace_good_same_day_snapshot(self):
        binary = shutil.which("restic")
        if not binary:
            self.skipTest("Restic is required for the real rotation smoke test")
        spec = importlib.util.spec_from_file_location("rotation_guard_tool", TOOL)
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
        with tempfile.TemporaryDirectory(prefix="sinegor-restic-refusal-") as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            files = {}
            for name in ("api.dump", "cms.dump"):
                (source / name).write_bytes(b"synthetic dump")
                files[name] = hashlib.sha256(b"synthetic dump").hexdigest()
            (source / "manifest.json").write_text(json.dumps(
                {"version": 1, "databases": ["source_api", "source_cms"], "files": files}))
            password = root / "password"
            password.write_text("synthetic-password")
            password.chmod(0o600)
            env = {
                "PATH": os.environ.get("PATH", ""), "HOME": str(root), "TZ": "UTC",
                "RESTIC_REPOSITORY": str(root / "repo"),
                "RESTIC_PASSWORD_FILE": str(password), "RESTIC_CACHE_DIR": str(root / "cache"),
            }
            def run(*args):
                return subprocess.run([binary, *args], env=env, cwd=source,
                                      capture_output=True, check=True).stdout
            run("init")
            for time_of_day in ("12:00:00", "13:00:00"):
                if time_of_day == "13:00:00":
                    (source / "manifest.json").unlink()
                run("backup", "--host", "sinegor", "--tag", "sinegor-managed-v1",
                    "--time", "2026-11-08 " + time_of_day, ".")
            before = {item["id"] for item in json.loads(run("snapshots", "--json"))}
            error = None
            with patch.dict(os.environ, env, clear=True):
                try:
                    tool.rotate(SimpleNamespace(execute=True))
                except tool.BackupError as caught:
                    error = caught
            after = {item["id"] for item in json.loads(run("snapshots", "--json"))}
            self.assertEqual(after, before, "A rejected newer snapshot must not delete the good copy")
            self.assertIsInstance(error, tool.BackupError)


if __name__ == "__main__":
    unittest.main()
