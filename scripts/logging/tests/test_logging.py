import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


class LogRetentionTests(unittest.TestCase):
    def test_real_service_output_rotation_and_ninety_day_expiry(self):
        tool = ROOT / "scripts/logging/run.py"
        self.assertTrue(tool.exists(), "Service log capture is missing")
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            logs = root / "logs"
            logs.mkdir(mode=0o700)
            for role in ("api", "web", "proxy", "strapi"):
                process = subprocess.run(
                    [
                        sys.executable,
                        str(tool),
                        "--directory",
                        str(logs),
                        role,
                        "--",
                        sys.executable,
                        "-c",
                        'import sys; print("synthetic"); print("diagnostic",file=sys.stderr)',
                    ],
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(process.returncode, 0)
                self.assertEqual(process.stdout, b"")
                self.assertIn(b"synthetic", (logs / f"{role}.log").read_bytes())
                self.assertEqual((logs / f"{role}.log").stat().st_mode & 0o777, 0o600)
                for days in (89, 91):
                    when = datetime.now() - timedelta(days=days)
                    archive = logs / f"{role}.log-{when:%Y%m%d}.gz"
                    archive.write_bytes(b"old synthetic")
                    os.utime(archive, (when.timestamp(), when.timestamp()))
            config = root / "rotate.conf"
            config.write_text(
                (ROOT / "infra/logging/logrotate.conf")
                .read_text()
                .replace("/var/log/sinegor", str(logs))
            )
            binary = shutil.which("logrotate") or "/usr/sbin/logrotate"
            result = subprocess.run(
                [binary, "--force", "--state", str(root / "state"), str(config)],
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            for role in ("api", "web", "proxy", "strapi"):
                self.assertEqual((logs / f"{role}.log").read_bytes(), b"")
                old = datetime.now() - timedelta(days=91)
                young = datetime.now() - timedelta(days=89)
                self.assertFalse((logs / f"{role}.log-{old:%Y%m%d}.gz").exists())
                self.assertTrue((logs / f"{role}.log-{young:%Y%m%d}.gz").exists())

    def test_capture_refuses_symlink_log_without_touching_target(self):
        tool = ROOT / "scripts/logging/run.py"
        self.assertTrue(tool.exists(), "Service log capture is missing")
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            root.chmod(0o700)
            target = root / "outside"
            target.write_bytes(b"keep")
            (root / "api.log").symlink_to(target)
            result = subprocess.run(
                [
                    sys.executable,
                    str(tool),
                    "--directory",
                    str(root),
                    "api",
                    "--",
                    "true",
                ],
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(target.read_bytes(), b"keep")


if __name__ == "__main__":
    unittest.main()
