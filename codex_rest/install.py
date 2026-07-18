import json
import os
import shutil
import stat
import sys
import tempfile
import time
from pathlib import Path

from .paths import hooks_path, installed_runtime_dir, wrapper_path, app_home


EVENTS = {
    "UserPromptSubmit": "休憩画面を開始しています",
    "Stop": "休憩画面を終了しています",
    "PermissionRequest": "承認操作のため休憩画面を一時停止しています",
    "PostToolUse": "休憩画面を再開しています",
}


def hook_command():
    return str(wrapper_path()) + " hook"


def _is_ours(handler):
    return isinstance(handler, dict) and handler.get("command") == hook_command()


def merge_hooks(document, remove=False):
    if not isinstance(document, dict):
        document = {}
    hooks = document.setdefault("hooks", {})
    for event, status in EVENTS.items():
        groups = hooks.get(event, [])
        cleaned = []
        for group in groups if isinstance(groups, list) else []:
            handlers = group.get("hooks", []) if isinstance(group, dict) else []
            remaining = [handler for handler in handlers if not _is_ours(handler)]
            if remaining:
                copy = dict(group)
                copy["hooks"] = remaining
                cleaned.append(copy)
        if not remove:
            cleaned.append({
                "hooks": [{
                    "type": "command",
                    "command": hook_command(),
                    "timeout": 5,
                    "statusMessage": status,
                }]
            })
        if cleaned:
            hooks[event] = cleaned
        else:
            hooks.pop(event, None)
    if not hooks:
        document.pop("hooks", None)
    return document


def _write_json_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def update_hooks(remove=False):
    path = hooks_path()
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        document = {}
    except json.JSONDecodeError as error:
        raise RuntimeError("{} is not valid JSON: {}".format(path, error))
    if path.exists():
        backup = path.with_name(path.name + ".codex-rest-{}.bak".format(time.strftime("%Y%m%d-%H%M%S")))
        shutil.copy2(str(path), str(backup))
    _write_json_atomic(path, merge_hooks(document, remove=remove))


def install(source_root=None):
    source = Path(source_root or Path(__file__).resolve().parents[1])
    target = installed_runtime_dir()
    # Stop an older daemon before replacing its runtime during an app update.
    try:
        from .client import request
        request("/api/shutdown", method="POST", data={}, timeout=1, ensure=False)
        time.sleep(0.15)
    except Exception:
        pass
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / ("runtime.new-" + str(os.getpid()))
    if temporary.exists():
        shutil.rmtree(str(temporary))
    temporary.mkdir(parents=True)
    shutil.copytree(str(source / "codex_rest"), str(temporary / "codex_rest"))
    if target.exists():
        old = target.parent / ("runtime.old-" + str(os.getpid()))
        target.rename(old)
        temporary.rename(target)
        shutil.rmtree(str(old), ignore_errors=True)
    else:
        temporary.rename(target)

    wrapper = wrapper_path()
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    script = """#!/bin/sh
export PYTHONPATH={runtime}
exec {python} -m codex_rest.cli "$@"
""".format(runtime=shlex_quote(str(target)), python=shlex_quote(sys.executable))
    wrapper.write_text(script, encoding="utf-8")
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    update_hooks(remove=False)
    return wrapper


def uninstall(purge=False):
    try:
        from .client import request
        request("/api/shutdown", method="POST", data={}, timeout=1, ensure=False)
    except Exception:
        pass
    update_hooks(remove=True)
    try:
        wrapper_path().unlink()
    except FileNotFoundError:
        pass
    shutil.rmtree(str(installed_runtime_dir()), ignore_errors=True)
    if purge:
        shutil.rmtree(str(app_home()), ignore_errors=True)


def shlex_quote(value):
    return "'" + value.replace("'", "'\"'\"'") + "'"
