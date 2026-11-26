import os
import tempfile
import unittest

from agentgit.adapters import AdapterError
from agentgit.engine import Crash, make_engine
from agentgit.seed import WORKFLOW, seed


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["AGENTGIT_HOME"] = self.tmp.name
        seed()
        self.eng = make_engine()
        self.before = self.eng.reg.state_hash()

    def tearDown(self):
        self.eng.close(); self.tmp.cleanup()

    def stage_all(self):
        for t, a in WORKFLOW:
            self.eng.stage(t, a)


class TestEngine(Base):
    def test_staging_changes_nothing(self):
        self.stage_all()
        self.assertEqual(self.eng.reg.state_hash(), self.before)
        self.assertIn("Move 'maths_notes.pdf'", self.eng.diff())

    def test_commit_applies_and_verifies(self):
        self.stage_all()
        r = self.eng.commit()
        self.assertTrue(r["ok"] and r["verified"])
        self.assertNotEqual(self.eng.reg.state_hash(), self.before)

    def test_failure_at_every_step_rolls_back_exactly(self):
        for k in range(1, len(WORKFLOW) + 1):
            with self.subTest(step=k):
                seed(); self.eng.close(); self.eng = make_engine(); before = self.eng.reg.state_hash()
                self.stage_all()
                r = self.eng.commit(fail_at=k)
                self.assertFalse(r["ok"]); self.assertTrue(r["rolled_back"])
                self.assertEqual(self.eng.reg.state_hash(), before)

    def test_crash_then_recover(self):
        self.stage_all()
        with self.assertRaises(Crash):
            self.eng.commit(crash_at=5)
        self.assertNotEqual(self.eng.reg.state_hash(), self.before)  # partial changes are live
        self.eng.recover()
        self.assertEqual(self.eng.reg.state_hash(), self.before)

    def test_revert_restores_exact_state(self):
        self.stage_all(); bid = self.eng.commit()["batch"]
        self.assertTrue(self.eng.revert(bid)["ok"])
        self.assertEqual(self.eng.reg.state_hash(), self.before)

    def test_commit_twice_is_idempotent(self):
        self.stage_all(); self.eng.commit(); after = self.eng.reg.state_hash()
        self.assertFalse(self.eng.commit()["ok"])
        self.assertEqual(self.eng.reg.state_hash(), after)

    def test_irreversible_needs_confirmation_and_runs_last(self):
        self.eng.stage("send_email", {"to": "prof@x.edu", "subject": "Late", "body": "hi"})
        self.eng.stage("move_file", {"src": "todo.txt", "dst": "Study/"})
        self.assertFalse(self.eng.commit()["ok"])
        self.assertTrue(self.eng.commit(confirm_irreversible=True)["ok"])
        d = self.eng.diff(1).splitlines()
        self.assertIn("[reversible]", d[1]); self.assertIn("[irreversible]", d[2])

    def test_stale_state_is_refused(self):
        self.stage_all()
        self.eng.reg.adapters[0].apply("delete_file", {"path": "holiday.jpg"})  # data changes behind our back
        r = self.eng.commit()
        self.assertTrue(r.get("stale"))

    def test_reject_discards(self):
        self.stage_all(); self.assertTrue(self.eng.reject()["ok"])
        self.assertEqual(self.eng.reg.state_hash(), self.before)

    def test_unknown_tool_and_path_escape(self):
        self.assertEqual(self.eng.reg.effect("rm_rf"), "irreversible")
        with self.assertRaises(AdapterError):
            self.eng.stage("rm_rf", {})
        with self.assertRaises(AdapterError):
            self.eng.stage("list_files", {"folder": "../.."})
        self.eng.stage("move_file", {"src": "../x", "dst": "a/"})
        self.assertFalse(self.eng.commit()["ok"])


if __name__ == "__main__":
    unittest.main()
