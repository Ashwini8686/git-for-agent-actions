"""The transaction engine: stage -> diff -> commit -> verify -> revert."""
import hashlib
import json
import time

from .adapters import AdapterError, Registry
from .db import connect, home

RANK = {"reversible": 0, "irreversible": 1}  # irreversible steps always run last
SYMBOL = {"add_event": "+", "delete_event": "-", "delete_file": "-", "move_file": ">", "send_email": "!"}


class InjectedFailure(Exception):
    """Used by tests and the chaos script to make a step fail."""


class Crash(BaseException):
    """Simulates the process dying mid-commit (not caught by 'except Exception')."""


class Engine:
    def __init__(self, reg: Registry, conn):
        self.reg, self.c = reg, conn

    def close(self):
        self.c.close()

    # ---------- helpers ----------
    def _log(self, batch, event, detail=""):
        self.c.execute("INSERT INTO log(ts,batch_id,event,detail) VALUES(?,?,?,?)", (time.time(), batch, event, detail))
        self.c.commit()

    def _batch(self, batch_id=None, status=None):
        if batch_id is not None:
            return self.c.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
        q = "SELECT * FROM batches WHERE status=? ORDER BY id DESC LIMIT 1"
        return self.c.execute(q, (status or "staging",)).fetchone()

    def _set(self, bid, status):
        self.c.execute("UPDATE batches SET status=?, updated=? WHERE id=?", (status, time.time(), bid))
        self.c.commit()

    def _rows(self, bid):
        rows = self.c.execute("SELECT * FROM actions WHERE batch_id=?", (bid,)).fetchall()
        return sorted(rows, key=lambda r: (RANK[r["effect"]], r["seq"]))

    # ---------- stage ----------
    def stage(self, tool, args):
        """Reads run now. Writes are only recorded, never executed."""
        ad, eff = self.reg.adapter(tool), self.reg.effect(tool)
        if eff == "read":
            self._log(None, "read", tool)
            return {"effect": "read", "result": ad.read(tool, args)}
        try:
            desc = ad.describe(tool, args)
        except KeyError as e:
            raise AdapterError(f"missing argument {e}") from None
        b = self._batch(status="staging")
        if not b:
            now = time.time()
            cur = self.c.execute("INSERT INTO batches(status,created,updated,note) VALUES('staging',?,?,?)",
                                 (now, now, json.dumps({"pre": self.reg.state_hash()})))
            self.c.commit()
            b = self._batch(cur.lastrowid)
        seq = self.c.execute("SELECT COALESCE(MAX(seq),0)+1 FROM actions WHERE batch_id=?", (b["id"],)).fetchone()[0]
        idem = hashlib.sha256(json.dumps([b["id"], seq, tool, args], sort_keys=True).encode()).hexdigest()[:16]
        self.c.execute("INSERT INTO actions(batch_id,seq,tool,args,effect,status,idem,desc) VALUES(?,?,?,?,?,'staged',?,?)",
                       (b["id"], seq, tool, json.dumps(args), eff, idem, desc))
        self.c.commit()
        self._log(b["id"], "staged", desc)
        return {"effect": eff, "staged": True, "batch": b["id"], "seq": seq, "description": desc}

    def diff(self, batch_id=None):
        b = self._batch(batch_id) if batch_id else self._batch(status="staging")
        if not b:
            return "Nothing staged."
        lines = [f"Batch #{b['id']} [{b['status']}]"]
        for n, r in enumerate(self._rows(b["id"]), 1):
            lines.append(f"  {n}. {SYMBOL.get(r['tool'], '?')} [{r['effect']}] {r['desc']}")
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

    # ---------- reject / revert / history ----------
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

    def history(self, limit=15):
        return self.c.execute(
            "SELECT b.id, b.status, b.created, (SELECT COUNT(*) FROM actions a WHERE a.batch_id=b.id) AS n "
            "FROM batches b ORDER BY b.id DESC LIMIT ?", (limit,)).fetchall()


def make_engine() -> Engine:
    eng = Engine(Registry(home()), connect())
    eng.recover()
    return eng
