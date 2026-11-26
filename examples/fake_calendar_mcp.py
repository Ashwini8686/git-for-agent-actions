#!/usr/bin/env python3
"""A stand-alone MCP server (standard library only) that stands in for ANY third-party server.
AgentGit never imports this file: it talks to it over MCP, exactly as it would to Google Calendar, Slack, etc."""
import json
import os
import sys
import uuid
from pathlib import Path

FILE = Path(os.environ.get("FAKE_CAL_FILE", "fake_calendar.json"))
S = {"type": "string"}


def tool(name, desc, props, req, ro=False):
    return {"name": name, "description": desc, "inputSchema": {"type": "object", "properties": props, "required": req},
            "annotations": {"readOnlyHint": ro}}


TOOLS = [
    tool("list_events", "List events", {}, [], True),
    tool("get_event", "Get one event by id", {"event_id": S}, ["event_id"], True),
    tool("add_event", "Add an event", {"title": S, "start": S, "id": S}, ["title", "start"]),
    tool("delete_event", "Delete an event by id", {"event_id": S}, ["event_id"]),
    tool("send_invite", "Email an invite for an event (cannot be recalled)", {"event_id": S, "to": S}, ["event_id", "to"]),
]


def load():
    return json.loads(FILE.read_text()) if FILE.exists() else []


def run(name, a):
    ev = load()
    if name == "list_events":
        return "\n".join(f"{e['id']} {e['start']} {e['title']}" for e in sorted(ev, key=lambda e: e["start"])) or "(none)"
    if name == "get_event":
        e = next((x for x in ev if x["id"] == a["event_id"]), None)
        if not e:
            raise ValueError("event not found")
        return json.dumps(e)
    if name == "add_event":
        e = {"id": a.get("id") or "up_" + uuid.uuid4().hex[:6], "title": a["title"], "start": a["start"]}
        ev.append(e)
        FILE.write_text(json.dumps(ev))
        return json.dumps(e)
    if name == "delete_event":
        if not any(x["id"] == a["event_id"] for x in ev):
            raise ValueError("event not found")
        FILE.write_text(json.dumps([x for x in ev if x["id"] != a["event_id"]]))
        return "deleted"
    if name == "send_invite":
        return f"invite sent to {a['to']}"
    raise ValueError("unknown tool")


def reply(i, result=None, error=None):
    m = {"jsonrpc": "2.0", "id": i}
    m.update({"error": error} if error else {"result": result})
    sys.stdout.write(json.dumps(m) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    if not line.strip():
        continue
    m = json.loads(line)
    meth, i, p = m.get("method"), m.get("id"), m.get("params") or {}
    if i is None:
        continue
    if meth == "initialize":
        reply(i, {"protocolVersion": p.get("protocolVersion", "2024-11-05"), "capabilities": {"tools": {}},
                  "serverInfo": {"name": "fake-calendar", "version": "1"}})
    elif meth == "tools/list":
        reply(i, {"tools": TOOLS})
    elif meth == "tools/call":
        try:
            reply(i, {"content": [{"type": "text", "text": run(p["name"], p.get("arguments") or {})}], "isError": False})
        except Exception as e:
            reply(i, {"content": [{"type": "text", "text": str(e)}], "isError": True})
    else:
        reply(i, error={"code": -32601, "message": "method not found"})
