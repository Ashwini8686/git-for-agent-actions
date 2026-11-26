"""Tests for the floating-panel request parser and the provider cards."""
import unittest

from agentgit.ask import parse
from agentgit.server import connections


class TestAsk(unittest.TestCase):
    def test_phrases(self):
        self.assertEqual(parse("move maths_notes.pdf to Study"), ("move_file", {"src": "maths_notes.pdf", "dst": "Study/"}))
        self.assertEqual(parse("Delete file todo.txt"), ("delete_file", {"path": "todo.txt"}))
        self.assertEqual(parse("delete event ev_gym"), ("delete_event", {"event_id": "ev_gym"}))
        self.assertEqual(parse("add event Maths exam at 2026-12-10 10:00"), ("add_event", {"title": "Maths exam", "start": "2026-12-10T10:00"}))

    def test_unknown_sentence_is_refused(self):
        self.assertIsNone(parse("wipe everything"))
        self.assertIsNone(parse(""))


class TestConnections(unittest.TestCase):
    def test_grouping(self):
        a = [{"agent": "claude-desktop", "batches": 2, "actions": 5, "committed": 1, "failed": 1}, {"agent": "my-bot", "batches": 1, "actions": 1, "committed": 1, "failed": 0}]
        c = {p["id"]: p for p in connections(a)}
        self.assertEqual((c["claude"]["status"], c["claude"]["batches"]), ("active", 2))
        self.assertEqual(c["custom"]["agents"], ["my-bot"])
        self.assertEqual(c["openai"]["status"], "waiting")


if __name__ == "__main__":
    unittest.main()
