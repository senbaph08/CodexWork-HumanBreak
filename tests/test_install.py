import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_rest.install import merge_hooks
from codex_rest.paths import wrapper_path


class HookMergeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.wrapper = Path(self.temporary.name) / "codex-rest"
        self.environment = patch.dict(os.environ, {"CODEX_REST_WRAPPER": str(self.wrapper)})
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temporary.cleanup()

    def test_merge_preserves_existing_hooks(self):
        existing = {
            "description": "mine",
            "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo existing"}]}]},
        }
        merged = merge_hooks(existing)
        self.assertEqual(merged["description"], "mine")
        commands = [
            handler["command"] for group in merged["hooks"]["Stop"]
            for handler in group["hooks"]
        ]
        self.assertIn("echo existing", commands)
        self.assertIn(str(wrapper_path()) + " hook", commands)

    def test_merge_is_idempotent(self):
        merged = merge_hooks(merge_hooks({}))
        command = str(wrapper_path()) + " hook"
        count = sum(
            1 for groups in merged["hooks"].values() for group in groups
            for handler in group["hooks"] if handler["command"] == command
        )
        self.assertEqual(count, 4)

    def test_remove_only_ours(self):
        merged = merge_hooks({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo existing"}]}]}})
        cleaned = merge_hooks(merged, remove=True)
        self.assertEqual(cleaned["hooks"]["Stop"][0]["hooks"][0]["command"], "echo existing")
        self.assertNotIn("UserPromptSubmit", cleaned["hooks"])


if __name__ == "__main__":
    unittest.main()
