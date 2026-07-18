import unittest
from unittest.mock import patch

from codex_rest.state import RestState


def payload(session="s1", turn="t1"):
    return {"session_id": session, "turn_id": turn}


class RestStateTests(unittest.TestCase):
    @patch("codex_rest.state.time.time", return_value=100.0)
    def test_start_and_stop(self, _time):
        state = RestState()
        self.assertEqual(state.handle("UserPromptSubmit", payload()), ["open"])
        self.assertEqual(state.snapshot()["active_count"], 1)
        self.assertEqual(state.started_at, 100.0)
        self.assertEqual(state.handle("Stop", payload()), ["finish"])
        self.assertEqual(state.phase, "finishing")

    def test_duplicate_start_is_idempotent(self):
        state = RestState()
        state.handle("UserPromptSubmit", payload())
        state.handle("UserPromptSubmit", payload())
        self.assertEqual(len(state.tasks), 1)

    def test_multiple_tasks_share_window_until_last_stop(self):
        state = RestState()
        state.handle("UserPromptSubmit", payload("s1", "t1"))
        state.handle("UserPromptSubmit", payload("s2", "t2"))
        self.assertNotIn("finish", state.handle("Stop", payload("s1", "t1")))
        self.assertEqual(state.handle("Stop", payload("s2", "t2")), ["finish"])

    def test_permission_pause_and_resume(self):
        state = RestState()
        state.handle("UserPromptSubmit", payload())
        self.assertEqual(state.handle("PermissionRequest", payload()), ["close"])
        self.assertEqual(state.phase, "paused")
        self.assertEqual(state.handle("PostToolUse", payload()), ["open"])
        self.assertEqual(state.phase, "active")

    def test_one_paused_task_hides_shared_window(self):
        state = RestState()
        state.handle("UserPromptSubmit", payload("a", "1"))
        state.handle("UserPromptSubmit", payload("b", "2"))
        state.handle("PermissionRequest", payload("a", "1"))
        self.assertFalse(state.should_display)
        self.assertEqual(state.handle("PostToolUse", payload("b", "2")), [])
        self.assertFalse(state.should_display)

    def test_manual_close_suppressed_until_new_prompt(self):
        state = RestState()
        state.handle("UserPromptSubmit", payload())
        state.manual_close()
        self.assertFalse(state.should_display)
        self.assertEqual(state.handle("PostToolUse", payload()), [])
        self.assertEqual(state.handle("UserPromptSubmit", payload("s2", "t2")), ["open"])

    def test_stale_finish_cannot_close_new_task(self):
        state = RestState()
        state.handle("UserPromptSubmit", payload())
        state.handle("Stop", payload())
        old_generation = state.generation
        state.handle("UserPromptSubmit", payload("new", "turn"))
        self.assertFalse(state.finish_complete(old_generation))


if __name__ == "__main__":
    unittest.main()
