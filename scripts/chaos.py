"""Failure-injection experiment: the numbers for your pitch.

For every step of a 7-action workflow we make that step fail (or crash the process)
and check whether the world returns to exactly where it started.
Baseline = the same actions applied directly (how a plain MCP agent works).
Run: python scripts/chaos.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agentgit.engine import Crash, make_engine  # noqa: E402
from agentgit.seed import WORKFLOW, seed  # noqa: E402


def fresh():
    tmp = tempfile.TemporaryDirectory()
    os.environ["AGENTGIT_HOME"] = tmp.name
    seed()
    return tmp, make_engine()


def run_gateway(k, crash):
    tmp, eng = fresh()
    before = eng.reg.state_hash()
    for t, a in WORKFLOW:
        eng.stage(t, a)
    try:
        eng.commit(crash_at=k if crash else None, fail_at=None if crash else k)
    except Crash:
        eng.recover()
    ok = eng.reg.state_hash() == before
    eng.close(); tmp.cleanup()
    return ok


def run_baseline(k):
    tmp, eng = fresh()
    before = eng.reg.state_hash()
    for n, (t, a) in enumerate(WORKFLOW, 1):
        if n == k:
            break  # the agent fails here; nothing cleans up the earlier steps
        eng.reg.adapter(t).apply(t, a)
    ok = eng.reg.state_hash() == before
    eng.close(); tmp.cleanup()
    return ok


n = len(WORKFLOW)
rows = [(k, run_baseline(k), run_gateway(k, False), run_gateway(k, True)) for k in range(1, n + 1)]
print(f"{'fail at step':<14}{'plain agent':<14}{'gateway (error)':<18}{'gateway (crash)':<16}")
for k, b, g, c in rows:
    print(f"{k:<14}{'clean' if b else 'CORRUPTED':<14}{'clean' if g else 'CORRUPTED':<18}{'clean' if c else 'CORRUPTED':<16}")
print(f"\nPlain agent recovered cleanly in {sum(r[1] for r in rows)} of {n} runs "
      f"(step 1 is trivial: nothing had run yet).")
print(f"Gateway recovered cleanly in {sum(r[2] for r in rows)} of {n} error runs "
      f"and {sum(r[3] for r in rows)} of {n} crash runs.")
