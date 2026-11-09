"""Real Restic retention over a private throwaway repository; no production env."""

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


if __name__ == "__main__":
    unittest.main()
