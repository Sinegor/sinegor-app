import copy
import importlib.util
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class TransportTests(unittest.TestCase):
    def module(self):
        spec = importlib.util.spec_from_file_location(
            "monitor_transport", Path(__file__).resolve().parents[1] / "production.py"
        )
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def test_actual_http_failure_invalid_body_and_redirect_are_detected(self):
        m = self.module()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                status = (
                    503
                    if self.path == "/down"
                    else 302
                    if self.path == "/redirect"
                    else 200
                )
                self.send_response(status)
                if status == 302:
                    self.send_header("Location", "/ready")
                self.end_headers()
                self.wfile.write(
                    b'{"status":"ok","database":"ok"}'
                    if self.path == "/ready"
                    else b"OK"
                )

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            origin = "http://127.0.0.1:" + str(server.server_port)
            self.assertIsNone(m.probe_http("api_ready", origin + "/ready")["reason"])
            for route in ("/down", "/invalid", "/redirect"):
                self.assertIsNotNone(
                    m.probe_http("api_ready", origin + route)["reason"]
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_maintenance_preserves_incident_instead_of_faking_recovery(self):
        m = self.module()
        self.assertTrue(
            callable(getattr(m, "normalize_results", None)),
            "maintenance normalization missing",
        )
        observations = {
            "docker.api": None,
            "http.site": None,
            "docker.postgres": "stopped",
            "tls.site": "tls_invalid",
        }
        safe = m.normalize_results(observations, True)
        self.assertNotIn("docker.api", safe)
        self.assertNotIn("http.site", safe)
        self.assertEqual(safe["docker.postgres"], "stopped")
        self.assertEqual(safe["tls.site"], "tls_invalid")
        self.assertIn("monitor.collect", safe)
        state = {}
        persist = lambda value: None
        for now in (10000, 10060, 10120):
            state = m.transition(
                state, {"http.site": "http_error"}, now, lambda event: True, persist
            )
        frozen = copy.deepcopy(state["checks"]["http.site"])
        for now in (10180, 10240):
            state = m.transition(state, safe, now, lambda event: True, persist)
        self.assertEqual(state["checks"]["http.site"], frozen)
        normal = m.normalize_results({"http.site": None}, False)
        for now in (10300, 10360):
            state = m.transition(state, normal, now, lambda event: True, persist)
        self.assertFalse(state["checks"]["http.site"]["active"])
