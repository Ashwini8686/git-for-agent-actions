"""HTTP API for ANY agent + the monitoring dashboard (standard library only).

Agent endpoints (agent token):  GET /api/v1/tools?format=openai|anthropic|mcp   POST /api/v1/call
Human endpoints (admin token):  dashboard, approve, reject, revert, capsules, audit ...
An agent token can never approve, reject or revert anything.
"""
import base64
import hmac
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .adapters import AdapterError, Registry
from .dashboard import DASH
from .db import connect, home
from .engine import Engine, agent_message
from .seed import WORKFLOW, seed

AGENT_ROUTES = {("POST", "/api/v1/call"), ("GET", "/api/v1/tools"), ("GET", "/api/v1/pending")}


def fmt_tools(specs, fmt):
    if fmt == "openai":
        return [{"type": "function", "function": {"name": s["name"], "description": s["description"], "parameters": s["inputSchema"]}} for s in specs]
    if fmt == "anthropic":
        return [{"name": s["name"], "description": s["description"], "input_schema": s["inputSchema"]} for s in specs]
    return [{"name": s["name"], "description": s["description"], "inputSchema": s["inputSchema"], "effect": s["effect"], "risk": s["risk"]} for s in specs]


class Handler(BaseHTTPRequestHandler):
    server_version = "AgentGit/2.0"

    # ----- auth -----
    def _role(self):
        s = self.server
        if not s.admin_token and not s.agent_token:
            return "admin"  # local development mode
        h, tok = self.headers.get("Authorization", ""), ""
        try:
            if h.startswith("Bearer "):
                tok = h[7:]
            elif h.startswith("Basic "):
                tok = base64.b64decode(h[6:]).decode().split(":", 1)[1]
        except Exception:
            return None
        if s.admin_token and hmac.compare_digest(tok, s.admin_token):
            return "admin"
        if s.agent_token and hmac.compare_digest(tok, s.agent_token):
            return "agent"
        return None

    def _send(self, body, code=200, ctype="application/json"):
        data = body if isinstance(body, bytes) else (json.dumps(body) if ctype == "application/json" else body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")

    def _route(self, method):
        u = urlparse(self.path)
        role = self._role()
        if role is None:
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="AgentGit"')
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if role == "agent" and (method, u.path) not in AGENT_ROUTES:
            return self._send({"ok": False, "error": "agent credentials cannot use this endpoint"}, 403)
        eng = None
        try:
            body = self._body() if method == "POST" else {}
            eng = Engine(self.server.reg, connect(), "human" if role == "admin" else body.get("agent") or "http-agent")
            self._dispatch(eng, method, u.path, parse_qs(u.query), body, role)
        except (AdapterError, ValueError, KeyError) as e:
            self._send({"ok": False, "error": str(e)}, 400)
        except Exception as e:
            self._send({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)
        finally:
            if eng:
                eng.close()

    def _dispatch(self, eng, method, path, q, body, role):
        reg, g = self.server.reg, (method == "GET")
        if g and path == "/":
            return self._send(DASH, 200, "text/html")
        if g and path == "/api/v1/stats":
            return self._send(eng.stats())
        if g and path == "/api/v1/pending":
            b = eng._batch(status="staging")
            return self._send({"batch": dict(b) if b else None, "diff": eng.diff(), "actions": next((x["actions"] for x in eng.batches(1) if b and x["id"] == b["id"]), [])})
        if g and path == "/api/v1/batches":
            return self._send(eng.batches(int(q.get("limit", ["30"])[0])))
        if g and path == "/api/v1/log":
            return self._send({"log": eng.log_tail(int(q.get("limit", ["40"])[0])), "chain": eng.verify_log()})
        if g and path == "/api/v1/tools":
            return self._send(fmt_tools(reg.tool_specs(), q.get("format", ["mcp"])[0]))
        if g and path == "/api/v1/capsules":
            return self._send(eng.capsules())
        if g and path == "/api/v1/data":
            return self._send(reg.builtin_view() or {})
        if method == "POST" and path == "/api/v1/call":
            r = eng.stage(body["tool"], body.get("args") or {})
            return self._send({"ok": True, "message": agent_message(r), **r})
        if method == "POST" and path == "/api/v1/approve":
            return self._send(eng.commit(body.get("batch"), bool(body.get("confirm_irreversible")), body.get("fail_at")))
        if method == "POST" and path == "/api/v1/reject":
            return self._send(eng.reject(body.get("batch")))
        if method == "POST" and path == "/api/v1/revert":
            return self._send(eng.revert(int(body["batch"])))
        if method == "POST" and path == "/api/v1/capsules":
            return self._send(eng.save_capsule(int(body["batch"]), body["name"]))
        if method == "POST" and path == "/api/v1/capsules/run":
            return self._send(eng.run_capsule(body["name"]))
        if method == "POST" and path == "/api/v1/demo":
            if eng._batch(status="staging"):
                return self._send({"ok": False, "error": "a batch is already staged; approve or reject it first"})
            for t, a in WORKFLOW:
                eng.stage(t, a, "demo-agent")
            return self._send({"ok": True, "staged": len(WORKFLOW)})
        if method == "POST" and path == "/api/v1/seed":
            eng.close()
            seed()
            return self._send({"ok": True})
        self._send({"ok": False, "error": "not found"}, 404)

    def log_message(self, *a):
        pass


def make_server(host="127.0.0.1", port=8765, admin_token=None, agent_token=None):
    if host not in ("127.0.0.1", "localhost") and not admin_token:
        raise SystemExit("Refusing to listen on the network without --admin-token.")
    srv = ThreadingHTTPServer((host, port), Handler)
    srv.admin_token, srv.agent_token = admin_token, agent_token
    srv.reg = Registry(home())
    if not (home() / "calendar.json").exists() and srv.reg.cfg.get("builtin", True):
        seed()
    Engine(srv.reg, connect(), "human").recover()
    return srv


def serve(host="127.0.0.1", port=8765, admin_token=None, agent_token=None):
    srv = make_server(host, port, admin_token, agent_token)
    print(f"Dashboard: http://{'127.0.0.1' if host == '0.0.0.0' else host}:{port}   (Ctrl+C to stop)")
    try:
        srv.serve_forever()
    finally:
        srv.reg.close()
