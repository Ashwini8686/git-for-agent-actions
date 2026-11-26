"""Adapters: the only code that touches real data.

Every adapter provides read / describe / apply / undo / verify / snapshot.
apply() returns an exact undo record, so rollback is plain code, never an LLM guess.
"""
import hashlib
import json
import os
import re
import threading
import uuid
from pathlib import Path

from .mcpwire import StdioMCPClient
from .policy import classify_name, default_risk, load_config, render


class AdapterError(Exception):
    pass


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()

def _mentions(text, value) -> bool:
    """True if value appears as a whole token, so id 'e1' does not match inside 'up_ae1f3b'."""
    return re.search(rf"(?<![\w-]){re.escape(str(value))}(?![\w-])", text) is not None


_STR = {"type": "string"}


def _S(desc, props, req):
    return {"description": desc, "inputSchema": {"type": "object", "properties": props, "required": req}}


SCHEMAS = {
    "list_files": _S("List files in a workspace folder.", {"folder": _STR}, []),
    "move_file": _S("Move a file; dst may be a folder like 'Study/'.", {"src": _STR, "dst": _STR}, ["src", "dst"]),
    "delete_file": _S("Delete a file (kept in trash, restorable).", {"path": _STR}, ["path"]),
    "list_events": _S("List calendar events with their ids.", {}, []),
    "add_event": _S("Add a calendar event; start looks like 2026-12-10T10:00.", {"title": _STR, "start": _STR, "end": _STR}, ["title", "start"]),
    "delete_event": _S("Delete a calendar event by id.", {"event_id": _STR}, ["event_id"]),
    "send_email": _S("Send an email (irreversible; needs explicit confirmation).", {"to": _STR, "subject": _STR, "body": _STR}, ["to", "subject"]),
}


class _Local:
    """Shared behaviour of the built-in demo adapters."""

    def owns(self, tool):
        return tool in self.tools

    def effect_of(self, tool):
        return self.tools[tool]

    def risk_of(self, tool):
        return default_risk(self.tools[tool], tool)

    def specs(self):
        return [dict(name=t, effect=e, risk=self.risk_of(t), **SCHEMAS[t]) for t, e in self.tools.items()]


class FilesAdapter(_Local):
    name = "files"
    tools = {"list_files": "read", "move_file": "reversible", "delete_file": "reversible"}

    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.trash = self.root / ".trash"

    def _p(self, rel) -> Path:
        p = (self.root / str(rel)).resolve()
        if p != self.root and self.root not in p.parents:
            raise AdapterError(f"path escapes the workspace: {rel}")
        return p

    def _rel(self, p) -> str:
        return str(Path(p).relative_to(self.root))

    def _move_paths(self, a):
        s, d = self._p(a["src"]), self._p(a["dst"])
        if d.is_dir() or str(a["dst"]).endswith("/"):
            d = d / s.name
        return s, d

    def read(self, tool, a):
        d = self._p(a.get("folder", "."))
        if not d.is_dir():
            raise AdapterError(f"not a folder: {a.get('folder')}")
        names = sorted(c.name + ("/" if c.is_dir() else "") for c in d.iterdir() if c.name != ".trash")
        return "\n".join(names) or "(empty)"

    def describe(self, tool, a):
        if tool == "move_file":
            return f"Move '{a['src']}' to '{a['dst']}'"
        return f"Delete '{a['path']}' (kept in .trash, restorable)"

    def apply(self, tool, a):
        if tool == "move_file":
            s, d = self._move_paths(a)
            if not s.is_file():
                raise AdapterError(f"source file missing: {a['src']}")
            if d.exists():
                raise AdapterError(f"destination already exists: {self._rel(d)}")
            made, q = [], d.parent
            while not q.exists():
                made.append(q)
                q = q.parent
            d.parent.mkdir(parents=True, exist_ok=True)
            s.rename(d)
            return {"from": self._rel(d), "to": self._rel(s), "rmdirs": [self._rel(m) for m in made]}
        s = self._p(a["path"])
        if not s.is_file():
            raise AdapterError(f"file missing: {a['path']}")
        self.trash.mkdir(exist_ok=True)
        t = self.trash / f"{uuid.uuid4().hex[:8]}_{s.name}"
        s.rename(t)
        return {"from": self._rel(t), "to": self._rel(s), "rmdirs": []}

    def undo(self, u):
        s, d = self._p(u["from"]), self._p(u["to"])
        if not s.exists():
            raise AdapterError("cannot undo: file is gone")
        d.parent.mkdir(parents=True, exist_ok=True)
        s.rename(d)
        for r in u.get("rmdirs", []):
            try:
                self._p(r).rmdir()
            except OSError:
                pass

    def verify(self, tool, a, u):
        return self._p(u["from"]).is_file() and not self._p(u["to"]).exists()

    def snapshot(self):
        parts = []
        for p in sorted(self.root.rglob("*")):
            if ".trash" in p.parts or not p.is_file():
                continue
            parts.append(self._rel(p) + _sha(p.read_bytes().hex()))
        return _sha("|".join(parts))


class CalendarAdapter(_Local):
    """A local JSON calendar. A Google Calendar adapter would implement the same methods."""
    name = "calendar"
    tools = {"list_events": "read", "add_event": "reversible", "delete_event": "reversible"}

    def __init__(self, path):
        self.path = Path(path)

    def _load(self):
        return json.loads(self.path.read_text()) if self.path.exists() else []

    def _save(self, events):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(events, indent=1))
        os.replace(tmp, self.path)

    def _find(self, eid):
        return next((e for e in self._load() if e["id"] == eid), None)

    def read(self, tool, a):
        ev = sorted(self._load(), key=lambda e: e["start"])
        return "\n".join(f'{e["id"]}  {e["start"]}  {e["title"]}' for e in ev) or "(no events)"

    def describe(self, tool, a):
        if tool == "add_event":
            return f"Add event '{a['title']}' at {a['start']}"
        e = self._find(a["event_id"])
        return f"Delete event '{e['title']}' ({e['start']})" if e else f"Delete event {a['event_id']} (not found)"

    def apply(self, tool, a):
        ev = self._load()
        if tool == "add_event":
            if not a.get("title") or not a.get("start"):
                raise AdapterError("title and start are required")
            e = {"id": "ev_" + uuid.uuid4().hex[:6], "title": a["title"], "start": a["start"], "end": a.get("end") or a["start"]}
            ev.append(e)
            self._save(ev)
            return {"op": "remove", "id": e["id"]}
        i = next((k for k, e in enumerate(ev) if e["id"] == a["event_id"]), None)
        if i is None:
            raise AdapterError(f"event not found: {a['event_id']}")
        e = ev.pop(i)
        self._save(ev)
        return {"op": "restore", "event": e, "index": i}

    def undo(self, u):
        ev = self._load()
        if u["op"] == "remove":
            ev = [e for e in ev if e["id"] != u["id"]]
        else:
            ev.insert(min(u["index"], len(ev)), u["event"])
        self._save(ev)

    def verify(self, tool, a, u):
        ids = {e["id"] for e in self._load()}
        return (u["id"] in ids) if tool == "add_event" else (a["event_id"] not in ids)

    def snapshot(self):
        return _sha(json.dumps(sorted(self._load(), key=lambda e: e["id"]), sort_keys=True))


class MailAdapter(_Local):
    """Writes to an outbox file. Sending is irreversible, so it is held and run last."""
    name = "mail"
    tools = {"send_email": "irreversible"}

    def __init__(self, path):
        self.path = Path(path)

    def describe(self, tool, a):
        return f"SEND email to {a['to']}: '{a['subject']}' (cannot be undone)"

    def apply(self, tool, a):
        with self.path.open("a") as f:
            f.write(json.dumps({"to": a["to"], "subject": a["subject"], "body": a.get("body", "")}) + "\n")
        return {}

    def undo(self, u):
        raise AdapterError("sent email cannot be undone")

    def verify(self, tool, a, u):
        lines = self.path.read_text().splitlines() if self.path.exists() else []
        return bool(lines) and json.loads(lines[-1])["to"] == a["to"]

    def snapshot(self):
        return _sha(self.path.read_text() if self.path.exists() else "")


class UpstreamAdapter:
    """Wraps ANY MCP server. Compensation (undo) is declared in config, never guessed by an LLM.

    rules per upstream tool:  capture (read before-image), undo (inverse call), verify, describe, effect, risk
    """

    def __init__(self, cfg):
        self.cfg, self.name = cfg, cfg["name"]
        self.prefix = cfg.get("prefix", self.name + "_")
        self.rules = cfg.get("tools", {})
        self._client, self._tools, self._lock = None, None, threading.RLock()

    # ----- plumbing -----
    def _cl(self):
        with self._lock:
            if self._client is None or self._client.p.poll() is not None:
                self._client = StdioMCPClient(self.cfg["command"], self.cfg.get("env"), self.cfg.get("cwd"))
            return self._client

    def _call(self, raw, args):
        text, err = self._cl().call_tool(raw, args)
        if err:
            raise AdapterError(f"{raw} failed: {text[:200]}")
        return text

    @staticmethod
    def _parse(text):
        try:
            v = json.loads(text)
            return v if isinstance(v, (dict, list)) else {"text": text}
        except ValueError:
            return {"text": text}

    def upstream_tools(self):
        with self._lock:
            if self._tools is None:
                self._tools = self._cl().list_tools()
            return self._tools

    def close(self):
        if self._client:
            self._client.close()

    # ----- classification -----
    def owns(self, tool):
        return tool.startswith(self.prefix)

    def raw(self, tool):
        return tool[len(self.prefix):]

    def effect_of(self, tool):
        raw, rule = self.raw(tool), self.rules.get(self.raw(tool), {})
        if rule.get("effect"):
            return rule["effect"]
        spec = next((t for t in self.upstream_tools() if t["name"] == raw), None)
        if spec is None:
            raise AdapterError(f"unknown tool: {tool}")
        if (spec.get("annotations") or {}).get("readOnlyHint") or classify_name(raw) == "read":
            return "read"
        return "reversible" if rule.get("undo") else "irreversible"  # no declared undo = treat as irreversible

    def risk_of(self, tool):
        rule = self.rules.get(self.raw(tool), {})
        return rule["risk"] if "risk" in rule else default_risk(self.effect_of(tool), self.raw(tool))

    def specs(self):
        out = []
        for t in self.upstream_tools():
            name = self.prefix + t["name"]
            out.append({"name": name, "description": t.get("description", ""), "effect": self.effect_of(name),
                        "risk": self.risk_of(name), "inputSchema": t.get("inputSchema") or {"type": "object", "properties": {}}})
        return out

    # ----- adapter interface -----
    def read(self, tool, a):
        return self._call(self.raw(tool), a)

    def describe(self, tool, a):
        raw, rule = self.raw(tool), self.rules.get(self.raw(tool), {})
        tpl, ctx = rule.get("describe"), {"args": a}
        if not tpl:
            return f"{raw}({', '.join(f'{k}={v!r}' for k, v in a.items())})"
        if "{before" in tpl and rule.get("capture"):  # preview: read the current state to show what will change
            c = rule["capture"]
            try:
                ctx["before"] = self._parse(self._call(c["tool"], render(c.get("args", {}), ctx)))
            except Exception:
                ctx["before"] = {}
        return render(tpl, ctx)

    def apply(self, tool, a):
        raw, rule, ctx = self.raw(tool), self.rules.get(self.raw(tool), {}), {"args": a}
        if rule.get("capture"):
            c = rule["capture"]
            ctx["before"] = self._parse(self._call(c["tool"], render(c.get("args", {}), ctx)))
        ctx["result"] = self._parse(self._call(raw, a))
        u = rule.get("undo")
        return {"tool": u["tool"], "args": render(u.get("args", {}), ctx)} if u else {}

    def undo(self, u):
        if not u.get("tool"):
            raise AdapterError("no undo declared for this tool")
        self._call(u["tool"], u["args"])

    def verify(self, tool, a, u):
        v = self.rules.get(self.raw(tool), {}).get("verify")
        if not v:
            return True
        out = self._call(v["tool"], render(v.get("args", {}), {"args": a}))
        if "contains" in v:
            return _mentions(out, render(v["contains"], {"args": a}))
        if "absent" in v:
            return not _mentions(out, render(v["absent"], {"args": a}))
        return True

    def snapshot(self):
        s = self.cfg.get("snapshot")
        return _sha(self._call(s["tool"], s.get("args", {}))) if s else ""


class Registry:
    """All tools the gateway knows: built-in demo adapters plus any number of upstream MCP servers."""

    def __init__(self, home, cfg=None):
        self.cfg = cfg or load_config()
        self.policy = self.cfg["policy"]
        home = Path(home)
        self.adapters = []
        if self.cfg.get("builtin", True):
            self.adapters += [FilesAdapter(home / "workspace"), CalendarAdapter(home / "calendar.json"), MailAdapter(home / "outbox.jsonl")]
        self.adapters += [UpstreamAdapter(u) for u in self.cfg.get("upstreams", [])]

    def adapter(self, tool):
        for ad in self.adapters:
            if ad.owns(tool):
                return ad
        raise AdapterError(f"unknown tool: {tool}")

    def effect(self, tool):
        try:
            return self.adapter(tool).effect_of(tool)
        except AdapterError:
            return "irreversible"  # unknown tools are treated as the riskiest class

    def tool_specs(self):
        return [s for ad in self.adapters for s in ad.specs()]

    def state_hash(self):
        return _sha("|".join(ad.snapshot() for ad in self.adapters))

    def builtin_view(self):
        if not self.cfg.get("builtin", True):
            return None
        return {"files": self.adapters[0].read("list_files", {}), "calendar": self.adapters[1].read("list_events", {})}

    def close(self):
        for ad in self.adapters:
            if hasattr(ad, "close"):
                ad.close()
