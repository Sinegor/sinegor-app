import unittest

import test_production as fixture

NOW = fixture.NOW


class ReviewRegressions(unittest.TestCase):
    def module(self):
        return fixture.MonitorTests().module()

    def test_watchdog_crashing_each_tick_is_not_healthy(self):
        m = self.module()
        self.assertTrue(
            callable(getattr(m, "watchdog_result", None)),
            "completed watchdog heartbeat missing",
        )
        timer = {
            "LoadState": "loaded",
            "ActiveState": "active",
            "UnitFileState": "enabled",
        }
        service = {
            "LoadState": "loaded",
            "ExecMainStartTimestampMonotonic": str(int(m.time.monotonic() * 1e6)),
            "Result": "exit-code",
            "ExecMainStatus": "1",
            "ActiveState": "inactive",
        }
        self.assertIsNotNone(
            m.watchdog_result(timer, service, {"checked_at": NOW - 300}, NOW, 600)
        )
        self.assertIsNone(
            m.watchdog_result(
                timer, service, {"checked_at": NOW, "status": "critical"}, NOW, 600
            )
        )

    def test_disk_capacity_still_works_when_database_measurement_is_unavailable(self):
        m = self.module()
        self.assertTrue(
            callable(getattr(m, "disk_capacity", None)),
            "independent statvfs check missing",
        )
        self.assertEqual(m.disk_capacity(1024, 100000, 90000), "disk_critical")
        self.assertEqual(m.disk_capacity(40 * 1024**3, 100000, 1), "inode_critical")

    def test_proxy_observation_is_not_suppressed_during_backup(self):
        m = self.module()
        results = m.normalize_results(
            {"http.proxy": "http_error", "http.site": "http_error"}, True
        )
        self.assertEqual(results["http.proxy"], "http_error")
        self.assertNotIn("http.site", results)
        self.assertIsNone(
            m.http_result(
                "proxy",
                200,
                (
                    "<html><title>Вход администратора — SINEGOR LAB</title>"
                    "Проверка сессии…</html>"
                ).encode(),
            )
        )

    def test_confirmed_three_restarts_alert_on_first_observation(self):
        m = self.module()
        items = fixture.MonitorTests().items()
        _, history = m.container_results(items, {}, NOW, False)
        items[0]["RestartCount"] = 3
        result, _ = m.container_results(items, history, NOW + 60, False)
        _state, messages = fixture.MonitorTests().tick(m, {}, result, NOW + 60)
        self.assertIn("monitor.docker.api.down", messages)

    def test_pending_recovery_is_not_sent_during_a_new_failure(self):
        m = self.module()
        helper = fixture.MonitorTests()
        state = {}
        for offset in (0, 60, 120):
            state, _ = helper.tick(m, state, {"http.site": "http_error"}, NOW + offset)
        state, _ = helper.tick(m, state, {"http.site": None}, NOW + 180)
        state, _ = helper.tick(m, state, {"http.site": None}, NOW + 240, False)
        self.assertEqual(state["checks"]["http.site"]["pending"], "recovered")
        state, messages = helper.tick(m, state, {"http.site": "http_error"}, NOW + 540)
        self.assertEqual(messages, [])
