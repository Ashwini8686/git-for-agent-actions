"""Minimal MCP-over-stdio client (JSON-RPC 2.0, newline-delimited). Standard library only.

Used to talk to ANY upstream MCP server. No SDK needed.
"""
import itertools
import json
import os
import subprocess
import sys
import threading


class MCPError(Exception):
    pass


class StdioMCPClient:
    def __init__(self, command, env=None, cwd=None, timeout=30):
        cmd = list(command)
        if cmd[0] in ("python", "python3"):
            cmd[0] = sys.executable
        e = dict(os.environ)
        e.update(env or {})
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  text=True, encoding="utf-8", bufsize=1, env=e, cwd=cwd)
        self.timeout = timeout
        self._ids = itertools.count(1)
        self._pending = {}
        self._lock = threading.Lock()
        self._wlock = threading.Lock()
        threading.Thread(target=self._reader, daemon=True).start()
        self.request("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                    "clientInfo": {"name": "agentgit", "version": "2.0"}})
        self.notify("notifications/initialized")

    def _reader(self):
        for line in self.p.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                m = json.loads(line)
            except ValueError:
                continue
            if "id" in m and ("result" in m or "error" in m):
                with self._lock:
                    slot = self._pending.get(m["id"])
                if slot:
                    slot[1] = m
                    slot[0].set()
        with self._lock:  # upstream closed: wake every waiter
            for ev, _ in self._pending.values():
                ev.set()

    def _send(self, msg):
        with self._wlock:
            self.p.stdin.write(json.dumps(msg) + "\n")
            self.p.stdin.flush()

    def request(self, method, params=None):
        i = next(self._ids)
        slot = [threading.Event(), None]
        with self._lock:
            self._pending[i] = slot
        self._send({"jsonrpc": "2.0", "id": i, "method": method, "params": params or {}})
        if not slot[0].wait(self.timeout):
            raise MCPError(f"timeout waiting for {method}")
        with self._lock:
            self._pending.pop(i, None)
        m = slot[1]
        if m is None:
            raise MCPError("upstream server closed the connection")
        if "error" in m:
            raise MCPError(m["error"].get("message", "upstream error"))
        return m["result"]

    def notify(self, method, params=None):
        msg = {"jsonrpc": "2.0", "method": method}
        if params:
            msg["params"] = params
        self._send(msg)

    def list_tools(self):
        tools, cursor = [], None
        while True:
            r = self.request("tools/list", {"cursor": cursor} if cursor else {})
            tools += r.get("tools", [])
            cursor = r.get("nextCursor")
            if not cursor:
                return tools

    def call_tool(self, name, args):
        r = self.request("tools/call", {"name": name, "arguments": args or {}})
        text = "\n".join(c.get("text", "") for c in r.get("content", []) if c.get("type") == "text")
        return text, bool(r.get("isError"))

    def close(self):
        try:
            self.p.stdin.close()
            self.p.terminate()
            self.p.wait(timeout=5)
        except Exception:
            pass
