"""Config, effect classification, risk scoring and the compensation template language."""
import fnmatch
import json
import os
import re
from pathlib import Path

from .db import home

DEFAULT = {"builtin": True, "upstreams": [],
           "policy": {"max_actions_per_batch": 50, "max_deletes_per_batch": 10, "deny": [], "auto_approve_max_risk": 0}}
READ_PREFIXES = ("get_", "list_", "read_", "search_", "find_", "fetch_", "show_", "describe_", "view_", "query_")
DESTRUCTIVE = re.compile(r"(delete|remove|drop|destroy|purge|erase|cancel)", re.I)
_T = re.compile(r"\{(args|result|before)((?:\.[\w-]+)*)\}")


def load_config():
    """Reads agentgit.json from AGENTGIT_CONFIG or the data folder; falls back to built-in demo tools."""
    cfg = json.loads(json.dumps(DEFAULT))
    p = Path(os.environ.get("AGENTGIT_CONFIG") or (home() / "agentgit.json"))
    if p.exists():
        user = json.loads(p.read_text())
        cfg["builtin"] = user.get("builtin", True)
        cfg["upstreams"] = user.get("upstreams", [])
        cfg["policy"].update(user.get("policy", {}))
    return cfg


def classify_name(raw):
    return "read" if raw.lower().startswith(READ_PREFIXES) else None


def default_risk(effect, name):
    if effect == "read":
        return 0
    if effect == "irreversible":
        return 5
    return 3 if DESTRUCTIVE.search(name) else 1


def denied(patterns, tool):
    return any(fnmatch.fnmatch(tool, p) for p in patterns)


def _get(ctx, root, path):
    v = ctx.get(root)
    for k in [p for p in path.split(".") if p]:
        if isinstance(v, dict) and k in v:
            v = v[k]
        elif isinstance(v, list) and k.isdigit() and int(k) < len(v):
            v = v[int(k)]
        else:
            return None
    return v


def render(val, ctx):
    """Fills {args.x}, {result.id}, {before.title} templates. A whole-string template keeps its type."""
    if isinstance(val, str):
        m = _T.fullmatch(val)
        if m:
            return _get(ctx, m.group(1), m.group(2))
        return _T.sub(lambda m: str(_get(ctx, m.group(1), m.group(2))), val)
    if isinstance(val, dict):
        return {k: render(v, ctx) for k, v in val.items()}
    if isinstance(val, list):
        return [render(v, ctx) for v in val]
    return val
