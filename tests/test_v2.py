import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from agentgit.adapters import AdapterError
from agentgit.db import connect, home
from agentgit.engine import Engine, PolicyError, make_engine
from agentgit.seed import seed

ROOT = Path(__file__).resolve().parent.parent
CAL = ROOT / "examples" / "fake_calendar_mcp.py"


def write_config(h, **policy):
    cfg = json.loads((ROOT / "examples" / "agentgit.example.json").read_text())
    up = cfg["upstreams"][0]
    up["command"][1], up["env"]["FAKE_CAL_FILE"] = str(CAL), str(Path(h) / "fakecal.json")
    cfg["policy"].update(policy)
    (Path(h) / "agentgit.json").write_text(json.dumps(cfg))
    (Path(h) / "fakecal.json").write_text(json.dumps([
        {"id": "e1", "title": "study block", "start": "2026-11-25T18:00"}, {"id": "e2", "title": "gym", "start": "2026-11-26T07:00"}]))


class Base(unittest.TestCase):
    policy = {}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["AGENTGIT_HOME"] = self.tmp.name
        os.environ.pop("AGENTGIT_CONFIG", None)
        seed()
        write_config(self.tmp.name, **self.policy)
        self.eng = make_engine("test-agent")
        self.before = self.eng.reg.state_hash()

    def tearDown(self):
        self.eng.reg.close(); self.eng.close(); self.tmp.cleanup()

    def cal(self):
        return json.loads((Path(self.tmp.name) / "fakecal.json").read_text())


class TestUpstream(Base):
    def test_classification(self):
        r = self.eng.reg
        self.assertEqual(r.effect("cal_list_events"), "read")        # readOnlyHint
        self.assertEqual(r.effect("cal_add_event"), "reversible")    # undo declared in config
        self.assertEqual(r.effect("cal_send_invite"), "irreversible")  # no undo declared
        self.assertEqual(r.effect("cal_nope"), "irreversible")
        with self.assertRaises(AdapterError):
            self.eng.stage("cal_nope", {})

    def test_stage_changes_nothing_and_preview_is_readable(self):
        self.eng.stage("cal_delete_event", {"event_id": "e1"})
        self.assertEqual(len(self.cal()), 2)
        self.assertIn("Delete event 'study block' (2026-11-25T18:00)", self.eng.diff())

    def test_commit_verify_revert_restores_exact_event(self):
        self.eng.stage("cal_add_event", {"title": "Maths exam", "start": "2026-12-10T10:00"})
        self.eng.stage("cal_delete_event", {"event_id": "e1"})
        bid = self.eng.commit()["batch"]
        titles = [e["title"] for e in self.cal()]
        self.assertIn("Maths exam", titles); self.assertNotIn("study block", titles)
        self.assertTrue(self.eng.revert(bid)["ok"])
        self.assertEqual(self.eng.reg.state_hash(), self.before)
        self.assertIn({"id": "e1", "title": "study block", "start": "2026-11-25T18:00"}, self.cal())

    def test_failure_at_every_step_rolls_back_upstream(self):
        for k in (1, 2, 3):
            with self.subTest(step=k):
                self.eng.stage("cal_add_event", {"title": "A", "start": "2026-12-01T10:00"})
                self.eng.stage("cal_add_event", {"title": "B", "start": "2026-12-02T10:00"})
                self.eng.stage("cal_delete_event", {"event_id": "e2"})
                self.assertTrue(self.eng.commit(fail_at=k)["rolled_back"])
                self.assertEqual(self.eng.reg.state_hash(), self.before)

    def test_irreversible_upstream_needs_confirmation(self):
        self.eng.stage("cal_send_invite", {"event_id": "e1", "to": "a@b.c"})
        self.assertFalse(self.eng.commit()["ok"])
        self.assertTrue(self.eng.commit(confirm_irreversible=True)["ok"])


class TestPolicy(Base):
    policy = {"max_actions_per_batch": 3, "max_deletes_per_batch": 1, "deny": ["cal_send_*"]}

    def test_deny_and_limits(self):
        with self.assertRaises(PolicyError):
            self.eng.stage("cal_send_invite", {"event_id": "e1", "to": "x"})
        self.eng.stage("cal_delete_event", {"event_id": "e1"})
        with self.assertRaises(PolicyError):
            self.eng.stage("cal_delete_event", {"event_id": "e2"})  # second delete exceeds the limit
        self.assertGreaterEqual(self.eng.stats()["summary"]["blocked"], 2)

    def test_risk_scores(self):
        self.eng.stage("cal_add_event", {"title": "x", "start": "2026-12-01T10:00"})
        self.eng.stage("cal_delete_event", {"event_id": "e1"})
        self.assertEqual(self.eng._batch(status="staging")["risk"], 1 + 3)


class TestAutopilot(Base):
    policy = {"auto_approve_max_risk": 1}

    def test_only_single_low_risk_reversible_actions_auto_commit(self):
        r = self.eng.stage("cal_add_event", {"title": "Nap", "start": "2026-12-01T13:00"})
        self.assertTrue(r["auto_committed"])
        self.assertIn("Nap", [e["title"] for e in self.cal()])
        r2 = self.eng.stage("cal_delete_event", {"event_id": "e1"})  # risk 3 > 1: waits for a human
        self.assertNotIn("auto_committed", r2)
        self.assertEqual(len(self.cal()), 3)


class TestAuditAndCapsules(Base):
    def test_chain_detects_tampering(self):
        self.eng.stage("cal_add_event", {"title": "x", "start": "2026-12-01T10:00"}); self.eng.commit()
        self.assertTrue(self.eng.verify_log()["ok"])
        self.eng.c.execute("UPDATE log SET detail='nothing to see' WHERE id=(SELECT MIN(id) FROM log)"); self.eng.c.commit()
        self.assertFalse(self.eng.verify_log()["ok"])

    def test_capsule_replays_without_an_llm_and_still_needs_approval(self):
        self.eng.stage("cal_add_event", {"title": "Weekly review", "start": "2026-12-06T17:00"})
        bid = self.eng.commit()["batch"]
        self.assertTrue(self.eng.save_capsule(bid, "weekly")["ok"])
        self.eng.revert(bid)
        self.assertEqual(self.eng.run_capsule("weekly")["staged"], 1)
        self.assertEqual(self.eng.reg.state_hash(), self.before)       # staged only
        self.assertTrue(self.eng.commit()["ok"])
        self.assertIn("Weekly review", [e["title"] for e in self.cal()])


class TestGatewayProtocol(Base):
    """Talks to the gateway exactly like an MCP client would: JSON-RPC over stdio."""

    def test_any_client_can_connect(self):
        env = dict(os.environ)
        p = subprocess.Popen([sys.executable, "-m", "agentgit.gateway"], cwd=ROOT, env=env, text=True,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        out = queue.Queue()
        threading.Thread(target=lambda: [out.put(l) for l in p.stdout], daemon=True).start()

        def rpc(i, method, params=None):
            p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": i, "method": method, "params": params or {}}) + "\n"); p.stdin.flush()
            return json.loads(out.get(timeout=20))
        try:
            init = rpc(1, "initialize", {"protocolVersion": "2025-06-18", "clientInfo": {"name": "some-other-agent"}})
            self.assertEqual(init["result"]["serverInfo"]["name"], "agentgit-gateway")
            p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"); p.stdin.flush()
            names = [t["name"] for t in rpc(2, "tools/list")["result"]["tools"]]
            self.assertIn("cal_add_event", names); self.assertIn("move_file", names); self.assertNotIn("commit", names)
            r = rpc(3, "tools/call", {"name": "cal_list_events", "arguments": {}})["result"]
            self.assertIn("study block", r["content"][0]["text"])
            w = rpc(4, "tools/call", {"name": "cal_delete_event", "arguments": {"event_id": "e1"}})["result"]
            self.assertIn("STAGED, NOT EXECUTED", w["content"][0]["text"])
            self.assertEqual(len(self.cal()), 2)                       # upstream untouched
            self.assertIn("error", rpc(5, "bogus/method"))
            self.assertTrue(rpc(6, "tools/call", {"name": "cal_nope", "arguments": {}})["result"]["isError"])
        finally:
            p.stdin.close(); p.wait(timeout=10)
        row = connect().execute("SELECT agent FROM batches ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(row["agent"], "some-other-agent")              # the agent is identified from MCP clientInfo
        self.assertTrue(self.eng.commit()["ok"])                        # the human then approves from another process
        self.assertEqual(len(self.cal()), 1)


class TestHttpApi(Base):
    def setUp(self):
        super().setUp()
        from agentgit.server import make_server
        self.srv = make_server("127.0.0.1", 0, "ADMIN", "AGENT")
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown(); self.srv.reg.close(); super().tearDown()

    def http(self, method, path, body=None, token=None):
        req = urllib.request.Request(self.url + path, method=method, data=json.dumps(body).encode() if body is not None else None)
        if token:
            req.add_header("Authorization", "Bearer " + token)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, json.loads(r.read() or b"{}") if "json" in r.headers.get("Content-Type", "") else r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, None

    def test_roles_and_full_flow(self):
        self.assertEqual(self.http("GET", "/api/v1/tools")[0], 401)
        code, tools = self.http("GET", "/api/v1/tools?format=openai", token="AGENT")
        self.assertEqual(code, 200); self.assertEqual(tools[0]["type"], "function")
        self.assertEqual(self.http("GET", "/api/v1/tools?format=anthropic", token="AGENT")[1][0].keys() >= {"name", "input_schema"}, True)
        code, r = self.http("POST", "/api/v1/call", {"agent": "gpt-agent", "tool": "cal_add_event", "args": {"title": "Demo", "start": "2026-12-03T10:00"}}, "AGENT")
        self.assertIn("STAGED", r["message"])
        self.assertEqual(self.http("POST", "/api/v1/approve", {}, "AGENT")[0], 403)   # an agent can never approve
        self.assertEqual(self.http("GET", "/api/v1/stats", token="AGENT")[0], 403)
        self.assertEqual(len(self.cal()), 2)
        code, r = self.http("POST", "/api/v1/approve", {"fail_at": 1}, "ADMIN")
        self.assertTrue(r["rolled_back"]); self.assertEqual(len(self.cal()), 2)
        self.http("POST", "/api/v1/call", {"agent": "gpt-agent", "tool": "cal_add_event", "args": {"title": "Demo", "start": "2026-12-03T10:00"}}, "AGENT")
        code, r = self.http("POST", "/api/v1/approve", {}, "ADMIN")
        self.assertTrue(r["ok"]); self.assertEqual(len(self.cal()), 3)
        s = self.http("GET", "/api/v1/stats", token="ADMIN")[1]
        self.assertEqual(s["summary"]["committed"], 1); self.assertEqual(s["agents"][0]["agent"], "gpt-agent")
        self.assertTrue(self.http("GET", "/api/v1/log", token="ADMIN")[1]["chain"]["ok"])
        self.assertIn("Git for Agent Actions", self.http("GET", "/", token="ADMIN")[1])


if __name__ == "__main__":
    unittest.main()
