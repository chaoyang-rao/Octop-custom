"""Verify a Vite dashboard and freeze it into the portable program packages."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
_ASSET_PATH = re.compile(
    r"""["'](/?assets/[^"'\s]+\.(?:js|css|woff2?|ttf|svg|png|webp))(?:\?[^"']*)?["']"""
)
_RELATIVE_MODULE = re.compile(
    r"""(?:\bfrom\s*|\bimport\s*(?:\(\s*)?|\bimportScripts\(\s*)["'](\.{1,2}/[^"']+\.(?:js|css))["']"""
)
_GENERATED = re.compile(r"[-.][A-Za-z0-9_-]{8}\.(?:js|css)$")
_CSS_URL = re.compile(r"""url\(\s*["']?([^\s"')]+)""")


def verify(directory: Path) -> dict[str, str]:
    if directory.is_symlink():
        raise ValueError("Dashboard root must not be a symlink")
    index = directory / "index.html"
    if not index.is_file() or not (directory / "assets").is_dir():
        raise ValueError("Build dashboard/ before freezing its output")
    files = {}
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"Dashboard output contains a symlink: {path}")
        if path.is_file() and path.name not in {".DS_Store", ".gitkeep"}:
            files[path.relative_to(directory).as_posix()] = path

    def require(parent: Path, value: str) -> None:
        parsed = urlsplit(value)
        if parsed.scheme or parsed.netloc or not parsed.path or parsed.path.startswith("var("):
            return
        path = unquote(parsed.path)
        target = (
            directory / path.lstrip("/") if path.startswith(("/", "assets/")) else parent / path
        )
        resolved = target.resolve()
        if not resolved.is_relative_to(directory.resolve()) or not resolved.is_file():
            raise ValueError(f"Missing local dashboard resource: {value}")

    html = index.read_text(encoding="utf-8")
    for value in re.findall(r"""(?:src|href)=["']([^"']+)["']""", html):
        require(directory, value)
    for name, path in files.items():
        if path.suffix not in {".js", ".css"}:
            continue
        text = path.read_text(encoding="utf-8")
        if re.search(r"\.avatars-v\d+\.(?:js|css)", text):
            raise ValueError(f"New dashboard still imports a legacy release: {name}")
        for value in _ASSET_PATH.findall(text):
            require(directory, value)
        for value in _RELATIVE_MODULE.findall(text):
            if _GENERATED.search(value):
                require(path.parent, value)
        if path.suffix == ".css":
            for value in _CSS_URL.findall(text):
                require(path.parent, value)
    return {
        name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in sorted(files.items())
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--check", action="store_true")
    options = parser.parse_args()
    source = ROOT / "src/octop/dashboard"
    target = ROOT / "customization/packages/octop/dashboard"
    for ancestor in (target, *target.parents):
        if ancestor == ROOT:
            break
        if ancestor.is_symlink():
            raise SystemExit(f"Dashboard target contains a symlink: {ancestor}")
    if options.apply:
        expected = verify(source)
        temporary = target.with_name("dashboard.building")
        if temporary.exists():
            raise SystemExit("Review the previous unfinished dashboard.building directory")
        shutil.copytree(source, temporary)
        if verify(temporary) != expected:
            raise SystemExit("Copied dashboard does not match its verified source")
        shutil.rmtree(target)
        temporary.rename(target)
        manifest = {
            "kind": "vite-source-build",
            "upstream_version": json.loads(
                (ROOT / "scripts/custom/upstream-lock.json").read_text()
            )["upstream_version"],
            "files": expected,
        }
        (ROOT / "customization/frontend/source-asset-release.json").write_text(
            json.dumps(manifest, indent=2) + "\n"
        )
    else:
        expected = json.loads(
            (ROOT / "customization/frontend/source-asset-release.json").read_text()
        )["files"]
        if verify(target) != expected:
            raise SystemExit("Frozen dashboard has drifted from its source-build manifest")
    print(json.dumps({"dashboard_files": len(expected), "verified": True}))
