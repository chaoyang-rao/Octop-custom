"""Build the shared native update helper and code-only companion archives."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUTHORITY = "https://120.79.0.171:18443"


def prepare(app: Path, version: str, platform: str) -> None:
    python_trust = json.loads(
        (ROOT.parent / "src/octop/infra/client_updates/trust.json").read_text()
    )
    native_trust = json.loads(
        (ROOT.parent / "desktop/src/internal/clientupdate/trust.json").read_text()
    )
    if python_trust != native_trust or not native_trust["authorities"].get(AUTHORITY):
        raise ValueError("Companion update signing keys must match the reviewed client trust")
    mac = platform.startswith("darwin-")
    resources = app / ("Contents/Resources" if mac else "resources")
    helper = app / ("Contents/Helpers/client-updater" if mac else "resources/client-updater.exe")
    helper.parent.mkdir(parents=True, exist_ok=True)
    archs = ["arm64", "amd64"] if platform == "darwin-universal" else [platform.split("-")[1]]
    built = []
    for arch in archs:
        binary = helper.with_name(helper.name + "-" + arch)
        env = {
            **os.environ,
            "GOOS": "darwin" if mac else "windows",
            "GOARCH": arch,
            "CGO_ENABLED": "0",
        }
        subprocess.run(
            [
                "go",
                "build",
                "-trimpath",
                "-ldflags=-s -w",
                "-o",
                str(binary),
                "./cmd/client-updater",
            ],
            cwd=ROOT.parent / "desktop/src",
            env=env,
            check=True,
        )
        built.append(binary)
    if len(built) == 2:
        subprocess.run(["lipo", "-create", *map(str, built), "-output", str(helper)], check=True)
    else:
        shutil.copy2(built[0], helper)
    for binary in built:
        binary.unlink()
    helper.chmod(0o755)
    (resources / "client-update-build.json").write_text(
        json.dumps(
            {
                "product": "octop-companion",
                "protocol": 1,
                "version": version,
                "authority": AUTHORITY,
            }
        )
        + "\n"
    )


def archive(app: Path, version: str, platform: str, output: Path) -> list[Path]:
    mac = platform.startswith("darwin-")
    platforms = ["darwin-arm64", "darwin-amd64"] if platform == "darwin-universal" else [platform]
    output.mkdir(parents=True, exist_ok=True)
    target = output / f"Dora-update-{platforms[0]}-{version}.zip"
    prefix = "Dora.app" if mac else "Dora"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for file in sorted(app.rglob("*")):
            name = prefix + "/" + file.relative_to(app).as_posix()
            if file.is_symlink():
                link = os.readlink(file)
                if (
                    not mac
                    or os.path.isabs(link)
                    or not file.resolve().is_relative_to(app.resolve())
                ):
                    raise ValueError("Companion package link escapes its application")
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                bundle.writestr(info, link)
            elif file.is_file():
                bundle.write(file, name)
    result = [target]
    for item in platforms[1:]:
        copied = output / f"Dora-update-{item}-{version}.zip"
        shutil.copy2(target, copied)
        result.append(copied)
    return result
