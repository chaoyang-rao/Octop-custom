"""Build self-contained engine archives from locked public runtimes and source."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(REPO / "scripts/custom"))
from build_portable import build_archive, git_is_dirty, git_revision, obtain_source
from runtime_dependencies import prepare


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arch", choices=["arm64", "x86_64", "universal"], default="universal")
    parser.add_argument("--platform", choices=["macos", "windows-amd64"], default="macos")
    args = parser.parse_args()
    lock = json.loads((REPO / "scripts/custom/upstream-lock.json").read_text())
    authority = "https://120.79.0.171:18443"
    output = ROOT / ("build/windows-engine" if args.platform == "windows-amd64" else "build/engine")
    output.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [sys.executable, str(REPO / "scripts/custom/sync_octop_source.py"), "--check"], check=True
    )
    subprocess.run(
        [sys.executable, str(REPO / "scripts/custom/sync_dashboard.py"), "--check"], check=True
    )
    manifest = {"authority": authority, "architectures": {}}
    architectures = (
        ["windows-amd64"]
        if args.platform == "windows-amd64"
        else (["arm64", "x86_64"] if args.arch == "universal" else [args.arch])
    )
    for arch in architectures:
        platform = (
            arch if arch == "windows-amd64" else "darwin-" + ("amd64" if arch == "x86_64" else arch)
        )
        source = obtain_source(platform, lock, REPO / ".cache/custom-release")
        target = output / ("engine-" + arch + ".zip")
        dependencies = prepare(platform, REPO / ".cache/runtime-dependency-wheels")
        build_archive(
            source,
            target,
            platform,
            REPO / "customization/packages",
            lock,
            git_revision(REPO),
            git_is_dirty(REPO),
            dependency_overlay=dependencies,
            enterprise_authority_url=authority,
        )
        manifest["architectures"][arch] = {
            "file": target.name,
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "root": "Octop-" + platform,
        }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(
        json.dumps(
            {"engine_architectures": list(manifest["architectures"]), "user_data_included": False}
        )
    )


if __name__ == "__main__":
    main()
