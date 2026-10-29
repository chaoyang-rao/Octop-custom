#!/usr/bin/env python3
"""Overlay the complete tracked custom packages onto verified official portables.

Only Python's standard library is needed. Never reads an installed ~/.octop.
The original archive's runtime, dependencies, permissions and symlinks survive.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import posixpath
import shutil
import stat
import struct
import subprocess
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = Path(__file__).with_name("upstream-lock.json")
PACKAGE_NAMES = ("octop", "octop_harness", "octop_gateway")
CHUNK_SIZE = 1024 * 1024


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_source(path: Path, asset: dict[str, Any]) -> None:
    if path.stat().st_size != asset["size"]:
        raise ValueError(f"Official archive size mismatch: {path.name}")
    if sha256_file(path) != asset["sha256"]:
        raise ValueError(f"Official archive SHA256 mismatch: {path.name}")


def obtain_source(platform: str, lock: dict[str, Any], cache: Path) -> Path:
    asset = lock["assets"][platform]
    cache.mkdir(parents=True, exist_ok=True)
    destination = cache / asset["name"]
    if destination.exists():
        verify_source(destination, asset)
        print(f"Verified cached official archive: {destination}", flush=True)
        return destination
    installed = Path("/Applications/Octop.app/Contents/Resources/Octop-darwin-arm64.zip")
    if platform == "darwin-arm64" and installed.is_file():
        try:
            verify_source(installed, asset)
        except ValueError:
            pass  # An unrelated installed app is not an input to this build.
        else:
            temporary = destination.with_suffix(".zip.part")
            try:
                shutil.copyfile(installed, temporary)
                verify_source(temporary, asset)
                temporary.replace(destination)
            finally:
                temporary.unlink(missing_ok=True)
            print(f"Verified official archive copied from Octop.app: {destination}", flush=True)
            return destination
    temporary = destination.with_suffix(".zip.part")
    print(f"Downloading official {asset['name']} ({asset['size']} bytes)...", flush=True)
    request = urllib.request.Request(asset["url"], headers={"User-Agent": "Octop-custom-release"})
    try:
        # urlopen honors the platform/environment proxy configuration.
        with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as out:
            received = 0
            while chunk := response.read(CHUNK_SIZE):
                received += len(chunk)
                if received > asset["size"]:
                    raise ValueError("Official download exceeded its locked size")
                out.write(chunk)
        verify_source(temporary, asset)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"Downloaded and verified: {destination}", flush=True)
    return destination


def safe_archive_name(name: str, root: str) -> str:
    """Reject ambiguous paths, absolute paths and traversal even without extracting."""
    parts = name.rstrip("/").split("/")
    if (
        not name
        or "\\" in name
        or "\x00" in name
        or any(part in ("", ".", "..") or ":" in part for part in parts)
        or parts[0] != root
    ):
        raise ValueError(f"Unsafe archive member: {name!r}")
    return name


def binary_architecture(data: bytes) -> str:
    """Read PE COFF or Mach-O CPU type without executing the bundled binary."""
    if data[:2] == b"MZ" and len(data) >= 64:
        offset = struct.unpack_from("<I", data, 0x3C)[0]
        if offset + 6 <= len(data) and data[offset : offset + 4] == b"PE\x00\x00":
            machine = struct.unpack_from("<H", data, offset + 4)[0]
            if machine == 0x8664:
                return "windows-amd64"
    magic = data[:4]
    if len(data) >= 8 and magic in (b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf"):
        endian = "<" if magic == b"\xcf\xfa\xed\xfe" else ">"
        cpu = struct.unpack_from(f"{endian}I", data, 4)[0]
        if cpu == 0x01000007:
            return "darwin-amd64"
        if cpu == 0x0100000C:
            return "darwin-arm64"
    raise ValueError("Unrecognized or unsupported bundled Python architecture")


def read_linked_member(archive: zipfile.ZipFile, name: str, root: str) -> bytes:
    visited: set[str] = set()
    while True:
        safe_archive_name(name, root)
        if name in visited:
            raise ValueError(f"Archive symlink cycle: {name}")
        visited.add(name)
        info = archive.getinfo(name)
        data = archive.read(info)
        if not stat.S_ISLNK(info.external_attr >> 16):
            return data
        target = data.decode("utf-8")
        if target.startswith("/") or "\\" in target or ":" in target:
            raise ValueError(f"Unsafe Python symlink: {name}")
        name = posixpath.normpath(posixpath.join(posixpath.dirname(name), target))


def validate_archive(archive: zipfile.ZipFile, platform: str, version: str) -> dict[str, str]:
    root = f"Octop-{platform}"
    names: set[str] = set()
    for info in archive.infolist():
        safe_archive_name(info.filename, root)
        if info.filename in names:
            raise ValueError(f"Duplicate archive member: {info.filename}")
        names.add(info.filename)
    values = dict(
        line.split("=", 1)
        for line in archive.read(f"{root}/VERSION.txt").decode("utf-8").splitlines()
        if "=" in line
    )
    if values.get("platform") != platform or values.get("octop_version") != version:
        raise ValueError("VERSION.txt platform/version does not match the release lock")
    interpreter = "runtime/python.exe" if platform == "windows-amd64" else "runtime/bin/python3"
    actual = binary_architecture(read_linked_member(archive, f"{root}/{interpreter}", root))
    if actual != platform:
        raise ValueError(f"Bundled Python architecture mismatch: expected {platform}, got {actual}")
    bad = archive.testzip()
    if bad:
        raise ValueError(f"Archive CRC mismatch: {bad}")
    return values


def collect_overlay(overlay_root: Path) -> dict[str, Path]:
    """Allow only the three code packages; do not traverse user data or symlinks."""
    files: dict[str, Path] = {}
    for package in PACKAGE_NAMES:
        package_dir = overlay_root / package
        if package_dir.is_symlink() or not package_dir.is_dir():
            raise ValueError(f"Missing or linked custom package: {package}")
        if not (package_dir / "__init__.py").is_file():
            raise ValueError(f"Incomplete custom package: {package}")
        for directory, dirnames, filenames in os.walk(package_dir, followlinks=False):
            dirnames[:] = sorted(name for name in dirnames if name != "__pycache__")
            for dirname in dirnames:
                if (Path(directory) / dirname).is_symlink():
                    raise ValueError(f"Linked custom package directory: {dirname}")
            for filename in sorted(filenames):
                if filename == ".DS_Store" or filename.endswith(".pyc"):
                    continue
                path = Path(directory) / filename
                if path.is_symlink() or not path.is_file():
                    raise ValueError(f"Non-regular custom package file: {path}")
                relative = "packages/" + path.relative_to(overlay_root).as_posix()
                safe_archive_name("root/" + relative, "root")
                files[relative] = path
    return dict(sorted(files.items()))


def custom_launch(original: bytes) -> bytes:
    newline = b"\r\n" if b"\r\n" in original else b"\n"
    anchor = b"def main() -> None:" + newline
    if original.count(anchor) != 1 or b"import os" + newline not in original:
        raise ValueError("Official launch.py layout changed; review the custom launch patch")
    return original.replace(
        anchor, anchor + b'    os.environ["OCTOP_CUSTOM_BUILD"] = "1"' + newline, 1
    )


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def git_revision(repo_root: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo_root, text=True, timeout=15
    ).strip()


def git_is_dirty(repo_root: Path) -> bool:
    return bool(
        subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=normal"],
            cwd=repo_root,
            text=True,
            timeout=15,
        ).strip()
    )


def readme(platform: str, lock: dict[str, Any]) -> bytes:
    return (
        f"Octop 定制便携版 {lock['custom_version']} ({platform})\n"
        f"基于官方 {lock['upstream_version']}，源码许可证 MIT。\n\n"
        "请完整解压到可写目录后启动，不要直接在 ZIP 内运行。\n"
        "macOS：终端运行 bash start.sh；Windows：双击 start.bat。\n"
        "启动脚本、Python 解释器和各平台原生依赖保留官方版本。\n"
        "定制代码包含在 packages/octop、octop_harness、octop_gateway。\n"
        "本包不包含用户数据库、工作区、登录态、密钥或个人配置。\n"
        "便携版默认数据在解压目录 data/；读取原数据需显式传 --home 指向原目录。\n"
        "定制版关闭官方自动更新，避免覆盖定制功能。\n\n"
        "复现构建（源码仓库，Python 3.12+，无需安装依赖）：\n"
        f"python scripts/custom/build_portable.py --platform {platform} --output dist\n"
        "官方输入文件的固定版本、大小和 SHA256：scripts/custom/upstream-lock.json\n"
        "定制文件的逐文件 SHA256：custom-release-manifest.json\n"
        "恢复时使用同版本源码中的 customization/packages，与清单逐文件核验；\n"
        "请先备份本机用户数据，不要用官方在线更新替换此定制包。\n"
    ).encode()


def build_archive(
    source_zip: Path,
    destination: Path,
    platform: str,
    overlay_root: Path,
    lock: dict[str, Any],
    git_commit: str,
    git_dirty: bool = False,
) -> dict[str, Any]:
    asset = lock["assets"][platform]
    verify_source(source_zip, asset)
    files = collect_overlay(overlay_root)
    hashes = {name: sha256_file(path) for name, path in files.items()}
    root = f"Octop-{platform}"
    manifest = {
        "schema_version": 1,
        "upstream_version": lock["upstream_version"],
        "custom_version": lock["custom_version"],
        "upstream_commit": lock["upstream_commit"],
        "git_commit": git_commit,
        "git_dirty": git_dirty,
        "platform": platform,
        "upstream_archive_sha256": asset["sha256"],
        "package_file_sha256": hashes,
    }
    manifest_data = json_bytes(manifest)
    marker = {
        "upstream_version": lock["upstream_version"],
        "custom_version": lock["custom_version"],
        "git_commit": git_commit,
        "git_dirty": git_dirty,
        "manifest": "custom-release-manifest.json",
        "manifest_sha256": hashlib.sha256(manifest_data).hexdigest(),
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".zip.part")
    retained: dict[str, tuple[int, int, int]] = {}
    try:
        with zipfile.ZipFile(source_zip) as original:
            validate_archive(original, platform, lock["upstream_version"])
            replacement = {
                "launch.py": custom_launch(original.read(f"{root}/launch.py")),
                "VERSION.txt": original.read(f"{root}/VERSION.txt").replace(
                    f"octop_version={lock['upstream_version']}".encode(),
                    f"octop_version={lock['custom_version']}".encode(),
                    1,
                ),
                "custom-release-manifest.json": manifest_data,
                "packages/octop-custom-release.json": json_bytes(marker),
                "CUSTOM-README.txt": readme(platform, lock),
            }
            package_prefixes = tuple(f"packages/{name}/" for name in PACKAGE_NAMES)
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as output:
                output.comment = original.comment
                for info in original.infolist():
                    relative = info.filename[len(root) + 1 :]
                    if relative.startswith(package_prefixes):
                        continue
                    if relative in replacement:
                        output.writestr(copy.copy(info), replacement.pop(relative))
                        continue
                    with original.open(info) as src, output.open(copy.copy(info), "w") as dst:
                        shutil.copyfileobj(src, dst, CHUNK_SIZE)
                    retained[info.filename] = (info.CRC, info.file_size, info.external_attr)
                for name, data in replacement.items():
                    output.writestr(f"{root}/{name}", data)
                for name, path in files.items():
                    output.write(path, f"{root}/{name}")
        with zipfile.ZipFile(temporary) as output:
            validate_archive(output, platform, lock["custom_version"])
            output_names = set(output.namelist())
            actual_overlay = {
                name[len(root) + 1 :]
                for name in output_names
                if name[len(root) + 1 :].startswith(package_prefixes) and not name.endswith("/")
            }
            if actual_overlay != set(files):
                raise ValueError("Custom package file set mismatch after ZIP build")
            for name, expected in hashes.items():
                with output.open(f"{root}/{name}") as stream:
                    actual = hashlib.file_digest(stream, "sha256").hexdigest()
                if actual != expected:
                    raise ValueError(f"Custom package SHA256 mismatch: {name}")
            for name, expected_metadata in retained.items():
                info = output.getinfo(name)
                if (info.CRC, info.file_size, info.external_attr) != expected_metadata:
                    raise ValueError(f"Original archive entry changed: {name}")
            if output.read(f"{root}/custom-release-manifest.json") != manifest_data:
                raise ValueError("Custom release manifest changed after ZIP build")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    report = {
        "artifact": destination.name,
        "size": destination.stat().st_size,
        "sha256": sha256_file(destination),
        "platform": platform,
        "upstream_version": lock["upstream_version"],
        "custom_version": lock["custom_version"],
        "git_commit": git_commit,
        "git_dirty": git_dirty,
        "upstream_archive_sha256": asset["sha256"],
        "verification": {
            "zip_crc": "passed",
            "runtime_architecture": platform,
            "overlay_files_verified": len(hashes),
            "preserved_original_entries": len(retained),
            "manifest_sha256": marker["manifest_sha256"],
        },
    }
    destination.with_suffix(".json").write_bytes(json_bytes(report))
    return report


def main() -> None:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", required=True, choices=tuple(lock["assets"]))
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "dist")
    parser.add_argument(
        "--source-zip", type=Path, help="Use an existing SHA256-locked official ZIP"
    )
    parser.add_argument(
        "--download-only", action="store_true", help="Only fetch/verify the official ZIP"
    )
    args = parser.parse_args()
    try:
        source = args.source_zip
        if source is None:
            source = obtain_source(args.platform, lock, REPO_ROOT / ".cache/custom-release")
        else:
            verify_source(source, lock["assets"][args.platform])
        if args.download_only:
            print(source.resolve())
            return
        destination = args.output / f"Octop-portable-{args.platform}-{lock['custom_version']}.zip"
        print(f"Building custom {args.platform} portable...", flush=True)
        report = build_archive(
            source,
            destination,
            args.platform,
            REPO_ROOT / "customization/packages",
            lock,
            git_revision(REPO_ROOT),
            git_is_dirty(REPO_ROOT),
        )
        print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, subprocess.SubprocessError) as error:
        parser.exit(1, f"Build refused: {error}\n")


if __name__ == "__main__":
    main()
