"""Transaction engine: stage -> diff -> commit -> verify -> revert, plus risk policy,
a tamper-evident audit chain and Routine Capsules."""
import hashlib
import json
import time

from .adapters import AdapterError, Registry
from .db import connect, home
from .policy import DESTRUCTIVE, denied

RANK = {"reversible": 0, "irreversible": 1}  # irreversible steps always run last


class PolicyError(AdapterError):
    """An action was blocked by policy."""


class InjectedFailure(Exception):
    """Used by tests, the chaos script and the dashboard's chaos lab."""


class Crash(BaseException):
    """Simulates the process dying mid-commit (not caught by 'except Exception')."""


def symbol(tool, effect):
    if effect == "irreversible":
        return "!"
    if DESTRUCTIVE.search(tool):
        return "-"
    return ">" if "move" in tool else "+"


def agent_message(r):
    """The text an agent sees after calling a tool."""
    if r["effect"] == "read":
        return r["result"]
    if "commit" in r and not r["commit"]["ok"]:
        return f"FAILED and rolled back: {r['commit'].get('error')}"
    if r.get("auto_committed"):
        return f"AUTO-APPROVED (low risk, undo available): {r['description']}"
    return (f"STAGED, NOT EXECUTED (batch #{r['batch']}, step {r['seq']}, risk {r['risk']}): {r['description']}. "
            "Nothing has changed yet. A human must approve the batch on the AgentGit dashboard.")


def _sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


class Engine:
    def __init__(self, reg: Registry, conn, agent="local"):
        self.reg, self.c, self.agent = reg, conn, agent

    def close(self):
        self.c.close()

    # ---------- audit chain ----------
    def _log(self, batch, event, detail="", agent=None):
        """Append-only log where every row hashes the previous one (tamper-evident)."""
        self.c.commit()
        self.c.execute("BEGIN IMMEDIATE")
        row = self.c.execute("SELECT hash FROM log WHERE hash IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
        prev, ts, agent = (row[0] if row else "GENESIS"), time.time(), agent or self.agent
        h = _sha(f"{prev}|{ts!r}|{batch}|{event}|{detail}|{agent}")
        self.c.execute("INSERT INTO log(ts,batch_id,event,detail,agent,prev,hash) VALUES(?,?,?,?,?,?,?)",
                       (ts, batch, event, detail, agent, prev, h))
        self.c.commit()

    def verify_log(self):
        prev, n = "GENESIS", 0
        for r in self.c.execute("SELECT * FROM log WHERE hash IS NOT NULL ORDER BY id").fetchall():
            h = _sha(f"{prev}|{r['ts']!r}|{r['batch_id']}|{r['event']}|{r['detail']}|{r['agent']}")
            if r["prev"] != prev or r["hash"] != h:
                return {"ok": False, "entries": n, "broken_at": r["id"]}
            prev, n = r["hash"], n + 1
        return {"ok": True, "entries": n, "broken_at": None}

    def log_tail(self, limit=40):
        return [dict(r) for r in self.c.execute(
            "SELECT id,ts,batch_id,event,detail,agent,substr(hash,1,10) AS hash FROM log ORDER BY id DESC LIMIT ?", (limit,))]

    # ---------- helpers ----------
    def _batch(self, batch_id=None, status=None):
        if batch_id is not None:
            return self.c.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
        return self.c.execute("SELECT * FROM batches WHERE status=? ORDER BY id DESC LIMIT 1", (status or "staging",)).fetchone()

    def _set(self, bid, status):
        self.c.execute("UPDATE batches SET status=?, updated=? WHERE id=?", (status, time.time(), bid))
        self.c.commit()

    def _rows(self, bid):
        rows = self.c.execute("SELECT * FROM actions WHERE batch_id=?", (bid,)).fetchall()
        return sorted(rows, key=lambda r: (RANK[r["effect"]], r["seq"]))

    # ---------- stage ----------
    def stage(self, tool, args, agent=None):
        """Reads run now. Writes are only recorded, never executed (unless policy auto-approves a tiny safe one)."""
        agent, pol = agent or self.agent, self.reg.policy
        ad = self.reg.adapter(tool)
        if denied(pol.get("deny", []), tool):
            self._log(None, "blocked", f"{tool}: denied by policy", agent)
            raise PolicyError(f"blocked by policy: {tool}")
        eff = ad.effect_of(tool)
        if eff == "read":
            self._log(None, "read", tool, agent)
            return {"effect": "read", "result": ad.read(tool, args)}
        try:
            desc = ad.describe(tool, args)
        except KeyError as e:
            raise AdapterError(f"missing argument {e}") from None
        b = self._batch(status="staging")
        if b:
            rows = self.c.execute("SELECT tool FROM actions WHERE batch_id=?", (b["id"],)).fetchall()
            deletes = sum(1 for r in rows if DESTRUCTIVE.search(r["tool"]))
            if len(rows) >= pol["max_actions_per_batch"] or (DESTRUCTIVE.search(tool) and deletes >= pol["max_deletes_per_batch"]):
                self._log(b["id"], "blocked", f"{tool}: batch limit reached", agent)
                raise PolicyError("batch limit reached; a human must approve or reject the current batch first")
        else:
            now = time.time()
            cur = self.c.execute("INSERT INTO batches(status,created,updated,note,agent,risk) VALUES('staging',?,?,?,?,0)",
                                 (now, now, json.dumps({"pre": self.reg.state_hash()}), agent))
            self.c.commit()
            b = self._batch(cur.lastrowid)
        seq = self.c.execute("SELECT COALESCE(MAX(seq),0)+1 FROM actions WHERE batch_id=?", (b["id"],)).fetchone()[0]
        idem = _sha(json.dumps([b["id"], seq, tool, args], sort_keys=True))[:16]
        risk = ad.risk_of(tool)
        self.c.execute("INSERT INTO actions(batch_id,seq,tool,args,effect,status,idem,desc,risk) VALUES(?,?,?,?,?,'staged',?,?,?)",
                       (b["id"], seq, tool, json.dumps(args), eff, idem, desc, risk))
        self.c.execute("UPDATE batches SET risk=risk+?, updated=? WHERE id=?", (risk, time.time(), b["id"]))
        self.c.commit()
        self._log(b["id"], "staged", desc, agent)
        out = {"effect": eff, "staged": True, "batch": b["id"], "seq": seq, "description": desc, "risk": risk}
        thr = pol.get("auto_approve_max_risk", 0)
        if thr and eff == "reversible" and risk <= thr and seq == 1:  # opt-in autopilot: one small, undoable action
            r = self.commit(b["id"])
            out["auto_committed"], out["commit"] = r["ok"], r
        return out

    def diff(self, batch_id=None):
        b = self._batch(batch_id) if batch_id else self._batch(status="staging")
        if not b:
            return "Nothing staged."
        lines = [f"Batch #{b['id']} [{b['status']}] agent={b['agent']} risk={b['risk']}"]
        for n, r in enumerate(self._rows(b["id"]), 1):
            lines.append(f"  {n}. {symbol(r['tool'], r['effect'])} [{r['effect']}] {r['desc']}")
        return "\n".join(lines)

    # ---------- commit ----------
    def commit(self, batch_id=None, confirm_irreversible=False, fail_at=None, crash_at=None, force=False):
        b = self._batch(batch_id) if batch_id else self._batch(status="staging")
        if not b or b["status"] != "staging":
            return {"ok": False, "error": "nothing staged to commit"}
        rows = self._rows(b["id"])
        if any(r["effect"] == "irreversible" for r in rows) and not confirm_irreversible:
            return {"ok": False, "error": "irreversible actions need explicit confirmation"}
        if not force and self.reg.state_hash() != json.loads(b["note"])["pre"]:
            return {"ok": False, "stale": True, "error": "data changed since staging; reject and stage again"}
        self._set(b["id"], "committing")
        try:
            for n, r in enumerate(rows, 1):
                if crash_at == n:
                    raise Crash()
                if fail_at == n:
                    raise InjectedFailure(f"injected failure at step {n}")
                undo = self.reg.adapter(r["tool"]).apply(r["tool"], json.loads(r["args"]))
                self.c.execute("UPDATE actions SET status='applied', ord=?, undo=? WHERE id=?", (n, json.dumps(undo), r["id"]))
                self.c.commit()
            for r in rows:  # verify: re-read real state and compare with what was approved
                u = json.loads(self.c.execute("SELECT undo FROM actions WHERE id=?", (r["id"],)).fetchone()[0])
                if not self.reg.adapter(r["tool"]).verify(r["tool"], json.loads(r["args"]), u):
                    raise AdapterError(f"verification failed at step {r['seq']}")
        except Exception as e:
            return self._rollback(b["id"], str(e))
        self._set(b["id"], "committed")
        self._log(b["id"], "committed", f"{len(rows)} actions, verified")
        return {"ok": True, "batch": b["id"], "applied": len(rows), "verified": True}

    def _undo_applied(self, bid, status_after):
        stuck = []
        rows = self.c.execute("SELECT * FROM actions WHERE batch_id=? AND status='applied' ORDER BY ord DESC", (bid,)).fetchall()
        for r in rows:
            try:
                if r["effect"] == "irreversible":
                    raise AdapterError("irreversible")
                self.reg.adapter(r["tool"]).undo(json.loads(r["undo"]))
                self.c.execute("UPDATE actions SET status=? WHERE id=?", (status_after, r["id"]))
            except Exception:
                stuck.append(r["seq"])
        self.c.commit()
        return stuck

    def _rollback(self, bid, error):
        stuck = self._undo_applied(bid, "rolled_back")
        self.c.execute("UPDATE actions SET status='skipped' WHERE batch_id=? AND status='staged'", (bid,))
        self._set(bid, "needs_attention" if stuck else "rolled_back")
        self._log(bid, "rolled_back", f"{error}; stuck={stuck}")
        return {"ok": False, "rolled_back": not stuck, "error": error, "stuck": stuck}

    def recover(self):
        """Crash recovery: any batch left 'committing' is rolled back on startup."""
        for b in self.c.execute("SELECT id FROM batches WHERE status='committing'").fetchall():
            self._rollback(b["id"], "recovered after crash")

    # ---------- reject / revert ----------
    def reject(self, batch_id=None):
        b = self._batch(batch_id) if batch_id else self._batch(status="staging")
        if not b or b["status"] != "staging":
            return {"ok": False, "error": "nothing staged"}
        self.c.execute("UPDATE actions SET status='rejected' WHERE batch_id=?", (b["id"],))
        self._set(b["id"], "rejected")
        self._log(b["id"], "rejected")
        return {"ok": True, "batch": b["id"]}

    def revert(self, batch_id):
        b = self._batch(batch_id)
        if not b or b["status"] != "committed":
            return {"ok": False, "error": "only committed batches can be reverted"}
        stuck = self._undo_applied(b["id"], "reverted")
        self._set(b["id"], "reverted" if not stuck else "partly_reverted")
        self._log(b["id"], "reverted", f"could not undo steps {stuck}")
        return {"ok": not stuck, "batch": b["id"], "could_not_undo": stuck}

    # ---------- capsules (verified plans replayed with no LLM) ----------
    def save_capsule(self, batch_id, name):
        b = self._batch(batch_id)
        if not b or b["status"] not in ("committed", "reverted"):
            return {"ok": False, "error": "only a committed batch can become a capsule"}
        acts = [{"tool": r["tool"], "args": json.loads(r["args"])} for r in sorted(self._rows(b["id"]), key=lambda r: r["seq"])]
        self.c.execute("INSERT OR REPLACE INTO capsules(name,actions,created,runs) VALUES(?,?,?,COALESCE((SELECT runs FROM capsules WHERE name=?),0))",
                       (name, json.dumps(acts), time.time(), name))
        self.c.commit()
        self._log(b["id"], "capsule_saved", name)
        return {"ok": True, "name": name, "actions": len(acts)}

    def run_capsule(self, name, agent=None):
        row = self.c.execute("SELECT * FROM capsules WHERE name=?", (name,)).fetchone()
        if not row:
            return {"ok": False, "error": f"no capsule named {name}"}
        acts = json.loads(row["actions"])
        for a in acts:
            self.stage(a["tool"], a["args"], agent)  # replay is staged like any agent action: a human still approves
        self.c.execute("UPDATE capsules SET runs=runs+1 WHERE name=?", (name,))
        self._log(None, "capsule_run", name, agent)
        return {"ok": True, "staged": len(acts)}

    def capsules(self):
        return [{"name": r["name"], "actions": len(json.loads(r["actions"])), "runs": r["runs"], "created": r["created"]}
                for r in self.c.execute("SELECT * FROM capsules ORDER BY created DESC")]

    # ---------- reporting ----------
    def history(self, limit=15):
        return self.c.execute(
            "SELECT b.id, b.status, b.created, b.agent, b.risk, (SELECT COUNT(*) FROM actions a WHERE a.batch_id=b.id) AS n "
            "FROM batches b ORDER BY b.id DESC LIMIT ?", (limit,)).fetchall()

    def batches(self, limit=30):
        out = []
        for h in self.history(limit):
            d = dict(h)
            d["actions"] = [{"seq": r["seq"], "tool": r["tool"], "effect": r["effect"], "status": r["status"], "desc": r["desc"],
                             "risk": r["risk"], "symbol": symbol(r["tool"], r["effect"])} for r in self._rows(h["id"])]
            out.append(d)
        return out

    def stats(self):
        q = lambda s, *a: self.c.execute(s, a).fetchall()  # noqa: E731
        st = {r[0]: r[1] for r in q("SELECT status,COUNT(*) FROM batches GROUP BY status")}
        ef = {r[0]: r[1] for r in q("SELECT effect,COUNT(*) FROM actions GROUP BY effect")}
        ev = {r[0]: r[1] for r in q("SELECT event,COUNT(*) FROM log GROUP BY event")}
        pend = q("SELECT COUNT(a.id), COALESCE(MAX(b.risk),0) FROM batches b LEFT JOIN actions a ON a.batch_id=b.id WHERE b.status='staging'")[0]
        done, bad = st.get("committed", 0), st.get("rolled_back", 0) + st.get("needs_attention", 0)
        agents = {r["agent"]: {"agent": r["agent"], "batches": r["batches"], "committed": r["committed"] or 0, "failed": r["failed"] or 0, "actions": 0}
                  for r in q("SELECT agent, COUNT(*) batches, SUM(status='committed') committed, "
                             "SUM(status IN ('rolled_back','needs_attention')) failed FROM batches GROUP BY agent")}
        for r in q("SELECT b.agent, COUNT(a.id) n FROM actions a JOIN batches b ON a.batch_id=b.id GROUP BY b.agent"):
            agents[r["agent"]]["actions"] = r["n"]
        recent = [dict(r) for r in q("SELECT b.id,b.status,b.agent,b.risk,b.created,"
                                     "(SELECT COUNT(*) FROM actions a WHERE a.batch_id=b.id) n FROM batches b ORDER BY b.id DESC LIMIT 14")][::-1]
        return {"summary": {"pending_actions": pend[0], "pending_risk": pend[1], "committed": done, "rolled_back": bad,
                            "reverted": st.get("reverted", 0), "blocked": ev.get("blocked", 0), "reads": ev.get("read", 0),
                            "batches": sum(st.values()),
                            "success_rate": round(100 * done / (done + bad), 1) if done + bad else None},
                "status": st, "effects": ef, "recent": recent, "agents": list(agents.values())}


def make_engine(agent="local", reg=None, recover=True) -> Engine:
    eng = Engine(reg or Registry(home()), connect(), agent)
    if recover:
        eng.recover()
    return eng
