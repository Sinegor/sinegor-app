import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import test_watchdog_monitoring as fixture


class BackupReviewRegressions(unittest.TestCase):
    def module(self):
        return fixture.WatchdogMonitoringTests().module()

    def test_enabled_missing_monitor_is_unavailable(self):
        m = self.module()
        with patch("pathlib.Path.exists", return_value=False):
            self.assertEqual(
                m.monitor_liveness({"monitoring_enabled": True}), "monitor_unavailable"
            )

    def test_backup_watchdog_does_not_alert_inside_valid_locked_capture(self):
        m = self.module()
        now = datetime(2026, 11, 17, 20, tzinfo=UTC).timestamp()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "runs").mkdir(mode=0o700)
            (root / "receipts").mkdir(mode=0o700)
            cfg = {
                "state_dir": directory,
                "images": {"api": "sha256:" + "a" * 64, "cms": "sha256:" + "b" * 64},
            }
            accepted = {
                "status": "success",
                "run_id": "c" * 32,
                "snapshot": "d" * 64,
                "verified": True,
                "rotation": "success",
                "finished_at": datetime.fromtimestamp(now - 3600, UTC).isoformat(),
            }
            m.atomic_json(root / "runs" / ("c" * 32 + ".json"), accepted)
            m.atomic_json(
                root / "receipts" / ("c" * 32 + ".json"),
                {"version": 1, "verified": True, "snapshot": "d" * 64},
            )
            m.atomic_json(
                root / "last-run.json",
                {
                    "status": "running",
                    "run_id": "e" * 32,
                    "started_at": datetime.fromtimestamp(now - 60, UTC).isoformat(),
                },
            )
            pending = {
                "version": 1,
                "created_at": datetime.fromtimestamp(now - 30, UTC).isoformat(),
                "entries": [
                    {"service": s, "id": c * 64, "image": "sha256:" + c * 64}
                    for s, c in (("api", "a"), ("cms", "b"))
                ],
            }
            m.atomic_json(root / "pending.json", pending)
            m.timer_properties = lambda: {
                "LoadState": "loaded",
                "ActiveState": "active",
                "UnitFileState": "enabled",
            }
            m.command = lambda *args, **kwargs: "ActiveState=activating\n"

            class Docker:
                def __init__(self, cfg):
                    pass

                def service(self, s):
                    c = "a" if s == "api" else "b"
                    return {"id": c * 64, "image": "sha256:" + c * 64}

            m.Docker = Docker
            messages = []
            m.notify = lambda cfg, event: messages.append(event) or True
            with patch.object(m.time, "time", return_value=now), m.RunLock(cfg):
                self.assertEqual(m.watchdog(cfg), 0)
            self.assertEqual(messages, [])
