import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_rest.config import ConfigStore


class ConfigStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name)
        self.environment = patch.dict(os.environ, {"CODEX_REST_HOME": str(self.home)})
        self.environment.start()
        self.store = ConfigStore(self.home / "config.json")

    def tearDown(self):
        self.environment.stop()
        self.temporary.cleanup()

    def test_defaults_and_clamping(self):
        defaults = self.store.load()
        self.assertTrue(defaults["music_enabled"])
        updated = self.store.update({"music_volume": 4, "completion_volume": -1})
        self.assertEqual(updated["music_volume"], 1.0)
        self.assertEqual(updated["completion_volume"], 0.0)

    def test_unknown_settings_are_ignored(self):
        updated = self.store.update({"prompt": "must not persist", "music_enabled": False})
        self.assertNotIn("prompt", updated)
        self.assertFalse(updated["music_enabled"])

    def test_tracks_are_copied_and_removed(self):
        track = self.store.add_track("quiet.mp3", b"audio-data")
        path = self.store.track_path(track["id"])
        self.assertEqual(path.read_bytes(), b"audio-data")
        self.assertTrue(self.store.remove_track(track["id"]))
        self.assertFalse(path.exists())

    def test_rejects_unsupported_track(self):
        with self.assertRaises(ValueError):
            self.store.add_track("script.html", b"bad")


if __name__ == "__main__":
    unittest.main()
