"""Failure-injection experiment: the numbers for your pitch.

For every step of a workflow we make that step fail (or crash the process) and check whether the world
returns to EXACTLY where it started. Two targets:
  1. built-in adapters (7-action workflow)
  2. a separate third-party-style MCP server (examples/fake_calendar_mcp.py), driven only through MCP
Baseline = the same actions applied directly, the way a plain agent works.
Run: python scripts/chaos.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from agentgit.engine import Crash, make_engine  # noqa: E402
from agentgit.seed import WORKFLOW, seed  # noqa: E402

UP_WORKFLOW = [("cal_add_event", {"title": "Maths exam", "start": "2026-12-10T10:00"}),
               ("cal_add_event", {"title": "Physics exam", "start": "2026-12-12T10:00"}),
               ("cal_delete_event", {"event_id": "e1"}), ("cal_delete_event", {"event_id": "e2"}),
               ("cal_add_event", {"title": "DSA exam", "start": "2026-12-15T14:00"})]


def fresh(upstream):
    tmp = tempfile.TemporaryDirectory()
    os.environ["AGENTGIT_HOME"] = tmp.name
    os.environ.pop("AGENTGIT_CONFIG", None)
    seed()
    if upstream:
        cfg = json.loads((ROOT / "examples" / "agentgit.example.json").read_text())
        up = cfg["upstreams"][0]
        up["command"][1], up["env"]["FAKE_CAL_FILE"] = str(ROOT / "examples" / "fake_calendar_mcp.py"), tmp.name + "/fakecal.json"
        (Path(tmp.name) / "agentgit.json").write_text(json.dumps(cfg))
        (Path(tmp.name) / "fakecal.json").write_text(json.dumps([
            {"id": "e1", "title": "study block", "start": "2026-11-25T18:00"}, {"id": "e2", "title": "gym", "start": "2026-11-26T07:00"}]))
    return tmp, make_engine("chaos")


def run(workflow, k, mode, upstream):
    tmp, eng = fresh(upstream)
    before = eng.reg.state_hash()
    if mode == "baseline":
        for n, (t, a) in enumerate(workflow, 1):
            if n == k:
                break
            eng.reg.adapter(t).apply(t, a)
    else:
        for t, a in workflow:
            eng.stage(t, a)
        try:
            eng.commit(crash_at=k if mode == "crash" else None, fail_at=k if mode == "error" else None)
        except Crash:
            eng.recover()
    ok = eng.reg.state_hash() == before
    eng.reg.close(); eng.close(); tmp.cleanup()
    return ok


def experiment(title, workflow, upstream):
    n = len(workflow)
    rows = [(k, run(workflow, k, "baseline", upstream), run(workflow, k, "error", upstream), run(workflow, k, "crash", upstream)) for k in range(1, n + 1)]
    print(f"\n{title}\n{'fail at step':<14}{'plain agent':<14}{'gateway (error)':<18}{'gateway (crash)':<16}")
    for k, b, g, c in rows:
        print(f"{k:<14}{'clean' if b else 'CORRUPTED':<14}{'clean' if g else 'CORRUPTED':<18}{'clean' if c else 'CORRUPTED':<16}")
    print(f"Plain agent clean in {sum(r[1] for r in rows)}/{n} (step 1 is trivial); gateway clean in "
          f"{sum(r[2] for r in rows)}/{n} errors and {sum(r[3] for r in rows)}/{n} crashes.")


experiment("Built-in adapters (7 actions)", WORKFLOW, False)
experiment("Third-party MCP server via the gateway (5 actions)", UP_WORKFLOW, True)
