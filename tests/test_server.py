import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import wave
from pathlib import Path
from unittest.mock import patch

from codex_rest.config import ConfigStore
from codex_rest.server import (
    RestController, RestHTTPServer, create_chime, should_play_completion_chime,
)


class FakeProcess:
    def __init__(self):
        self.returncode = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.returncode = -9


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name)
        self.environment = patch.dict(os.environ, {"CODEX_REST_HOME": str(self.home)})
        self.environment.start()
        self.launched = []

        def launcher():
            process = FakeProcess()
            self.launched.append(process)
            return process

        self.controller = RestController(ConfigStore(self.home / "config.json"), launcher)
        self.controller.port = 12345

    def tearDown(self):
        self.controller.close_browser()
        self.environment.stop()
        self.temporary.cleanup()

    def test_single_browser_for_concurrent_tasks(self):
        self.controller.handle_hook("UserPromptSubmit", {"session_id": "a", "turn_id": "1"})
        self.controller.handle_hook("UserPromptSubmit", {"session_id": "b", "turn_id": "2"})
        self.assertEqual(len(self.launched), 1)

    def test_permission_closes_browser(self):
        payload = {"session_id": "a", "turn_id": "1"}
        self.controller.handle_hook("UserPromptSubmit", payload)
        process = self.launched[0]
        self.controller.handle_hook("PermissionRequest", payload)
        self.assertTrue(process.terminated)

    def test_reset_closes_browser_and_clears_tasks_without_chime(self):
        self.controller.handle_hook("UserPromptSubmit", {"session_id": "a", "turn_id": "1"})
        process = self.launched[0]
        with patch.object(self.controller, "_play_completion_chime") as play_chime:
            self.assertEqual(self.controller.reset_state(), 1)
        self.assertTrue(process.terminated)
        self.assertEqual(self.controller.snapshot()["active_count"], 0)
        self.assertEqual(self.controller.state.phase, "idle")
        play_chime.assert_not_called()

    def test_chime_is_valid_wave(self):
        target = self.home / "chime.wav"
        create_chime(target)
        with wave.open(str(target), "rb") as audio:
            self.assertEqual(audio.getframerate(), 44100)
            self.assertGreater(audio.getnframes(), 40000)

    def test_chime_only_plays_when_music_is_off_and_chime_is_on(self):
        cases = [
            (True, True, False),
            (True, False, False),
            (False, False, False),
            (False, True, True),
        ]
        for music, chime, expected in cases:
            with self.subTest(music=music, chime=chime):
                self.assertEqual(should_play_completion_chime({
                    "music_enabled": music,
                    "completion_sound_enabled": chime,
                }), expected)


class HTTPServerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name)
        self.environment = patch.dict(os.environ, {"CODEX_REST_HOME": str(self.home)})
        self.environment.start()
        self.controller = RestController(ConfigStore(self.home / "config.json"), lambda: FakeProcess())
        self.server = RestHTTPServer(("127.0.0.1", 0), self.controller)
        self.controller.server = self.server
        self.controller.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.environment.stop()
        self.temporary.cleanup()

    def request(self, path, token=True, method="GET", body=None, headers=None):
        request = urllib.request.Request(
            "http://127.0.0.1:{}{}".format(self.server.server_port, path),
            data=body,
            method=method,
            headers=headers or {},
        )
        if token:
            request.add_header("X-Codex-Rest-Token", self.controller.token)
        return urllib.request.urlopen(request, timeout=2)

    def test_state_requires_token(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/api/state", token=False)
        self.assertEqual(caught.exception.code, 403)
        with self.request("/api/state") as response:
            self.assertEqual(response.status, 200)

    def test_wrong_origin_is_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/api/settings", method="POST", body=b"{}", headers={"Origin": "https://example.com"})
        self.assertEqual(caught.exception.code, 403)

    def test_reset_endpoint_clears_active_tasks(self):
        self.controller.handle_hook("UserPromptSubmit", {"session_id": "a", "turn_id": "1"})
        with self.request("/api/reset", method="POST", body=b"{}") as response:
            result = __import__("json").loads(response.read().decode("utf-8"))
        self.assertEqual(result["cleared_count"], 1)
        self.assertEqual(result["state"]["active_count"], 0)

    def test_settings_page_contains_reset_control(self):
        with self.request("/settings", token=False) as response:
            page = response.read().decode("utf-8")
        self.assertIn('id="resetTaskState"', page)
        self.assertIn("状態をリセット", page)

    def test_track_upload_and_byte_range(self):
        with self.request(
            "/api/tracks", method="POST", body=b"0123456789",
            headers={"X-File-Name": "sample.mp3"},
        ) as response:
            track = __import__("json").loads(response.read().decode("utf-8"))
        with self.request(
            "/media/{}?t={}".format(track["id"], self.controller.token),
            token=False,
            headers={"Range": "bytes=2-5"},
        ) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.read(), b"2345")


if __name__ == "__main__":
    unittest.main()
