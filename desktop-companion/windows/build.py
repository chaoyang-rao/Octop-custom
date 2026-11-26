"""Assemble Windows Dora with the pinned native KuroCat renderer and independent engine."""

from pathlib import Path
import json
import shutil
import struct
import subprocess
import zlib
import sys

ROOT = Path(__file__).resolve().parent
COMPANION = ROOT.parent
BUILD = COMPANION / "build/windows"
VERSION = json.loads((ROOT / "package.json").read_text())["version"]
sys.path.insert(0, str(COMPANION / "scripts"))
from companion_updates import prepare as prepare_update


def icon() -> bytes:
    rows = []
    for y in range(32):
        row = bytearray()
        for x in range(32):
            inside = (x - 16) ** 2 + (y - 15) ** 2 < 14**2 or (5 <= x <= 12 and 20 <= y <= 28)
            eye = (x - 11) ** 2 + (y - 14) ** 2 <= 3 or (x - 21) ** 2 + (y - 14) ** 2 <= 3
            row.extend(
                (255, 255, 255, 255) if eye else (22, 138, 194, 255) if inside else (0, 0, 0, 0)
            )
        rows.append(b"\x00" + row)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 32, 32, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"".join(rows)))
        + chunk(b"IEND", b"")
    )


def main() -> None:
    target = BUILD / "Dora"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(ROOT / "node_modules/electron/dist", target)
    (target / "electron.exe").rename(target / "Dora.exe")
    app = target / "resources/app"
    app.mkdir(parents=True)
    for pattern in ("*.cjs", "*.html", "*.js", "package.json", "package-lock.json"):
        for file in ROOT.glob(pattern):
            shutil.copy2(file, app / file.name)
    # Install only locked runtime JS dependencies; Electron itself lives outside app/.
    subprocess.run(
        [
            shutil.which("npm.cmd") or "npm",
            "ci",
            "--omit=dev",
            "--ignore-scripts",
            "--prefix",
            str(app),
        ],
        check=True,
    )
    resources = target / "resources"
    shutil.copytree(COMPANION / "dist/web", resources / "web")
    shutil.copytree(COMPANION / "build/windows-engine", resources / "engine")
    shutil.copy2(COMPANION / "scripts/engine_entry.py", resources / "engine_entry.py")
    shutil.copy2(COMPANION / "build/DoraSpeech.exe", resources / "DoraSpeech.exe")
    shutil.copy2(COMPANION / "build/kurocat-windows/Release/DoraKuroCat.exe", resources / "DoraKuroCat.exe")
    shutil.copy2(ROOT / "native/kurocat/LICENSE", resources / "KuroCat-LICENSE.txt")
    shutil.copy2(ROOT / "native/kurocat/UPSTREAM.json", resources / "KuroCat-UPSTREAM.json")
    shutil.copy2(ROOT / "使用说明.txt", resources / "使用说明.txt")
    shutil.copy2(ROOT / "ASSET-NOTICE.txt", resources / "ASSET-NOTICE.txt")
    png = icon()
    (resources / "tray.png").write_bytes(png)
    (BUILD / "dora.ico").write_bytes(
        struct.pack("<HHH", 0, 1, 1)
        + struct.pack("<BBBBHHII", 32, 32, 0, 0, 1, 32, len(png), 22)
        + png
    )
    (target / "companion-version.json").write_text(
        json.dumps({"bundle_id": "com.chaoyangrao.octop.companion", "version": VERSION}),
        encoding="utf-8",
    )
    # Engine and application contain no member data, log files or private artwork.
    assert not list(target.rglob("pet.json"))
    prepare_update(target, VERSION, "windows-amd64")
    public_zip = shutil.make_archive(str(BUILD / ("Dora-Windows-x64-" + VERSION)), "zip", BUILD, "Dora")
    shutil.copy2(public_zip, BUILD / f"Dora-update-windows-amd64-{VERSION}.zip")
    print(
        json.dumps(
            {"version": VERSION, "renderer": "chanke17/KuroCat native Windows", "internal_artwork_included": False, "member_data_included": False}
        )
    )


if __name__ == "__main__":
    main()
