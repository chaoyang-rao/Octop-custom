"""Copy only checksum-verified companion delivery assets into a joint release."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def collect(mac: Path, windows: Path, output: Path) -> None:
    version = json.loads((ROOT / "desktop-companion/package.json").read_text())["version"]
    if (
        json.loads((ROOT / "desktop-companion/windows/package.json").read_text())["version"]
        != version
    ):
        raise ValueError("Both companion platforms must use the same version")
    output.mkdir(parents=True, exist_ok=True)
    for root, names in [
        (
            mac,
            [
                f"Dora-macos-universal-{version}.dmg",
                f"Dora-update-darwin-amd64-{version}.zip",
                f"Dora-update-darwin-arm64-{version}.zip",
            ],
        ),
        (
            windows,
            [f"Dora-Windows-x64-{version}-Setup.exe", f"Dora-update-windows-amd64-{version}.zip"],
        ),
    ]:
        checksums = {}
        for line in (root / "SHA256SUMS.txt").read_text(encoding="utf-8-sig").splitlines():
            digest, name = line.split(maxsplit=1)
            checksums[name.strip()] = digest
        for name in names:
            file = root / name
            with file.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if (
                file.is_symlink()
                or file.stat().st_size <= 100_000_000
                or checksums.get(name) != digest
            ):
                raise ValueError("Companion delivery is incomplete or changed: " + name)
            shutil.copy2(file, output / name)
    print(f"Verified companion {version}: two installers and three native update packages")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mac", type=Path, required=True)
    parser.add_argument("--windows", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    collect(args.mac, args.windows, args.output)
