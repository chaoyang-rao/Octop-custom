#!/usr/bin/env python3
"""Install or roll back the reviewed local Octop customization.

Only files changed against the saved baseline are installed. Never overwrite
unexpected runtime changes, and never restore an old database over new chats.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile

ROOT = Path(__file__).resolve().parent
_baseline_config = ROOT / "avatar-baseline.json"
BASELINE = json.loads(_baseline_config.read_text()) if _baseline_config.exists() else {
    "version": "1.0.2+projects-v2",
    "backup": str(ROOT / "baselines" / "projects-v2"),
    "runtime": str(Path.home() / ".octop" / "portable" / "packages"),
}
RUNTIME = Path(BASELINE["runtime"])
BASE = Path(BASELINE["backup"])
PACKAGES = ROOT / "packages"
RELEASE = ROOT / "avatar-release-manifest.json"


def digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def changes() -> list[dict]:
    result = []
    for path in sorted(PACKAGES.rglob("*")):
        rel = path.relative_to(PACKAGES)
        if not path.is_file() or "__pycache__" in rel.parts or path.suffix == ".pyc":
            continue
        if path.name == ".DS_Store":
            continue
        old, new = digest(BASE / rel), digest(path)
        if old != new:
            result.append({"path": str(rel), "baseline_sha256": old, "sha256": new})
    return result


def replace_file(source: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".octop-avatars-", dir=dest.parent)
    os.close(fd)
    try:
        shutil.copy2(source, name)
        os.replace(name, dest)
    finally:
        if Path(name).exists():
            Path(name).unlink()


def apply(rows: list[dict]) -> None:
    if not rows:
        raise SystemExit("No changes to install.")
    if all(digest(RUNTIME / row["path"]) == row["sha256"] for row in rows):
        print("This exact patch is already installed; no files or backups changed.")
        return
    previous = json.loads(RELEASE.read_text()) if RELEASE.exists() else {"files": []}
    known = {row["path"]: row["sha256"] for row in previous["files"]}
    for row in rows:
        actual = digest(RUNTIME / row["path"])
        if actual not in (row["baseline_sha256"], row["sha256"], known.get(row["path"])):
            raise SystemExit(f"Runtime changed independently; stop: {row['path']}")
    pending = [row for row in rows if digest(RUNTIME / row["path"]) != row["sha256"]]
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup = ROOT.parent / "backups" / ("deployment-" + stamp)
    backup.mkdir(parents=True, mode=0o700)
    for row in pending:
        src = RUNTIME / row["path"]
        if src.is_file():
            dst = backup / "files" / row["path"]
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    db = Path.home() / ".octop" / "octop.db"
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as src:
        with sqlite3.connect(backup / "octop.db") as dst:
            src.backup(dst)
    (backup / "octop.db").chmod(0o600)
    manifest = {"baseline_version": BASELINE["version"], "backup": str(backup), "files": rows}
    (backup / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    installed = []
    try:
        for row in pending:
            replace_file(PACKAGES / row["path"], RUNTIME / row["path"])
            installed.append(row)
    except Exception:
        for row in reversed(installed):
            saved = backup / "files" / row["path"]
            if saved.exists():
                replace_file(saved, RUNTIME / row["path"])
            elif (RUNTIME / row["path"]).exists():
                (RUNTIME / row["path"]).unlink()
        raise
    RELEASE.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(f"Installed {len(pending)} changed files. Backup: {backup}")
    print("Restart Octop to load the updated Python modules.")


def rollback() -> None:
    manifest = json.loads(RELEASE.read_text())
    for row in manifest["files"]:
        if digest(RUNTIME / row["path"]) != row["sha256"]:
            raise SystemExit(f"Runtime changed since deployment; stop: {row['path']}")
    for row in manifest["files"]:
        saved = BASE / row["path"]
        target = RUNTIME / row["path"]
        if saved.exists():
            replace_file(saved, target)
        else:
            target.unlink()
    print("Program files restored. The current database and all chats are preserved.")
    print("Restart Octop. Avatar metadata and all chat history remain in the current database.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "apply", "rollback"), nargs="?", default="check")
    args = parser.parse_args()
    if args.action == "rollback":
        rollback()
    else:
        rows = changes()
        if args.action == "apply":
            apply(rows)
        else:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
