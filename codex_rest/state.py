import time


class RestState:
    """Pure state machine for Codex hook events."""

    def __init__(self):
        self.tasks = {}
        self.suppressed = False
        self.phase = "idle"
        self.started_at = None
        self.generation = 0

    @staticmethod
    def task_key(payload):
        session = str(payload.get("session_id") or "unknown-session")
        turn = str(payload.get("turn_id") or "unknown-turn")
        return session + ":" + turn

    @staticmethod
    def task_ids(payload):
        return (
            str(payload.get("session_id") or "unknown-session"),
            str(payload.get("turn_id") or "unknown-turn"),
        )

    def handle(self, event_name, payload):
        key = self.task_key(payload)
        actions = []

        if event_name == "UserPromptSubmit":
            session, turn = self.task_ids(payload)
            # A Codex session can only have one active turn. If Stop was lost
            # (for example because the thread was archived), a later turn in
            # that same session supersedes the stale entry.
            for stale_key, task in list(self.tasks.items()):
                if task["session_id"] == session and task["turn_id"] != turn:
                    self.tasks.pop(stale_key, None)
            was_empty = not self.tasks
            self.tasks[key] = {
                "paused": False,
                "session_id": session,
                "turn_id": turn,
            }
            self.suppressed = False
            self.generation += 1
            self.phase = "active"
            if was_empty:
                self.started_at = time.time()
            if self.should_display:
                actions.append("open")

        elif event_name == "PermissionRequest":
            if key in self.tasks:
                self.tasks[key]["paused"] = True
            if self.tasks:
                self.phase = "paused"
                actions.append("close")

        elif event_name == "PostToolUse":
            if key in self.tasks and self.tasks[key]["paused"]:
                self.tasks[key]["paused"] = False
            if self.tasks and not self.any_paused:
                self.phase = "active"
                if self.should_display:
                    actions.append("open")

        elif event_name == "Stop":
            removed = self.tasks.pop(key, None)
            # Ignore a delayed or duplicate Stop. In particular, it must not
            # produce a completion chime after the user has reset the state.
            if removed is None:
                return []
            if not self.tasks:
                self.generation += 1
                self.phase = "finishing"
                actions.append("finish")
            elif not self.any_paused:
                self.phase = "active"
                if self.should_display:
                    actions.append("open")

        return actions

    @property
    def any_paused(self):
        return any(task["paused"] for task in self.tasks.values())

    @property
    def should_display(self):
        return bool(self.tasks) and not self.any_paused and not self.suppressed

    def manual_close(self):
        self.suppressed = True
        return ["close"]

    def reset(self):
        """Forget all tracked work without treating it as task completion."""
        cleared_count = len(self.tasks)
        self.tasks.clear()
        self.suppressed = False
        self.phase = "idle"
        self.started_at = None
        self.generation += 1
        return ["close"], cleared_count

    def finish_complete(self, generation):
        if generation == self.generation and not self.tasks:
            self.phase = "idle"
            self.started_at = None
            return True
        return False

    def snapshot(self):
        return {
            "active_count": len(self.tasks),
            "paused_count": sum(1 for task in self.tasks.values() if task["paused"]),
            "suppressed": self.suppressed,
            "phase": self.phase,
            "started_at": self.started_at,
        }
