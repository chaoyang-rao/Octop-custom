#!/usr/bin/env python3
"""Repair missing speech purpose strings in an ad hoc signed local Mac app.

Check-only by default. Quit the app before --apply. No OS permissions are
granted: macOS still asks the user when voice input is explicitly started.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import plistlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

PURPOSES = {
    "NSMicrophoneUsageDescription": "用于您主动开启的语音输入，将说话内容转换为聊天文字。",
    "NSSpeechRecognitionUsageDescription": "用于通过系统语音识别服务将您主动输入的语音转换为文字。",
}


def repair(app: Path, *, apply: bool, backups: Path) -> dict:
    info_path = app / "Contents/Info.plist"
    info = plistlib.loads(info_path.read_bytes())
    missing = [key for key in PURPOSES if not str(info.get(key) or "").strip()]
    result = {"app": str(app), "missing": missing, "applied": False}
    if not apply or not missing:
        return result
    binary = app / "Contents/MacOS" / info["CFBundleExecutable"]
    running = subprocess.run(["pgrep", "-f", re.escape(str(binary)) + "($| )"], capture_output=True)
    if running.returncode == 0:
        raise RuntimeError("Quit Octop before repairing its signed app bundle.")
    signature = subprocess.run(
        ["codesign", "-dvv", str(app)], capture_output=True, text=True, check=True
    )
    if "Signature=adhoc" not in signature.stderr:
        raise RuntimeError("Only existing ad hoc signatures can be repaired with this tool.")
    backup = backups / ("voice-permissions-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    backup.mkdir(parents=True, mode=0o700)
    saved = [
        Path("Contents/Info.plist"),
        binary.relative_to(app),
        Path("Contents/_CodeSignature/CodeResources"),
    ]
    for relative in saved:
        destination = backup / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(app / relative, destination)
    try:
        for key in missing:
            info[key] = PURPOSES[key]
        info_path.write_bytes(plistlib.dumps(info, sort_keys=False))
        subprocess.run(
            [
                "codesign",
                "--force",
                "--sign",
                "-",
                "--preserve-metadata=identifier,entitlements,flags,runtime",
                str(app),
            ],
            check=True,
            capture_output=True,
        )
        subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)
    except BaseException:
        for relative in saved:
            shutil.copy2(backup / relative, app / relative)
        raise
    result.update(applied=True, backup=str(backup))
    (backup / "repair.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, default=Path("/Applications/Octop.app"))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--backups", type=Path, default=Path(__file__).resolve().parents[2] / "backups"
    )
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("This repair is only for macOS app bundles.")
    print(
        json.dumps(
            repair(args.app, apply=args.apply, backups=args.backups), ensure_ascii=False, indent=2
        )
    )


if __name__ == "__main__":
    main()
