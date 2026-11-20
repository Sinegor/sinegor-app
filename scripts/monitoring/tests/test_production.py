"""Synthetic regression scenarios for host monitoring; no production mutation."""

import copy
import importlib.util
import unittest
from datetime import UTC, datetime
from pathlib import Path

NOW = datetime(2026, 11, 17, 20, tzinfo=UTC).timestamp()


class MonitorTests(unittest.TestCase):
    def module(self):
        path = Path(__file__).resolve().parents[1] / "production.py"
        self.assertTrue(path.is_file(), "production monitor missing")
        spec = importlib.util.spec_from_file_location("monitor", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_http_status_does_not_replace_schema_and_ssr_validation(self):
        m = self.module()
        self.assertIsNone(
            m.http_result("api_ready", 200, b'{"status":"ok","database":"ok"}')
        )
        self.assertIsNotNone(m.http_result("api_ready", 200, b'{"status":"ok"}'))
        self.assertIsNotNone(m.http_result("site", 200, b"OK", title="Published"))
        page = b'<html>SINEGOR<div class="public-hero"><h1>Published</h1></div></html>'
        self.assertIsNone(m.http_result("site", 200, page, title="Published"))
        self.assertIsNotNone(m.http_result("site", 200, page, title="Other"))
        self.assertIsNotNone(m.http_result("site", 503, page, title="Published"))

    def test_cms_204_and_database_readiness_are_distinct(self):
        m = self.module()
        self.assertIsNone(m.http_result("cms_live", 204, b""))
        self.assertIsNotNone(m.http_result("cms_live", 200, b""))
        self.assertIsNone(
            m.http_result(
                "cms_content", 200, b'{"data":{"slug":"home","title":"Published"}}'
            )
        )
        self.assertIsNotNone(m.http_result("cms_content", 200, b'{"data":null}'))
        self.assertIsNotNone(m.http_result("cms_content", 200, b"invalid"))

    def test_backup_window_requires_active_backup_and_expires(self):
        m = self.module()
        pending = {
            "version": 1,
            "created_at": datetime.fromtimestamp(NOW - 20, UTC).isoformat(),
            "entries": [
                {"service": s, "id": c * 64, "image": "sha256:" + c * 64}
                for s, c in (("api", "a"), ("cms", "b"))
            ],
        }
        run = {
            "status": "running",
            "started_at": datetime.fromtimestamp(NOW - 30, UTC).isoformat(),
        }
        self.assertTrue(m.maintenance_allowed(pending, run, True, NOW))
        self.assertFalse(m.maintenance_allowed(pending, run, False, NOW))
        self.assertFalse(m.maintenance_allowed(pending, run, True, NOW + 500))
        self.assertFalse(
            m.maintenance_allowed(pending, run | {"status": "success"}, True, NOW)
        )
        bad = copy.deepcopy(pending)
        bad["entries"].pop()
        self.assertFalse(m.maintenance_allowed(bad, run, True, NOW))

    def items(self):
        return [
            {
                "Id": c * 64,
                "RestartCount": 0,
                "Config": {"Labels": {"com.docker.compose.service": s}},
                "State": {
                    "Status": "running",
                    "StartedAt": "old",
                    "Health": {"Status": "healthy"},
                },
            }
            for s, c in zip(("api", "cms", "postgres", "web", "proxy"), "abcde")
        ]

    def test_container_failures_and_restart_loop(self):
        m = self.module()
        items = self.items()
        checks, history = m.container_results(items, {}, NOW, False)
        self.assertTrue(all(v is None for v in checks.values()))
        stopped = copy.deepcopy(items)
        stopped[0]["State"]["Status"] = "exited"
        self.assertEqual(
            m.container_results(stopped, history, NOW + 60, False)[0]["docker.api"],
            "stopped",
        )
        bad = copy.deepcopy(items)
        bad[1]["State"]["Health"]["Status"] = "unhealthy"
        self.assertEqual(
            m.container_results(bad, history, NOW + 60, False)[0]["docker.cms"],
            "unhealthy",
        )
        self.assertIsNotNone(
            m.container_results(items[1:], history, NOW + 60, False)[0]["docker.api"]
        )
        self.assertIsNotNone(
            m.container_results(items + [items[0]], history, NOW + 60, False)[0][
                "docker.api"
            ]
        )
        restarted = copy.deepcopy(items)
        restarted[0]["RestartCount"] = 3
        self.assertEqual(
            m.container_results(restarted, history, NOW + 60, False)[0]["docker.api"],
            "restart_loop",
        )

    def test_backup_window_does_not_suppress_postgres_or_proxy(self):
        m = self.module()
        items = self.items()
        for item in items:
            item["State"]["Status"] = "exited"
        checks, _ = m.container_results(items, {}, NOW, True)
        self.assertIsNone(checks["docker.api"])
        self.assertIsNone(checks["docker.cms"])
        self.assertIsNotNone(checks["docker.postgres"])
        self.assertIsNotNone(checks["docker.proxy"])

    def test_disk_guard_includes_backup_and_inode_budget(self):
        m = self.module()
        g = 1024**3
        reason, metrics = m.disk_result(
            40 * g, 100000, 90000, 20 * 1024**2, 120 * 1024**2
        )
        self.assertIsNone(reason)
        self.assertGreaterEqual(metrics["required_free"], 6 * g)
        self.assertEqual(
            m.disk_result(
                metrics["required_free"] - 1, 100000, 90000, 20 * 1024**2, 120 * 1024**2
            )[0],
            "backup_space",
        )
        self.assertEqual(m.disk_result(40 * g, 100000, 500, 0, 0)[0], "inode_critical")

    def test_tls_warning_critical_and_validation_failure(self):
        m = self.module()
        self.assertIsNone(m.tls_result(31, True))
        self.assertEqual(m.tls_result(29, True), "tls_expiring")
        self.assertEqual(m.tls_result(6, True), "tls_critical")
        self.assertEqual(m.tls_result(88, False), "tls_invalid")

    def tick(self, m, state, result, now, sent=True):
        messages = []
        writes = []

        def notify(event):
            self.assertTrue(writes, "persist before SMTP")
            messages.append(event)
            return sent

        state = m.transition(
            state,
            result,
            now,
            notify,
            lambda value: writes.append(copy.deepcopy(value)),
        )
        return state, messages

    def test_confirmation_repeat_and_recovery(self):
        m = self.module()
        state = {}
        for offset in (0, 60):
            state, msg = self.tick(m, state, {"http.site": "http_error"}, NOW + offset)
            self.assertEqual(msg, [])
        state, msg = self.tick(m, state, {"http.site": "http_error"}, NOW + 120)
        self.assertEqual(msg, ["monitor.http.site.down"])
        state, msg = self.tick(m, state, {"http.site": "http_error"}, NOW + 180)
        self.assertEqual(msg, [])
        state, msg = self.tick(m, state, {"http.site": "http_error"}, NOW + 21720)
        self.assertEqual(msg, ["monitor.http.site.down"])
        state, msg = self.tick(m, state, {"http.site": None}, NOW + 21800)
        self.assertEqual(msg, [])
        state, msg = self.tick(m, state, {"http.site": None}, NOW + 21860)
        self.assertEqual(msg, ["monitor.http.site.recovered"])
        state, msg = self.tick(m, state, {"http.site": None}, NOW + 21920)
        self.assertEqual(msg, [])

    def test_smtp_failure_is_durable_and_retry_is_throttled(self):
        m = self.module()
        state = {}
        for offset in (0, 60, 120):
            state, msg = self.tick(
                m, state, {"http.site": "http_error"}, NOW + offset, False
            )
        self.assertEqual(msg, ["monitor.http.site.down"])
        self.assertEqual(state["checks"]["http.site"]["pending"], "down")
        self.assertFalse(state["checks"]["http.site"]["notified"])
        state, msg = self.tick(m, state, {"http.site": "http_error"}, NOW + 180, False)
        self.assertEqual(msg, [])
        state, msg = self.tick(m, state, {"http.site": "http_error"}, NOW + 420)
        self.assertEqual(msg, ["monitor.http.site.down"])
        self.assertTrue(state["checks"]["http.site"]["notified"])

    def test_no_recovery_without_accepted_alarm(self):
        m = self.module()
        state = {}
        for offset in (0, 60, 120):
            state, _ = self.tick(
                m, state, {"http.site": "http_error"}, NOW + offset, False
            )
        state, _ = self.tick(m, state, {"http.site": None}, NOW + 180, False)
        state, msg = self.tick(m, state, {"http.site": None}, NOW + 240)
        self.assertEqual(msg, [])
        self.assertFalse(state["checks"]["http.site"]["active"])

    def test_critical_capacity_and_overdue_recovery_alert_immediately(self):
        m = self.module()
        for key, reason in (
            ("disk.root", "backup_space"),
            ("backup.window", "recovery_overdue"),
        ):
            _, msg = self.tick(m, {}, {key: reason}, NOW)
            self.assertEqual(msg, ["monitor." + key + ".down"])


if __name__ == "__main__":
    unittest.main()
