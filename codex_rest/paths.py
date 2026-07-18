import os
from pathlib import Path


APP_NAME = "Codex Rest"


def app_home():
    override = os.environ.get("CODEX_REST_HOME")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / "Library" / "Application Support" / APP_NAME


def runtime_dir():
    return app_home() / "run"


def media_dir():
    return app_home() / "media"


def chrome_profile_dir():
    return app_home() / "chrome-profile"


def config_path():
    return app_home() / "config.json"


def runtime_path():
    return runtime_dir() / "runtime.json"


def log_path():
    return app_home() / "codex-rest.log"


def installed_runtime_dir():
    return app_home() / "runtime"


def wrapper_path():
    override = os.environ.get("CODEX_REST_WRAPPER")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".local" / "bin" / "codex-rest"


def hooks_path():
    codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    return codex_home.expanduser() / "hooks.json"


def chrome_path():
    return Path(os.environ.get(
        "CODEX_REST_CHROME",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ))


def web_dir():
    return Path(__file__).resolve().parent / "web"
