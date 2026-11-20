import importlib.util
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path


class WatchdogMonitoringTests(unittest.TestCase):
    def module(self):
        root = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(root))
        spec = importlib.util.spec_from_file_location(
            "backup_monitoring", root / "production.py"
        )
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def test_last_accepted_snapshot_survives_new_failed_or_running_run(self):
        m = self.module()
        self.assertTrue(
            callable(getattr(m, "last_accepted", None)),
            "accepted backup history missing",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "runs").mkdir(mode=0o700)
            (root / "receipts").mkdir(mode=0o700)
            accepted = {
                "run_id": "a" * 32,
                "status": "success",
                "verified": True,
                "rotation": "success",
                "snapshot": "b" * 64,
                "finished_at": "2026-11-17T00:00:00+00:00",
            }
            m.atomic_json(root / "runs" / ("a" * 32 + ".json"), accepted)
            m.atomic_json(
                root / "receipts" / ("a" * 32 + ".json"),
                {"version": 1, "verified": True, "snapshot": "b" * 64},
            )
            for status in ("running", "failed"):
                m.atomic_json(
                    root / "last-run.json", {"status": status, "run_id": "c" * 32}
                )
                self.assertEqual(
                    m.last_accepted({"state_dir": str(root)})["snapshot"], "b" * 64
                )
            now = datetime(2026, 11, 18, 3, tzinfo=UTC).timestamp()
            self.assertEqual(m.accepted_freshness(accepted, now), "run_stale")

    def test_failed_smtp_is_recorded_before_retry_and_recovery_is_sent_once(self):
        m = self.module()
        self.assertTrue(
            callable(getattr(m, "alert_transition", None)),
            "durable backup alert missing",
        )
        with tempfile.TemporaryDirectory() as directory:
            cfg = {"state_dir": directory}
            root = Path(directory)
            events = []

            def rejected(event):
                self.assertTrue((root / "alert-state.json").exists())
                events.append(event)
                return False

            bad = {"status": "critical", "reason": "run_failed"}
            good = {"status": "ok", "reason": "completed"}
            m.alert_transition(cfg, bad, "run", 10000, rejected)
            self.assertEqual(len(events), 1)
            self.assertTrue(m.read_private(root / "alert-state.json")["active"])
            m.alert_transition(cfg, bad, "run", 10060, rejected)
            self.assertEqual(len(events), 1)

            def accepted(event):
                events.append(event)
                return True

            m.alert_transition(cfg, bad, "run", 10300, accepted)
            self.assertEqual(len(events), 2)
            m.alert_transition(cfg, good, "run", 10360, accepted)
            self.assertEqual(events[-1]["event"], "backup_recovered")
            m.alert_transition(cfg, good, "run", 10420, accepted)
            self.assertEqual(len(events), 3)


if __name__ == "__main__":
    unittest.main()
