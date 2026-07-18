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

    def test_new_turn_replaces_stale_turn_in_same_session(self):
        state = RestState()
        state.handle("UserPromptSubmit", payload("same-session", "old-turn"))
        state.handle("UserPromptSubmit", payload("same-session", "new-turn"))
        self.assertEqual(len(state.tasks), 1)
        self.assertNotIn("same-session:old-turn", state.tasks)
        self.assertIn("same-session:new-turn", state.tasks)

    def test_new_turn_keeps_tasks_from_other_sessions(self):
        state = RestState()
        state.handle("UserPromptSubmit", payload("session-a", "turn-1"))
        state.handle("UserPromptSubmit", payload("session-b", "turn-1"))
        state.handle("UserPromptSubmit", payload("session-a", "turn-2"))
        self.assertEqual(len(state.tasks), 2)
        self.assertIn("session-b:turn-1", state.tasks)

    def test_reset_clears_tasks_without_finishing(self):
        state = RestState()
        state.handle("UserPromptSubmit", payload())
        actions, cleared_count = state.reset()
        self.assertEqual(actions, ["close"])
        self.assertEqual(cleared_count, 1)
        self.assertEqual(state.phase, "idle")
        self.assertIsNone(state.started_at)
        self.assertEqual(state.snapshot()["active_count"], 0)

    def test_delayed_stop_after_reset_is_ignored(self):
        state = RestState()
        state.handle("UserPromptSubmit", payload())
        state.reset()
        self.assertEqual(state.handle("Stop", payload()), [])
        self.assertEqual(state.phase, "idle")


if __name__ == "__main__":
    unittest.main()
