import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


class ClosedArchiveTests(unittest.TestCase):
    def module(self):
        root = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(root))
        spec = importlib.util.spec_from_file_location(
            "logging_cutover", root / "cutover.py"
        )
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def test_closed_copy_preserves_bytes_and_is_immutable(self):
        m = self.module()
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            source = folder / "source.log"
            data = (
                json.dumps(
                    {
                        "time": "2026-11-18T00:00:00Z",
                        "stream": "stdout",
                        "log": "synthetic\n",
                    }
                )
                + "\n"
            )
            source.write_text(data)
            item = {
                "Id": "a" * 64,
                "State": {"Running": False},
                "LogPath": str(source),
                "Config": {"Labels": {"com.docker.compose.service": "api"}},
            }
            result = m.archive_closed(
                item, folder / "closed", folder / "locks", lambda identifier: item
            )
            final = folder / "closed" / ("api-" + "a" * 64 + "-0.jsonl")
            self.assertEqual(final.read_text(), data)
            self.assertEqual(result[0]["bytes"], len(data.encode()))
            source.write_text(data.replace("synthetic", "different"))
            with self.assertRaises(ValueError):
                m.archive_closed(
                    item, folder / "closed", folder / "locks", lambda identifier: item
                )
            self.assertEqual(final.read_text(), data)

    def test_running_or_resumed_producer_cannot_publish(self):
        m = self.module()
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            source = folder / "source.log"
            source.write_text(
                '{"time":"2026-11-18T00:00:00Z","stream":"stdout","log":"synthetic"}\n'
            )
            item = {
                "Id": "a" * 64,
                "State": {"Running": True},
                "LogPath": str(source),
                "Config": {"Labels": {"com.docker.compose.service": "api"}},
            }
            with self.assertRaises(ValueError):
                m.archive_closed(
                    item, folder / "closed", folder / "locks", lambda identifier: item
                )
            item["State"]["Running"] = False
            with self.assertRaises(ValueError):
                m.archive_closed(
                    item,
                    folder / "closed",
                    folder / "locks",
                    lambda identifier: {"State": {"Running": True}},
                )
            self.assertFalse(list((folder / "closed").glob("*.jsonl")))
