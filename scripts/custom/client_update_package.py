"""Stamp and archive the fixed native application update payload (no user data)."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "desktop/src"


def stamp(version: str, authority: str) -> None:
    if not re.fullmatch(r"1\.0\.3b3\.post\d{10}", version):
        raise ValueError("Expected a custom release version")
    authority = authority.rstrip("/")
    python_pins = json.loads((ROOT / "src/octop/infra/client_updates/trust.json").read_text())
    native_pins = json.loads((DESKTOP / "internal/clientupdate/trust.json").read_text())
    if python_pins != native_pins or not native_pins["authorities"].get(authority):
        raise ValueError("The company authority needs a reviewed, pinned update signing key")
    value = {"product": "octop-desktop", "protocol": 1, "version": version, "authority": authority}
    (DESKTOP / "assets/client-update-build.json").write_text(json.dumps(value) + "\n")


def archive(platform: str, version: str, output: Path) -> Path:
    root = DESKTOP / "bin"
    if platform.startswith("darwin-"):
        application = root / "OctopCustom.app"
        files = sorted(application.rglob("*"))
        prefix = "OctopCustom.app"
        build_file = application / "Contents/Resources/client-update-build.json"
    else:
        application = root
        files = [root / n for n in ("OctopCustom.exe", "client-updater.exe")]
        # The NSIS installer and update payload contain the same metadata.
        build_file = DESKTOP / "assets/client-update-build.json"
        files.append(build_file)
        prefix = "OctopCustom"
    if json.loads(build_file.read_text())["version"] != version:
        raise ValueError("Application version differs from update target")
    output.mkdir(parents=True, exist_ok=True)
    target = output / f"OctopCustom-update-{platform}-{version}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for path in files:
            relative = (
                path.relative_to(application).as_posix()
                if path.is_relative_to(application)
                else path.name
            )
            name = f"{prefix}/{relative}"
            if path.is_symlink():
                link = os.readlink(path)
                if os.path.isabs(link) or not path.resolve().is_relative_to(application.resolve()):
                    raise ValueError("Application link escapes the bundle")
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                bundle.writestr(info, link)
            elif path.is_file():
                bundle.write(path, name)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("stamp")
    prepare.add_argument("--version", required=True)
    prepare.add_argument("--authority", required=True)
    pack = commands.add_parser("archive")
    pack.add_argument("--version", required=True)
    pack.add_argument(
        "--platform", choices=["darwin-arm64", "darwin-amd64", "windows-amd64"], required=True
    )
    pack.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    if args.command == "stamp":
        stamp(args.version, args.authority)
    else:
        print(archive(args.platform, args.version, args.output))


if __name__ == "__main__":
    main()
