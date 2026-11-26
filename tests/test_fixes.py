"""Regression tests for bugs found while running the dashboard."""
import contextlib
import io
import json
import threading
import unittest
import urllib.request

from agentgit.adapters import UpstreamAdapter
from agentgit.doctor import run as doctor
from test_v2 import Base


class TestVerifyMatching(unittest.TestCase):
    def test_id_inside_another_id_is_not_a_match(self):
        ad = UpstreamAdapter({"name": "x", "tools": {"delete": {"verify": {"tool": "list", "absent": "{args.id}"}}}})
        ad._call = lambda tool, args: "up_ae1f3b 2026-12-10 Maths exam"
        self.assertTrue(ad.verify("x_delete", {"id": "e1"}, {}))
        ad._call = lambda tool, args: '{"id": "e1"}'
        self.assertFalse(ad.verify("x_delete", {"id": "e1"}, {}))


class TestResetAndDoctor(Base):
    def setUp(self):
        super().setUp()
        from agentgit.server import make_server
        self.srv = make_server("127.0.0.1", 0)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown(); self.srv.server_close(); self.srv.reg.close(); super().tearDown()

    def call(self, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", data=data, timeout=30) as r:
            return json.loads(r.read())

    def test_reset_while_the_dashboard_is_polling(self):
        errors, stop = [], threading.Event()

        def poll():
            while not stop.is_set():
                for p in ("/api/v1/stats", "/api/v1/pending", "/api/v1/log", "/api/v1/data"):
                    try:
                        self.call(p)
                    except Exception as e:
                        errors.append(repr(e))

        threads = [threading.Thread(target=poll) for _ in range(3)]
        for t in threads:
            t.start()
        try:
            for _ in range(15):
                self.call("/api/v1/seed", {}); self.call("/api/v1/demo", {}); self.call("/api/v1/reject", {})
        finally:
            stop.set()
            for t in threads:
                t.join()
        self.assertEqual(errors, [])

    def test_doctor_recognises_a_running_server(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(doctor(self.port), 0)
        self.assertIn("the server is running", out.getvalue())


if __name__ == "__main__":
    unittest.main()
