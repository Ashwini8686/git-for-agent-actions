"""Zero-dependency approval page (standard library only): http://127.0.0.1:8765"""
import html
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs

from .engine import make_engine

CSS = ("body{font-family:Calibri,Arial,sans-serif;max-width:860px;margin:30px auto;padding:0 16px;background:#fff6e5;color:#1b2a49}"
       "pre{background:#fff;border:1px solid #ccc;padding:14px;border-radius:8px;font-size:15px}"
       "button{padding:10px 18px;border:0;border-radius:8px;color:#fff;font-size:15px;margin-right:8px;cursor:pointer}"
       ".ok{background:#2e8b57}.no{background:#c0392b}.rv{background:#2f5da8}table{border-collapse:collapse;width:100%}"
       "td,th{border-bottom:1px solid #ddd;padding:6px;text-align:left}")


def page():
    eng = make_engine()
    try:
        diff = eng.diff()
        staged = eng.c.execute("SELECT 1 FROM batches WHERE status='staging'").fetchone()
        rows = "".join(
            f"<tr><td>#{r['id']}</td><td>{html.escape(r['status'])}</td><td>{r['n']}</td>"
            f"<td>{time.strftime('%d %b %H:%M', time.localtime(r['created']))}</td><td>"
            + (f"<form method=post action=/revert style='margin:0'><input type=hidden name=b value={r['id']}>"
               "<button class=rv>Revert</button></form>" if r["status"] == "committed" else "") + "</td></tr>"
            for r in eng.history())
    finally:
        eng.close()
    buttons = ("<form method=post action=/approve><label><input type=checkbox name=irr value=1> "
               "I confirm irreversible actions (e.g. sent email)</label><br><br>"
               "<button class=ok>Approve and commit</button></form>"
               "<form method=post action=/reject><br><button class=no>Reject batch</button></form>") if staged else ""
    return (f"<html><head><meta charset=utf-8><title>Git for Agent Actions</title><style>{CSS}</style></head><body>"
            f"<h1>Git for Agent Actions</h1><h3>Pending changes</h3><pre>{html.escape(diff)}</pre>{buttons}"
            f"<h3>History</h3><table><tr><th>Batch</th><th>Status</th><th>Actions</th><th>When</th><th></th></tr>{rows}</table>"
            "</body></html>")


class Handler(BaseHTTPRequestHandler):
    def _send(self, body, code=200):
        self.send_response(code); self.send_header("Content-Type", "text/html; charset=utf-8"); self.end_headers()
        self.wfile.write(body.encode())

    def do_GET(self):
        self._send(page())

    def do_POST(self):
        data = parse_qs(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode())
        eng = make_engine()
        try:
            if self.path == "/approve":
                eng.commit(confirm_irreversible=bool(data.get("irr")))
            elif self.path == "/reject":
                eng.reject()
            elif self.path == "/revert":
                eng.revert(int(data["b"][0]))
        finally:
            eng.close()
        self.send_response(303); self.send_header("Location", "/"); self.end_headers()

    def log_message(self, *a):
        pass


def serve(port=8765):
    print(f"Approval page: http://127.0.0.1:{port}  (Ctrl+C to stop)")
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
