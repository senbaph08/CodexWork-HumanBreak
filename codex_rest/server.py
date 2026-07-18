import json
import logging
import math
import mimetypes
import os
import secrets
import signal
import struct
import subprocess
import threading
import time
import urllib.parse
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import ConfigStore, MAX_TRACK_BYTES
from .paths import (
    app_home, chrome_path, chrome_profile_dir, log_path, runtime_dir,
    runtime_path, web_dir,
)
from .state import RestState


LOGGER = logging.getLogger("codex-rest")


def _atomic_json(path, data, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-" + secrets.token_hex(4))
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(data, handle)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def create_chime(path):
    """Generate a soft, original three-note completion chime."""
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    rate = 44100
    duration = 1.45
    notes = [(523.25, 0.00), (659.25, 0.28), (783.99, 0.56)]
    frames = []
    for index in range(int(rate * duration)):
        t = index / rate
        sample = 0.0
        for frequency, start in notes:
            local = t - start
            if 0 <= local <= 0.86:
                attack = min(1.0, local / 0.035)
                decay = math.exp(-3.2 * local)
                tone = math.sin(2 * math.pi * frequency * local)
                tone += 0.18 * math.sin(2 * math.pi * frequency * 2 * local)
                sample += 0.22 * attack * decay * tone
        sample = max(-0.85, min(0.85, sample))
        frames.append(struct.pack("<h", int(sample * 32767)))
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(b"".join(frames))
    os.chmod(path, 0o600)
    return path


def should_play_completion_chime(config):
    return not bool(config.get("music_enabled")) and bool(config.get("completion_sound_enabled"))


class RestController:
    def __init__(self, config=None, browser_launcher=None):
        self.config = config or ConfigStore()
        self.state = RestState()
        self.lock = threading.RLock()
        self.browser = None
        self.browser_launcher = browser_launcher or self._launch_chrome
        self.port = None
        self.token = secrets.token_urlsafe(32)
        self.shutdown_event = threading.Event()
        self.server = None

    def handle_hook(self, event_name, payload):
        with self.lock:
            actions = self.state.handle(event_name, payload)
            generation = self.state.generation
        self._apply(actions, generation)

    def manual_close(self):
        with self.lock:
            actions = self.state.manual_close()
        self._apply(actions, self.state.generation)

    def reset_state(self):
        with self.lock:
            actions, cleared_count = self.state.reset()
            generation = self.state.generation
        self._apply(actions, generation)
        return cleared_count

    def _apply(self, actions, generation):
        for action in actions:
            if action == "open":
                self.ensure_browser()
            elif action == "close":
                self.close_browser()
            elif action == "finish":
                threading.Thread(
                    target=self._finish, args=(generation,), name="codex-rest-finish", daemon=True
                ).start()

    def ensure_browser(self):
        with self.lock:
            if self.browser is not None and self.browser.poll() is None:
                return
            if not self.state.should_display or self.port is None:
                return
            try:
                self.browser = self.browser_launcher()
            except Exception:
                LOGGER.exception("Chrome could not be launched")
                self.browser = None

    def _launch_chrome(self):
        executable = chrome_path()
        if not executable.is_file():
            raise FileNotFoundError(str(executable))
        chrome_profile_dir().mkdir(parents=True, exist_ok=True)
        url = "http://127.0.0.1:{}/#{}".format(self.port, self.token)
        command = [
            str(executable),
            "--user-data-dir=" + str(chrome_profile_dir()),
            "--app=" + url,
            "--start-fullscreen",
            "--autoplay-policy=no-user-gesture-required",
            "--no-first-run",
            "--disable-session-crashed-bubble",
            "--disable-sync",
        ]
        return subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def close_browser(self):
        with self.lock:
            process = self.browser
            self.browser = None
        if process is None or process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
        except OSError:
            pass

    def _finish(self, generation):
        config = self.config.load()
        chime_duration = 0.0
        if should_play_completion_chime(config):
            chime_duration = self._play_completion_chime(config["completion_volume"])
        deadline = time.time() + max(1.5, chime_duration)
        while time.time() < deadline:
            time.sleep(0.05)
            with self.lock:
                if generation != self.state.generation or self.state.tasks:
                    return
        with self.lock:
            if not self.state.finish_complete(generation):
                return
        self.close_browser()

    @staticmethod
    def _play_completion_chime(volume):
        afplay = Path("/usr/bin/afplay")
        if not afplay.is_file():
            return 0.0
        chime = create_chime(app_home() / "completion-chime.wav")
        try:
            subprocess.Popen(
                [str(afplay), "-v", str(max(0.0, min(1.0, float(volume)))), str(chime)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return 1.45
        except OSError:
            LOGGER.exception("Completion chime could not be played")
            return 0.0

    def snapshot(self):
        with self.lock:
            state = self.state.snapshot()
            state["browser_open"] = self.browser is not None and self.browser.poll() is None
        config = self.config.load()
        state["settings"] = config
        return state

    def monitor_browser(self):
        while not self.shutdown_event.wait(0.5):
            with self.lock:
                process = self.browser
                if process is not None and process.poll() is not None:
                    self.browser = None
                    if self.state.tasks:
                        self.state.suppressed = True

    def stop(self):
        self.shutdown_event.set()
        self.close_browser()
        if self.server:
            threading.Thread(target=self.server.shutdown, daemon=True).start()


class RestHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, controller):
        self.controller = controller
        super().__init__(address, RestRequestHandler)


class RestRequestHandler(BaseHTTPRequestHandler):
    server_version = "CodexRest/1.0"

    @property
    def controller(self):
        return self.server.controller

    def log_message(self, fmt, *args):
        LOGGER.debug(fmt, *args)

    def _token(self):
        header = self.headers.get("X-Codex-Rest-Token", "")
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        supplied = header or (query.get("t", [""])[0])
        return secrets.compare_digest(supplied, self.controller.token)

    def _origin_ok(self):
        origin = self.headers.get("Origin")
        expected = "http://127.0.0.1:{}".format(self.server.server_port)
        return origin is None or origin == expected

    def _json(self, status, data):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _read_json(self, maximum=1024 * 1024):
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0 or length > maximum:
            raise ValueError("request too large")
        return json.loads(self.rfile.read(length).decode("utf-8") or "{}")

    def _authorized(self):
        if not self._token() or not self._origin_ok():
            self._json(403, {"error": "forbidden"})
            return False
        return True

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path == "/api/state":
            if not self._authorized():
                return
            self._json(200, self.controller.snapshot())
            return
        if path.startswith("/media/"):
            if not self._authorized():
                return
            self._serve_media(path.rsplit("/", 1)[-1])
            return
        self._serve_static(path)

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        if not self._authorized():
            return
        try:
            if path == "/api/hook":
                payload = self._read_json()
                event = str(payload.pop("hook_event_name", ""))
                if event not in {"UserPromptSubmit", "Stop", "PermissionRequest", "PostToolUse"}:
                    self._json(400, {"error": "unsupported hook event"})
                    return
                self.controller.handle_hook(event, payload)
                self._json(200, {"ok": True})
            elif path == "/api/settings":
                updated = self.controller.config.update(self._read_json())
                self._json(200, updated)
            elif path == "/api/close":
                self.controller.manual_close()
                self._json(200, {"ok": True})
            elif path == "/api/reset":
                cleared_count = self.controller.reset_state()
                self._json(200, {
                    "ok": True,
                    "cleared_count": cleared_count,
                    "state": self.controller.snapshot(),
                })
            elif path == "/api/tracks":
                self._upload_track()
            elif path == "/api/shutdown":
                self._json(200, {"ok": True})
                self.controller.stop()
            else:
                self._json(404, {"error": "not found"})
        except (ValueError, json.JSONDecodeError) as error:
            self._json(400, {"error": str(error)})
        except Exception:
            LOGGER.exception("Request failed")
            self._json(500, {"error": "internal error"})

    def do_DELETE(self):
        path = urllib.parse.urlsplit(self.path).path
        if not self._authorized():
            return
        if path.startswith("/api/tracks/"):
            track_id = path.rsplit("/", 1)[-1]
            removed = self.controller.config.remove_track(track_id)
            self._json(200 if removed else 404, {"removed": bool(removed)})
        else:
            self._json(404, {"error": "not found"})

    def _upload_track(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1 or length > MAX_TRACK_BYTES:
            raise ValueError("音源ファイルは250MB以下にしてください")
        encoded_name = self.headers.get("X-File-Name", "")
        name = urllib.parse.unquote(encoded_name)
        if not name:
            raise ValueError("file name is required")
        payload = self.rfile.read(length)
        track = self.controller.config.add_track(name, payload)
        self._json(201, track)

    def _serve_media(self, track_id):
        path = self.controller.config.track_path(track_id)
        if path is None:
            self.send_error(404)
            return
        size = path.stat().st_size
        start, end = 0, size - 1
        status = 200
        requested = self.headers.get("Range")
        if requested and requested.startswith("bytes="):
            try:
                first, last = requested[6:].split("-", 1)
                start = int(first) if first else 0
                end = int(last) if last else size - 1
                if start < 0 or end < start or start >= size:
                    raise ValueError
                end = min(end, size - 1)
                status = 206
            except ValueError:
                self.send_response(416)
                self.send_header("Content-Range", "bytes */{}".format(size))
                self.end_headers()
                return
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if status == 206:
            self.send_header("Content-Range", "bytes {}-{}/{}".format(start, end, size))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        with path.open("rb") as handle:
            handle.seek(start)
            remaining = end - start + 1
            while remaining:
                chunk = handle.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def _serve_static(self, path):
        mapping = {
            "/": "index.html",
            "/settings": "index.html",
            "/app.js": "app.js",
            "/styles.css": "styles.css",
        }
        filename = mapping.get(path)
        if not filename:
            self.send_error(404)
            return
        target = web_dir() / filename
        try:
            payload = target.read_bytes()
        except OSError:
            self.send_error(404)
            return
        content_type = {
            ".html": "text/html; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
        }[target.suffix]
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "media-src 'self' blob:; connect-src 'self'; img-src 'self' data:; "
            "object-src 'none'; frame-ancestors 'none'; base-uri 'none'",
        )
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(payload)


def run_server():
    app_home().mkdir(parents=True, exist_ok=True)
    runtime_dir().mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(log_path()),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    controller = RestController()
    server = RestHTTPServer(("127.0.0.1", 0), controller)
    controller.server = server
    controller.port = server.server_port
    _atomic_json(runtime_path(), {
        "pid": os.getpid(), "port": server.server_port, "token": controller.token,
    })
    monitor = threading.Thread(target=controller.monitor_browser, daemon=True)
    monitor.start()

    def stop_handler(_signum, _frame):
        controller.stop()

    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        controller.close_browser()
        try:
            current = json.loads(runtime_path().read_text(encoding="utf-8"))
            if current.get("pid") == os.getpid():
                runtime_path().unlink()
        except (OSError, json.JSONDecodeError):
            pass
        server.server_close()
