import json
import os
import tempfile
import threading
import uuid
from pathlib import Path

from .paths import app_home, config_path, media_dir


DEFAULT_CONFIG = {
    "music_enabled": True,
    "completion_sound_enabled": True,
    "music_volume": 0.30,
    "completion_volume": 0.45,
    "music_source": "builtin",
    "playlist_order": "sequential",
    "tracks": [],
}

ALLOWED_EXTENSIONS = {".mp3", ".m4a", ".aac", ".wav", ".ogg", ".flac"}
MAX_TRACK_BYTES = 250 * 1024 * 1024


class ConfigStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else config_path()
        self.lock = threading.RLock()

    def load(self):
        with self.lock:
            data = dict(DEFAULT_CONFIG)
            try:
                with self.path.open("r", encoding="utf-8") as handle:
                    loaded = json.load(handle)
                if isinstance(loaded, dict):
                    data.update(loaded)
            except (FileNotFoundError, json.JSONDecodeError, OSError):
                pass
            data["tracks"] = [t for t in data.get("tracks", []) if isinstance(t, dict)]
            return data

    def save(self, data):
        with self.lock:
            app_home().mkdir(parents=True, exist_ok=True)
            merged = dict(DEFAULT_CONFIG)
            merged.update(data)
            fd, tmp_name = tempfile.mkstemp(prefix="config-", suffix=".json", dir=str(self.path.parent))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(merged, handle, ensure_ascii=False, indent=2)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.chmod(tmp_name, 0o600)
                os.replace(tmp_name, self.path)
            finally:
                if os.path.exists(tmp_name):
                    os.unlink(tmp_name)
            return merged

    def update(self, changes):
        allowed = {
            "music_enabled", "completion_sound_enabled", "music_volume",
            "completion_volume", "music_source", "playlist_order",
        }
        clean = {key: value for key, value in changes.items() if key in allowed}
        for key in ("music_enabled", "completion_sound_enabled"):
            if key in clean:
                clean[key] = bool(clean[key])
        for key in ("music_volume", "completion_volume"):
            if key in clean:
                clean[key] = max(0.0, min(1.0, float(clean[key])))
        if clean.get("music_source") not in (None, "builtin", "playlist"):
            clean.pop("music_source", None)
        if clean.get("playlist_order") not in (None, "sequential", "shuffle"):
            clean.pop("playlist_order", None)
        data = self.load()
        data.update(clean)
        return self.save(data)

    def add_track(self, original_name, payload):
        suffix = Path(original_name).suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            raise ValueError("対応していない音声形式です")
        if len(payload) > MAX_TRACK_BYTES:
            raise ValueError("音源ファイルは250MB以下にしてください")
        media_dir().mkdir(parents=True, exist_ok=True)
        track_id = uuid.uuid4().hex
        target = media_dir() / (track_id + suffix)
        with target.open("wb") as handle:
            handle.write(payload)
        os.chmod(target, 0o600)
        data = self.load()
        track = {"id": track_id, "name": Path(original_name).name, "file": target.name}
        data["tracks"].append(track)
        self.save(data)
        return track

    def remove_track(self, track_id):
        data = self.load()
        kept = []
        removed = None
        for track in data["tracks"]:
            if track.get("id") == track_id and removed is None:
                removed = track
            else:
                kept.append(track)
        if removed:
            candidate = media_dir() / Path(removed.get("file", "")).name
            try:
                candidate.unlink()
            except FileNotFoundError:
                pass
            data["tracks"] = kept
            if not kept and data.get("music_source") == "playlist":
                data["music_source"] = "builtin"
            self.save(data)
        return removed

    def track_path(self, track_id):
        for track in self.load()["tracks"]:
            if track.get("id") == track_id:
                candidate = media_dir() / Path(track.get("file", "")).name
                try:
                    resolved = candidate.resolve()
                    resolved.relative_to(media_dir().resolve())
                except (ValueError, OSError):
                    return None
                return resolved if resolved.is_file() else None
        return None
