import importlib.util
import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path


class RetentionTests(unittest.TestCase):
    def module(self):
        p = Path(__file__).resolve().parents[1] / "retention.py"
        self.assertTrue(p.exists(), "calendar retention mechanism missing")
        s = importlib.util.spec_from_file_location("log_retention", p)
        m = importlib.util.module_from_spec(s)
        s.loader.exec_module(m)
        return m

    def line(self, at):
        return (
            json.dumps(
                {"time": at.isoformat(), "stream": "stdout", "log": "synthetic\n"}
            )
            + "\n"
        )

    def test_exact_ninety_day_boundary_and_recent_records(self):
        m = self.module()
        now = datetime(2026, 11, 18, tzinfo=UTC)
        lines = [
            self.line(now - timedelta(days=90, microseconds=1)),
            self.line(now - timedelta(days=90)),
            self.line(now - timedelta(days=90) + timedelta(microseconds=1)),
        ]
        kept, removed = m.filter_lines(lines, now)
        self.assertEqual(removed, 2)
        self.assertEqual(kept, lines[2:])

    def test_utc_offsets_and_future_records_preserved(self):
        m = self.module()
        now = datetime(2026, 11, 18, tzinfo=UTC)
        old = (
            json.dumps(
                {
                    "time": "2026-08-20T03:00:00+03:00",
                    "stream": "stderr",
                    "log": "synthetic",
                }
            )
            + "\n"
        )
        new = self.line(now + timedelta(days=1))
        self.assertEqual(m.filter_lines([old, new], now), ([new], 1))

    def test_unparseable_record_cannot_be_silently_destroyed(self):
        m = self.module()
        now = datetime(2026, 11, 18, tzinfo=UTC)
        for line in ("invalid\n", '{"time":"bad"}\n', '{"log":"synthetic"}\n'):
            with self.assertRaises((ValueError, KeyError, TypeError)):
                m.filter_lines([line], now)

    def test_naive_timestamp_is_rejected(self):
        m = self.module()
        with self.assertRaises(ValueError):
            m.filter_lines(
                [
                    '{"time":"2026-01-01T00:00:00","stream":"stdout","log":"synthetic"}\n'
                ],
                datetime.now(UTC),
            )

    def test_scan_preserves_and_cleanup_rewrites_only_expired_records(self):
        m = self.module()
        now = datetime(2026, 11, 18, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / ("api-" + "a" * 64 + "-0.jsonl")
            old, new = self.line(now - timedelta(days=91)), self.line(now)
            path.write_text(old + new)
            path.chmod(0o600)
            self.assertEqual(m.process(root, now)["expired_records"], 1)
            self.assertEqual(path.read_text(), old + new)
            self.assertEqual(m.process(root, now, True)["expired_records"], 1)
            self.assertEqual(path.read_text(), new)
            m.process(root, now + timedelta(days=91), True)
            self.assertFalse(path.exists())

    def test_bad_second_file_prevents_first_file_deletion(self):
        m = self.module()
        now = datetime(2026, 11, 18, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = root / ("api-" + "a" * 64 + "-0.jsonl")
            second = root / ("cms-" + "b" * 64 + "-0.jsonl")
            old = self.line(now - timedelta(days=91))
            first.write_text(old)
            second.write_text("unknown record\n")
            first.chmod(0o600)
            second.chmod(0o600)
            with self.assertRaises(ValueError):
                m.process(root, now, True)
            self.assertEqual(first.read_text(), old)
            self.assertEqual(second.read_text(), "unknown record\n")

    def test_symlink_and_insecure_file_are_rejected(self):
        m = self.module()
        now = datetime(2026, 11, 18, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / ("api-" + "a" * 64 + "-0.jsonl")
            path.symlink_to("/dev/null")
            with self.assertRaises(OSError):
                m.process(root, now, True)
            path.unlink()
            path.write_text(self.line(now))
            path.chmod(0o644)
            with self.assertRaises(PermissionError):
                m.process(root, now, True)

    def test_dangling_root_symlink_is_not_absent(self):
        m = self.module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "missing-root-link"
            root.symlink_to(Path(folder) / "absent")
            with self.assertRaises(PermissionError):
                m.process(root, datetime.now(UTC), True)

    def test_publisher_and_cleanup_are_mutually_exclusive(self):
        m = self.module()
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder) / "locks"
            with (
                m.archive_lock(state),
                self.assertRaises(BlockingIOError),
                m.archive_lock(state),
            ):
                self.fail("second archive actor acquired lock")
            with m.archive_lock(state):
                self.assertTrue((state / "run.lock").exists())
