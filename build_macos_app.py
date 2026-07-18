#!/usr/bin/env python3
"""Build and optionally install the native Codex Rest macOS app."""

import argparse
import os
import plistlib
import shutil
import subprocess
from pathlib import Path

from codex_rest import __version__


ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
APP = BUILD / "Codex Rest.app"


def build():
    if APP.exists():
        shutil.rmtree(APP)
    macos = APP / "Contents" / "MacOS"
    resources = APP / "Contents" / "Resources"
    backend = resources / "backend"
    macos.mkdir(parents=True)
    backend.mkdir(parents=True)

    subprocess.run([
        "xcrun", "clang",
        "-O2",
        "-fobjc-arc",
        "-fmodules",
        "-mmacosx-version-min=13.0",
        str(ROOT / "macos_app" / "CodexRestApp.m"),
        "-o", str(macos / "CodexRest"),
        "-framework", "Cocoa",
        "-framework", "WebKit",
    ], check=True)

    shutil.copytree(ROOT / "codex_rest", backend / "codex_rest", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(ROOT / "install.py", backend / "install.py")

    info = {
        "CFBundleDevelopmentRegion": "ja",
        "CFBundleDisplayName": "Codex Rest",
        "CFBundleExecutable": "CodexRest",
        "CFBundleIdentifier": "com.senba.codex-rest",
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": "Codex Rest",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": __version__,
        "CFBundleVersion": "1",
        "LSMinimumSystemVersion": "13.0",
        "NSHighResolutionCapable": True,
        "NSPrincipalClass": "NSApplication",
        "NSHumanReadableCopyright": "Local utility for Codex",
    }
    with (APP / "Contents" / "Info.plist").open("wb") as handle:
        plistlib.dump(info, handle)

    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(APP)], check=True)
    return APP


def install(app):
    applications = Path.home() / "Applications"
    applications.mkdir(parents=True, exist_ok=True)
    target = applications / app.name
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(app, target, symlinks=True)
    subprocess.run(["/usr/bin/open", str(target)], check=True)
    return target


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()
    app = build()
    print("Built: {}".format(app))
    if args.install:
        print("Installed: {}".format(install(app)))


if __name__ == "__main__":
    main()
