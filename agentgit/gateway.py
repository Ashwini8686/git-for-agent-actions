"""MCP gateway (stdio). Works with ANY MCP client and wraps ANY MCP server listed in agentgit.json.

The agent sees one MCP server. Reads run. Writes are STAGED; only a human approves, on the dashboard.
There is deliberately no 'commit' tool. Never print() to stdout here: stdout carries the protocol.
Run:  python -m agentgit.gateway
"""
import json
import sys

from .adapters import AdapterError, Registry
from .db import connect, home
from .engine import Engine, agent_message

VERSION = "2.0.0"
INSTRUCTIONS = ("Write actions are staged, not executed. Tell the user to review and approve the batch on the AgentGit "
                "dashboard. Use agentgit_preview to show what is pending.")
HELPERS = [
    {"name": "agentgit_preview", "description": "Show the pending (staged) changes as a diff. Read-only.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "agentgit_status", "description": "Summary counts of staged, committed and rolled-back batches. Read-only.",
     "inputSchema": {"type": "object", "properties": {}}},
]


def tool_def(s):
    note = "" if s["effect"] == "read" else " [staged until a human approves]"
    return {"name": s["name"], "description": f"[{s['effect']}, risk {s['risk']}] {s['description']}{note}",
            "inputSchema": s["inputSchema"], "annotations": {"readOnlyHint": s["effect"] == "read"}}


def text(t, error=False):
    return {"content": [{"type": "text", "text": t}], "isError": error}


def main():
    reg = Registry(home())
    eng = Engine(reg, connect(), "unknown-agent")
    eng.recover()

    def send(m):
        sys.stdout.write(json.dumps(m) + "\n")
        sys.stdout.flush()

    def call(p):
        name, args = p.get("name"), p.get("arguments") or {}
        if name == "agentgit_preview":
            return text(eng.diff())
        if name == "agentgit_status":
            return text(json.dumps(eng.stats()["summary"]))
        try:
            return text(agent_message(eng.stage(name, args)))
        except AdapterError as e:
            return text(f"ERROR: {e}", True)

    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                m = json.loads(line)
            except ValueError:
                send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
                continue
            meth, i, p = m.get("method"), m.get("id"), m.get("params") or {}
            try:
                if meth == "initialize":
                    eng.agent = (p.get("clientInfo") or {}).get("name") or "unknown-agent"
                    res = {"protocolVersion": p.get("protocolVersion", "2024-11-05"), "capabilities": {"tools": {}},
                           "serverInfo": {"name": "agentgit-gateway", "version": VERSION}, "instructions": INSTRUCTIONS}
                elif meth == "ping":
                    res = {}
                elif meth == "tools/list":
                    res = {"tools": [tool_def(s) for s in reg.tool_specs()] + HELPERS}
                elif meth == "tools/call":
                    res = call(p)
                elif i is None:
                    continue  # notification: no reply
                else:
                    send({"jsonrpc": "2.0", "id": i, "error": {"code": -32601, "message": f"method not found: {meth}"}})
                    continue
                if i is not None:
                    send({"jsonrpc": "2.0", "id": i, "result": res})
            except Exception as e:  # never crash the loop
                if i is not None:
                    send({"jsonrpc": "2.0", "id": i, "error": {"code": -32603, "message": str(e)}})
    finally:
        reg.close()


if __name__ == "__main__":
    main()
