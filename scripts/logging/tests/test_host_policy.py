import importlib.util
import unittest
from pathlib import Path


class HostPolicyTests(unittest.TestCase):
    def test_all_blocks_get_ninety_days_and_quiet_logs_rotate(self):
        path = Path(__file__).resolve().parents[1] / "install_policy.py"
        self.assertTrue(path.exists(), "native host policy renderer missing")
        spec = importlib.util.spec_from_file_location("host_policy", path)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        source = "/var/log/a {\n monthly\n rotate 12\n notifempty\n minsize 1M\n}\n/var/log/b {\n weekly\n rotate 4\n}\n"
        result = m.render(source)
        self.assertEqual(result.count("maxage 90"), 2)
        self.assertEqual(result.count("rotate 90"), 2)
        self.assertNotIn("monthly", result)
        self.assertNotIn("weekly", result)
        self.assertNotIn("notifempty", result)
        self.assertNotIn("minsize", result)
        self.assertEqual(m.render(result), result)
