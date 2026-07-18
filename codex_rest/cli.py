import argparse
import json
import os
import platform
import subprocess
import sys
import urllib.parse

from . import __version__
from .client import ensure_daemon, hook as send_hook, read_runtime, request
from .install import install, uninstall
from .paths import chrome_path, hooks_path, wrapper_path
from .server import run_server


def command_hook(_args):
    try:
        payload = json.load(sys.stdin)
        safe = {
            "hook_event_name": payload.get("hook_event_name"),
            "session_id": payload.get("session_id"),
            "turn_id": payload.get("turn_id"),
        }
        send_hook(safe)
    except Exception:
        # Hooks must never block Codex. Diagnostics remain available via doctor/logs.
        return 0
    return 0


def command_settings(_args):
    ensure_daemon()
    runtime = read_runtime()
    url = "http://127.0.0.1:{}/settings#{}".format(runtime["port"], runtime["token"])
    subprocess.Popen(["/usr/bin/open", url])
    print("設定画面を開きました。")
    return 0


def command_status(_args):
    try:
        state = request("/api/state", ensure=False)
    except Exception:
        print("Codex Rest: 停止中")
        return 0
    settings = state["settings"]
    print("Codex Rest: {}".format("稼働中" if state["active_count"] else "待機中"))
    print("アクティブタスク: {} / 承認待ち: {}".format(state["active_count"], state["paused_count"]))
    print("休憩画面: {}".format("表示中" if state["browser_open"] else "非表示"))
    print("音楽: {} / 完了通知音: {}".format(
        "ON" if settings["music_enabled"] else "OFF",
        "ON" if settings["completion_sound_enabled"] else "OFF",
    ))
    return 0


def command_start(_args):
    ensure_daemon()
    return 0


def command_doctor(_args):
    checks = []
    checks.append((platform.system() == "Darwin", "macOS", platform.platform()))
    checks.append((chrome_path().is_file(), "Google Chrome", str(chrome_path())))
    checks.append((os.path.isfile("/usr/bin/afplay"), "完了通知音", "/usr/bin/afplay"))
    checks.append((hooks_path().exists(), "Codex hooks.json", str(hooks_path())))
    checks.append((wrapper_path().exists(), "codex-rest CLI", str(wrapper_path())))
    try:
        document = json.loads(hooks_path().read_text(encoding="utf-8"))
        command = str(wrapper_path()) + " hook"
        count = sum(
            1 for groups in document.get("hooks", {}).values()
            for group in groups for handler in group.get("hooks", [])
            if handler.get("command") == command
        )
        checks.append((count == 4, "Codexフック4件", "{}件".format(count)))
    except Exception as error:
        checks.append((False, "Codexフック4件", str(error)))
    failed = False
    for passed, label, detail in checks:
        print("{} {:<18} {}".format("✓" if passed else "✗", label, detail))
        failed = failed or not passed
    if read_runtime():
        print("✓ デーモン           稼働中")
    else:
        print("- デーモン           未起動（最初のプロンプトで自動起動）")
    return 1 if failed else 0


def build_parser():
    parser = argparse.ArgumentParser(prog="codex-rest")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("hook").set_defaults(func=command_hook)
    commands.add_parser("daemon").set_defaults(func=lambda _args: run_server() or 0)
    commands.add_parser("settings").set_defaults(func=command_settings)
    commands.add_parser("status").set_defaults(func=command_status)
    commands.add_parser("start", help="バックエンドを起動").set_defaults(func=command_start)
    commands.add_parser("doctor").set_defaults(func=command_doctor)
    install_parser = commands.add_parser("install")
    install_parser.set_defaults(func=lambda _args: (print("Installed: {}".format(install())) or 0))
    uninstall_parser = commands.add_parser("uninstall")
    uninstall_parser.add_argument("--purge-data", action="store_true")
    uninstall_parser.set_defaults(func=lambda args: (uninstall(args.purge_data) or 0))
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
