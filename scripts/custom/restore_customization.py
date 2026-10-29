#!/usr/bin/env python3
"""Restore reviewed Octop 1.0.2 program changes; check-only unless --apply."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import stat
import sys
import tempfile
from contextlib import closing
from datetime import UTC, datetime
from email.parser import Parser
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_VERSION = "1.0.2"
PACKAGE_NAMES = {"octop", "octop_harness", "octop_gateway"}
MARKER = "octop-custom-release.json"
INSTALL_MANIFEST = "custom-restore-manifest.json"


def digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def json_bytes(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def default_packages(home: Path | None = None) -> Path:
    home = home or Path.home()
    custom = home / ".octop" / "custom-runtime" / "portable" / "packages"
    return custom if custom.is_dir() else home / ".octop" / "portable" / "packages"


def program_path(root: Path, name: str) -> Path:
    relative = PurePosixPath(name)
    if (
        not name
        or "\\" in name
        or ":" in name
        or relative.is_absolute()
        or any(part in {".", ".."} for part in name.split("/"))
        or (relative.parts[0] not in PACKAGE_NAMES and name != MARKER)
    ):
        raise ValueError(f"Invalid program path: {name}")
    path = root.joinpath(*relative.parts)
    for ancestor in (path, *path.parents):
        if ancestor == root:
            break
        if ancestor.is_symlink():
            raise ValueError(f"Program path contains a symlink: {name}")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Program path escapes packages: {name}")
    return path


def validate_version(packages: Path) -> None:
    metadata = sorted(packages.glob("octop-*.dist-info/METADATA"))
    versions = [
        Parser().parsestr(path.read_text(encoding="utf-8")).get("Version") for path in metadata
    ]
    if versions != [BASE_VERSION]:
        raise ValueError(
            f"Expected one Octop {BASE_VERSION} package METADATA; found versions {versions}"
        )


def previous_hashes(packages: Path) -> dict:
    own = packages.parent / INSTALL_MANIFEST
    if own.exists():
        manifest = json.loads(own.read_text(encoding="utf-8"))
    else:
        release = packages.parent / "custom-release-manifest.json"
        marker = packages / MARKER
        if not release.is_file() or not marker.is_file():
            return {}
        marker_data = json.loads(marker.read_text(encoding="utf-8"))
        if marker_data.get("manifest_sha256") != digest(release):
            return {}
        manifest = json.loads(release.read_text(encoding="utf-8"))
    if manifest.get("upstream_version") != BASE_VERSION:
        raise ValueError("Previous installation manifest has a different upstream version")
    # Portable ZIP manifests include the packages/ prefix; local restore
    # manifests store paths relative to that directory.
    return {
        name.removeprefix("packages/"): sha
        for name, sha in manifest.get("package_file_sha256", {}).items()
    }


def plan(packages: Path, repo: Path) -> list[dict]:
    validate_version(packages)
    source = repo / "customization" / "packages"
    baseline = repo / "customization" / "baselines" / "original"
    known = previous_hashes(packages)
    rows = []
    for package in sorted(PACKAGE_NAMES):
        if not (source / package).is_dir() or not (baseline / package).is_dir():
            raise ValueError(f"Missing repository program source/baseline: {package}")
        for path in sorted((source / package).rglob("*")):
            if (
                not path.is_file()
                or "__pycache__" in path.parts
                or path.name == ".DS_Store"
                or path.suffix in {".pyc", ".pyo"}
            ):
                continue
            if (
                path.suffix in {".db", ".sqlite", ".sqlite3"}
                or any(token in path.name for token in (".db-", ".sqlite-", ".sqlite3-"))
                or path.name.startswith(".env")
            ):
                raise ValueError("Private/runtime files must not appear in program source")
            name = path.relative_to(source).as_posix()
            current = digest(program_path(source, name))
            original = digest(program_path(baseline, name))
            if current == original:
                continue
            target = program_path(packages, name)
            actual = digest(target)
            allowed = {None, current} if original is None else {original, current}
            if known.get(name) is not None:
                allowed.add(known[name])
            if actual not in allowed:
                raise ValueError(
                    f"Independent program changes detected; refusing overwrite: {name}"
                )
            rows.append({"path": name, "sha256": current, "before_sha256": actual})
    marker = program_path(packages, MARKER)
    if not marker.exists():
        data = json_bytes(
            {"upstream_version": BASE_VERSION, "managed_by": "restore_customization.py"}
        )
        rows.append(
            {"path": MARKER, "sha256": hashlib.sha256(data).hexdigest(), "before_sha256": None}
        )
    return rows


def atomic_write(path: Path, data: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".octop-restore-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def restore_rows(packages: Path, backup: Path, rows: list[dict]) -> None:
    for row in rows:
        target = program_path(packages, row["path"])
        if row["before_sha256"] is None:
            target.unlink(missing_ok=True)
        else:
            saved = program_path(backup / "files", row["path"])
            atomic_write(target, saved.read_bytes(), row["before_mode"])


def restore(
    packages: Path, *, apply: bool = False, repo: Path = REPO_ROOT, home: Path | None = None
) -> dict:
    packages = packages.resolve()
    rows = plan(packages, repo)
    pending = [row for row in rows if row["sha256"] != row["before_sha256"]]
    result = {
        "mode": "apply" if apply else "check",
        "upstream_version": BASE_VERSION,
        "packages": str(packages),
        "managed_files": len(rows),
        "pending_files": len(pending),
    }
    if not apply or not pending:
        return result
    parent = packages.parent / "customization-backups"
    parent.mkdir(mode=0o700, exist_ok=True)
    parent.chmod(0o700)
    backup = Path(
        tempfile.mkdtemp(prefix=datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ-"), dir=parent)
    )
    backup.chmod(0o700)
    state = packages.parent / INSTALL_MANIFEST
    previous_state = state.read_bytes() if state.exists() else None
    if previous_state is not None:
        atomic_write(backup / "previous-install-manifest.json", previous_state)
    for row in pending:
        target = program_path(packages, row["path"])
        if digest(target) != row["before_sha256"]:
            raise ValueError("Program changed while preparing backup; retry after closing Octop")
        row["before_mode"] = stat.S_IMODE(target.stat().st_mode) if target.exists() else None
        if row["before_sha256"] is not None:
            atomic_write(program_path(backup / "files", row["path"]), target.read_bytes())
    database = (home or Path.home()) / ".octop" / "octop.db"
    if database.is_file():
        with (
            closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as source,
            closing(sqlite3.connect(backup / "octop.db")) as destination,
        ):
            source.backup(destination)
        (backup / "octop.db").chmod(0o600)
    manifest = {
        "upstream_version": BASE_VERSION,
        "packages": str(packages),
        "files": pending,
        "previous_manifest_sha256": hashlib.sha256(previous_state).hexdigest()
        if previous_state is not None
        else None,
    }
    atomic_write(backup / "manifest.json", json_bytes(manifest))
    installed = []
    try:
        for row in pending:
            target = program_path(packages, row["path"])
            if digest(target) != row["before_sha256"]:
                raise ValueError(f"Program changed after backup: {row['path']}")
            if row["path"] == MARKER:
                data = json_bytes(
                    {"upstream_version": BASE_VERSION, "managed_by": "restore_customization.py"}
                )
                mode = 0o644
            else:
                source = program_path(repo / "customization" / "packages", row["path"])
                data = source.read_bytes()
                mode = stat.S_IMODE(source.stat().st_mode)
            if hashlib.sha256(data).hexdigest() != row["sha256"]:
                raise ValueError("Repository source changed during restoration")
            atomic_write(target, data, mode)
            installed.append(row)
        state_data = json_bytes(
            {
                "upstream_version": BASE_VERSION,
                "package_file_sha256": {row["path"]: row["sha256"] for row in rows},
            }
        )
        atomic_write(state, state_data)
        manifest["installed_manifest_sha256"] = hashlib.sha256(state_data).hexdigest()
        atomic_write(backup / "manifest.json", json_bytes(manifest))
    except Exception:
        restore_rows(packages, backup, reversed(installed))
        if previous_state is None:
            state.unlink(missing_ok=True)
        else:
            atomic_write(state, previous_state)
        raise
    result["backup"] = str(backup)
    return result


def rollback(packages: Path, backup: Path, *, apply: bool = False) -> dict:
    packages, backup = packages.resolve(), backup.resolve()
    validate_version(packages)
    manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
    if (
        manifest.get("upstream_version") != BASE_VERSION
        or Path(manifest["packages"]).resolve() != packages
    ):
        raise ValueError("Backup belongs to another package installation/version")
    rows = manifest["files"]
    for row in rows:
        if digest(program_path(packages, row["path"])) != row["sha256"]:
            raise ValueError(
                f"Program changed since installation; refusing rollback: {row['path']}"
            )
        if (
            row["before_sha256"] is not None
            and digest(program_path(backup / "files", row["path"])) != row["before_sha256"]
        ):
            raise ValueError("Backup program checksum mismatch")
    state = packages.parent / INSTALL_MANIFEST
    if digest(state) != manifest.get("installed_manifest_sha256"):
        raise ValueError("Installation manifest changed since this backup")
    previous_state = backup / "previous-install-manifest.json"
    if digest(previous_state) != manifest["previous_manifest_sha256"]:
        raise ValueError("Previous installation manifest backup checksum mismatch")
    if apply:
        restore_rows(packages, backup, rows)
        if previous_state.exists():
            atomic_write(state, previous_state.read_bytes())
        else:
            state.unlink()
    return {
        "mode": "rollback" if apply else "check-rollback",
        "program_files": len(rows),
        "packages": str(packages),
        "database_restored": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packages", type=Path, default=None)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check", action="store_true", help="Read-only compatibility/integrity check (default)"
    )
    mode.add_argument(
        "--apply", action="store_true", help="Explicitly apply program changes or rollback"
    )
    parser.add_argument("--rollback", type=Path, metavar="BACKUP_DIR")
    args = parser.parse_args()
    packages = args.packages or default_packages()
    try:
        result = (
            rollback(packages, args.rollback, apply=args.apply)
            if args.rollback
            else restore(packages, apply=args.apply)
        )
    except (ValueError, OSError, sqlite3.Error, KeyError) as error:
        print(f"Refusing recovery: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
