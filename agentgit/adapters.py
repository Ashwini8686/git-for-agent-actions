"""Adapters: the only code that touches real data.

Every adapter provides read / describe / apply / undo / verify / snapshot.
apply() returns an exact undo record, so rollback is plain code, never an LLM guess.
"""
import hashlib
import json
import os
import uuid
from pathlib import Path


class AdapterError(Exception):
    pass


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class FilesAdapter:
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


class CalendarAdapter:
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


class MailAdapter:
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


class Registry:
    """Maps tool names to adapters and effect classes (read, reversible, irreversible)."""

    def __init__(self, home):
        home = Path(home)
        self.adapters = [FilesAdapter(home / "workspace"), CalendarAdapter(home / "calendar.json"), MailAdapter(home / "outbox.jsonl")]
        self.by_tool = {t: ad for ad in self.adapters for t in ad.tools}

    def effect(self, tool):
        ad = self.by_tool.get(tool)
        return ad.tools[tool] if ad else "irreversible"  # unknown tools are treated as the riskiest class

    def adapter(self, tool):
        if tool not in self.by_tool:
            raise AdapterError(f"unknown tool: {tool}")
        return self.by_tool[tool]

    def state_hash(self):
        return _sha("|".join(ad.snapshot() for ad in self.adapters))
