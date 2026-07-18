import json
import os
import tempfile
import threading
import urllib.parse
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
    "radio_mode": "selectable",
    "radio_station_id": None,
    "radio_stations": [],
}

ALLOWED_EXTENSIONS = {".mp3", ".m4a", ".aac", ".wav", ".ogg", ".flac"}
MAX_TRACK_BYTES = 250 * 1024 * 1024
MAX_RADIO_NAME_LENGTH = 120
MAX_RADIO_URL_LENGTH = 2048


def normalize_radio_url(value):
    url = str(value or "").strip()
    if not url or len(url) > MAX_RADIO_URL_LENGTH:
        raise ValueError("ラジオ局URLを入力してください")
    if any(ord(character) < 32 or ord(character) == 127 for character in url):
        raise ValueError("ラジオ局URLに制御文字は使用できません")
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("ラジオ局URLはhttp://またはhttps://で指定してください")
    if parsed.username or parsed.password:
        raise ValueError("認証情報を含むURLは登録できません")
    return url


def normalize_radio_name(value, url):
    name = str(value or "").strip()
    if not name:
        name = urllib.parse.urlsplit(url).hostname or "Internet Radio"
    if len(name) > MAX_RADIO_NAME_LENGTH:
        raise ValueError("ラジオ局名は120文字以下にしてください")
    return name


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
            stations = []
            for station in data.get("radio_stations", []):
                if not isinstance(station, dict) or not station.get("id"):
                    continue
                try:
                    url = normalize_radio_url(station.get("url"))
                    name = normalize_radio_name(station.get("name"), url)
                except ValueError:
                    continue
                stations.append({"id": str(station["id"]), "name": name, "url": url})
            data["radio_stations"] = stations
            station_ids = {station["id"] for station in stations}
            if data.get("radio_station_id") not in station_ids:
                data["radio_station_id"] = stations[0]["id"] if stations else None
            if data.get("radio_mode") not in {"selectable", "random_locked"}:
                data["radio_mode"] = "selectable"
            if data.get("music_source") not in {"builtin", "playlist", "radio"}:
                data["music_source"] = "builtin"
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
            "radio_mode", "radio_station_id",
        }
        clean = {key: value for key, value in changes.items() if key in allowed}
        for key in ("music_enabled", "completion_sound_enabled"):
            if key in clean:
                clean[key] = bool(clean[key])
        for key in ("music_volume", "completion_volume"):
            if key in clean:
                clean[key] = max(0.0, min(1.0, float(clean[key])))
        if clean.get("music_source") not in (None, "builtin", "playlist", "radio"):
            clean.pop("music_source", None)
        if clean.get("playlist_order") not in (None, "sequential", "shuffle"):
            clean.pop("playlist_order", None)
        data = self.load()
        if clean.get("radio_mode") not in (None, "selectable", "random_locked"):
            clean.pop("radio_mode", None)
        if "radio_station_id" in clean:
            station_ids = {station["id"] for station in data["radio_stations"]}
            if clean["radio_station_id"] not in station_ids:
                clean.pop("radio_station_id", None)
        data.update(clean)
        return self.save(data)

    def add_radio_station(self, name, url):
        clean_url = normalize_radio_url(url)
        clean_name = normalize_radio_name(name, clean_url)
        data = self.load()
        if any(station["url"] == clean_url for station in data["radio_stations"]):
            raise ValueError("このラジオ局URLは登録済みです")
        station = {"id": uuid.uuid4().hex, "name": clean_name, "url": clean_url}
        data["radio_stations"].append(station)
        if not data.get("radio_station_id"):
            data["radio_station_id"] = station["id"]
        self.save(data)
        return station

    def remove_radio_station(self, station_id):
        data = self.load()
        kept = [station for station in data["radio_stations"] if station["id"] != station_id]
        if len(kept) == len(data["radio_stations"]):
            return None
        removed = next(station for station in data["radio_stations"] if station["id"] == station_id)
        data["radio_stations"] = kept
        if data.get("radio_station_id") == station_id:
            data["radio_station_id"] = kept[0]["id"] if kept else None
        if not kept and data.get("music_source") == "radio":
            data["music_source"] = "builtin"
        self.save(data)
        return removed

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
