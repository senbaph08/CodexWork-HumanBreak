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

    def handle(self, event_name, payload):
        key = self.task_key(payload)
        actions = []

        if event_name == "UserPromptSubmit":
            was_empty = not self.tasks
            self.tasks[key] = {"paused": False}
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
            self.tasks.pop(key, None)
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
