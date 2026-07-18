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

    def test_radio_stations_can_be_added_selected_and_removed(self):
        first = self.store.add_radio_station("Quiet FM", "https://radio.example/live.mp3")
        second = self.store.add_radio_station("Night FM", "http://night.example:8000/stream")
        loaded = self.store.load()
        self.assertEqual(loaded["radio_station_id"], first["id"])
        self.assertEqual(len(loaded["radio_stations"]), 2)
        updated = self.store.update({
            "music_source": "radio",
            "radio_mode": "random_locked",
            "radio_station_id": second["id"],
        })
        self.assertEqual(updated["music_source"], "radio")
        self.assertEqual(updated["radio_mode"], "random_locked")
        self.assertEqual(updated["radio_station_id"], second["id"])
        self.store.remove_radio_station(second["id"])
        self.assertEqual(self.store.load()["radio_station_id"], first["id"])
        self.store.remove_radio_station(first["id"])
        self.assertEqual(self.store.load()["music_source"], "builtin")

    def test_radio_station_name_defaults_to_host(self):
        station = self.store.add_radio_station("", "https://radio.example/live")
        self.assertEqual(station["name"], "radio.example")

    def test_rejects_invalid_or_duplicate_radio_urls(self):
        invalid = [
            "javascript:alert(1)",
            "file:///tmp/audio.mp3",
            "https://user:pass@example.com/live",
            "https://example.com/live\x00.mp3",
        ]
        for url in invalid:
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.store.add_radio_station("Bad", url)
        self.store.add_radio_station("One", "https://radio.example/live")
        with self.assertRaises(ValueError):
            self.store.add_radio_station("Duplicate", "https://radio.example/live")

    def test_invalid_radio_setting_values_are_ignored(self):
        station = self.store.add_radio_station("One", "https://radio.example/live")
        updated = self.store.update({
            "radio_mode": "anything",
            "radio_station_id": "missing",
            "music_source": "web-page",
        })
        self.assertEqual(updated["radio_mode"], "selectable")
        self.assertEqual(updated["radio_station_id"], station["id"])
        self.assertEqual(updated["music_source"], "builtin")


if __name__ == "__main__":
    unittest.main()
