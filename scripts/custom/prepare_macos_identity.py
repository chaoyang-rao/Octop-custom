"""Prepare an in-place Mac update without changing the installed app's identity.

Only a staged application is modified. The old application, executable name,
new version, permissions declarations and all user data remain untouched.
"""

from __future__ import annotations

import argparse
import json
import plistlib
import subprocess
import sys
from pathlib import Path


def update_identity(incoming: dict, installed: dict) -> dict:
    if not installed.get("CFBundleIdentifier") or not incoming.get("CFBundleExecutable"):
        raise ValueError("Both installed identity and incoming executable are required")
    result = dict(incoming)
    for key in ("CFBundleIdentifier", "CFBundleName", "CFBundleDisplayName"):
        if key in installed:
            result[key] = installed[key]
        else:
            result.pop(key, None)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", required=True, type=Path, help="Staged incoming .app")
    parser.add_argument("--current", type=Path, default=Path("/Applications/Octop.app"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if (
        args.app.resolve() == args.current.resolve()
        or args.current.resolve() in args.app.resolve().parents
    ):
        raise SystemExit("Prepare a separate staged application, not the running installation")
    info_path = args.app / "Contents/Info.plist"
    incoming = plistlib.loads(info_path.read_bytes())
    installed = plistlib.loads((args.current / "Contents/Info.plist").read_bytes())
    result = update_identity(incoming, installed)
    if args.apply:
        if sys.platform != "darwin":
            raise SystemExit("Application signing requires macOS")
        info_path.write_bytes(plistlib.dumps(result, sort_keys=False))
        subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(args.app)], check=True)
        subprocess.run(["codesign", "--verify", "--deep", "--strict", str(args.app)], check=True)
    print(
        json.dumps(
            {
                "mode": "apply" if args.apply else "check",
                "identifier": result["CFBundleIdentifier"],
                "name": result.get("CFBundleName"),
                "version": result.get("CFBundleShortVersionString"),
            }
        )
    )
