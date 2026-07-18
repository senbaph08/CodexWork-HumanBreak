import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

from .paths import runtime_path


def read_runtime():
    try:
        data = json.loads(runtime_path().read_text(encoding="utf-8"))
        os.kill(int(data["pid"]), 0)
        return data
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return None


def request(path, method="GET", data=None, timeout=3, ensure=True):
    runtime = read_runtime()
    if runtime is None and ensure:
        ensure_daemon()
        runtime = read_runtime()
    if runtime is None:
        raise RuntimeError("Codex Rest daemon is unavailable")
    body = None if data is None else json.dumps(data).encode("utf-8")
    target = "http://127.0.0.1:{}{}".format(runtime["port"], path)
    req = urllib.request.Request(target, data=body, method=method)
    req.add_header("X-Codex-Rest-Token", runtime["token"])
    if body is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def ensure_daemon():
    if read_runtime() is not None:
        return
    subprocess.Popen(
        [sys.executable, "-m", "codex_rest.cli", "daemon"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )
    deadline = time.time() + 4.0
    while time.time() < deadline:
        if read_runtime() is not None:
            return
        time.sleep(0.05)
    raise RuntimeError("Codex Rest daemon did not start")


def hook(payload):
    request("/api/hook", method="POST", data=payload, timeout=4)
