"""Remove obsolete generated releases after validating the current dashboard graph.

Unversioned helper sources, fonts, images and saved baselines are never candidates.
Run without --apply to preview the removal list.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

_VERSIONED = re.compile(r"\.avatars-v\d+\.(?:js|css)$")
_HASHED_CSS = re.compile(r"\.[a-f0-9]{10}\.css$")
_REFERENCE = re.compile(r"(?<![\w.-])([\w.@-]+\.(?:js|css))(?=[\"'`?#)\s])")


def obsolete_assets(dashboard: Path, manifest: dict[str, object]) -> list[Path]:
    release = str(manifest["release"])
    if not re.fullmatch(r"avatars-v\d+", release):
        raise ValueError("Unknown generated release name")
    names = manifest["assets"]
    if not isinstance(names, list) or not names:
        raise ValueError("The current asset manifest must not be empty")
    assets = dashboard / "assets"
    for name in names:
        if not isinstance(name, str) or Path(name).name != name:
            raise ValueError("Asset names must stay inside the assets directory")
        if _VERSIONED.search(name) and f".{release}." not in name:
            raise ValueError(f"Current manifest contains an old release: {name}")
        if not (assets / name).is_file():
            raise ValueError(f"Current asset is missing: {name}")
    known = {p.name for p in assets.iterdir() if p.is_file()}

    def references(text: str) -> set[str]:
        return {
            name
            for name in _REFERENCE.findall(text)
            if name in known or _VERSIONED.search(name) or _HASHED_CSS.search(name)
        }

    pending = set(names) | references((dashboard / "index.html").read_text(encoding="utf-8"))
    active: set[str] = set()
    while pending:
        name = pending.pop()
        if name in active:
            continue
        active.add(name)
        target = assets / name
        if not target.is_file():
            raise ValueError(f"Referenced asset is missing: {name}")
        if _VERSIONED.search(name) and f".{release}." not in name:
            raise ValueError(f"Current graph still references an old release: {name}")
        if target.suffix in {".js", ".css"}:
            pending.update(references(target.read_text(encoding="utf-8")) - active)
    return sorted(
        (
            p
            for p in assets.iterdir()
            if p.is_file()
            and not p.is_symlink()
            and p.name not in active
            and (_VERSIONED.search(p.name) or _HASHED_CSS.search(p.name))
        ),
        key=lambda p: p.name,
    )


def prune_assets(dashboard: Path, manifest: dict[str, object], *, apply: bool = False) -> int:
    obsolete = obsolete_assets(dashboard, manifest)
    size = sum(p.stat().st_size for p in obsolete)
    if apply:
        for p in obsolete:
            p.unlink()
    print(f"{'Removed' if apply else 'Would remove'} {len(obsolete)} obsolete assets ({size / 1024**2:.2f} MiB)")
    return len(obsolete)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    current = json.loads((root / "frontend" / "avatar-asset-release.json").read_text())
    prune_assets(root / "packages" / "octop" / "dashboard", current, apply=args.apply)
