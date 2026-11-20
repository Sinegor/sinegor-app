import unittest

import test_production as fixture


class ProxySsrTests(unittest.TestCase):
    def test_anonymous_admin_ssr_uses_session_fallback_before_client_form(self):
        m = fixture.MonitorTests().module()
        page = (
            "<html><title>Вход администратора — SINEGOR LAB</title>"
            '<div role="status">Проверка сессии…</div></html>'
        ).encode()
        self.assertIsNone(m.http_result("proxy", 200, page))
        self.assertIsNotNone(m.http_result("proxy", 200, b"<html>SINEGOR</html>"))
        self.assertIsNotNone(m.http_result("proxy", 503, page))
