"""Pinned archive verification and inert extraction; no installer scripts run."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
import os
import shutil
import stat
import tarfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from octop.infra.agents.native_cli.config import NativeCLIError

_MAX_EXPANDED = 1024 * 1024 * 1024


def digest_file(path: Path, algorithm: str = "sha256") -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_artifact(path: Path, artifact: dict[str, Any]) -> None:
    if path.stat().st_size != int(artifact["size"]):
        raise NativeCLIError("managed_integrity")
    if artifact.get("sha256"):
        valid = digest_file(path) == artifact["sha256"]
    else:
        integrity = str(artifact.get("integrity") or "")
        try:
            algorithm, expected = integrity.split("-", 1)
            valid = (
                algorithm in {"sha256", "sha512"}
                and digest_file(path, algorithm) == base64.b64decode(expected, validate=True).hex()
            )
        except (ValueError, TypeError):
            valid = False
    if not valid:
        raise NativeCLIError("managed_integrity")


def artifact_identity(artifact: dict[str, Any]) -> str:
    return str(
        artifact.get("sha256") or hashlib.sha256(str(artifact["integrity"]).encode()).hexdigest()
    )[:12]


def safe_relative(value: str) -> Path:
    relative = PurePosixPath(value.replace("\\", "/"))
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or any(":" in part for part in relative.parts)
    ):
        raise NativeCLIError("managed_unsafe_archive")
    return Path(*relative.parts)


def extract_tree(
    archive: Path,
    destination: Path,
    archive_format: str,
    *,
    strip_prefix: str = "",
    skip_internal_links: bool = False,
) -> list[Path]:
    """No links are created. Node's known internal npm links may be skipped.

    Every link target is checked even when skipped; traversal/absolute targets
    are rejected. Duplicate files and writes outside the target are refused.
    """
    files: list[Path] = []
    expanded = 0
    destination.mkdir(parents=True, exist_ok=True)
    prefix = safe_relative(strip_prefix) if strip_prefix else None

    def target(name: str, size: int, directory: bool) -> Path | None:
        nonlocal expanded
        relative = safe_relative(name)
        if prefix is not None:
            if relative == prefix and directory:
                return None
            if not relative.is_relative_to(prefix):
                raise NativeCLIError("managed_unsafe_archive")
            relative = relative.relative_to(prefix)
        result = destination / relative
        if not result.resolve().is_relative_to(destination.resolve()):
            raise NativeCLIError("managed_unsafe_archive")
        expanded += size
        if size < 0 or expanded > _MAX_EXPANDED:
            raise NativeCLIError("managed_unsafe_archive")
        if directory:
            result.mkdir(parents=True, exist_ok=True)
        else:
            if result.exists() or not relative.parts:
                raise NativeCLIError("managed_unsafe_archive")
            result.parent.mkdir(parents=True, exist_ok=True)
            files.append(result)
        return result

    def copy(incoming: Any, path: Path, mode: int) -> None:
        with incoming, path.open("xb") as outgoing:
            shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
        path.chmod(0o755 if mode & 0o111 else 0o644)

    if archive_format == "binary":
        path = target("binary", archive.stat().st_size, False)
        assert path is not None
        copy(archive.open("rb"), path, 0o755)
    elif archive_format == "zip":
        with zipfile.ZipFile(archive) as source:
            if len(source.infolist()) > 20000:
                raise NativeCLIError("managed_unsafe_archive")
            for member in source.infolist():
                mode = member.external_attr >> 16
                if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR}):
                    raise NativeCLIError("managed_unsafe_archive")
                path = target(member.filename, member.file_size, member.is_dir())
                if path is not None and not member.is_dir():
                    copy(source.open(member), path, mode)
    elif archive_format in {"tar.gz", "tar.xz"}:
        with tarfile.open(archive, "r:*") as tar_source:
            members = tar_source.getmembers()
            if len(members) > 20000:
                raise NativeCLIError("managed_unsafe_archive")
            for tar_member in members:
                if tar_member.issym() or tar_member.islnk():
                    if not skip_internal_links:
                        raise NativeCLIError("managed_unsafe_archive")
                    link = PurePosixPath(tar_member.linkname.replace("\\", "/"))
                    owner = safe_relative(tar_member.name)
                    if prefix is not None:
                        if not owner.is_relative_to(prefix):
                            raise NativeCLIError("managed_unsafe_archive")
                        owner = owner.relative_to(prefix)
                    base = destination / owner.parent if tar_member.issym() else destination
                    resolved = (base / str(link)).resolve()
                    if (
                        link.is_absolute()
                        or any(":" in part for part in link.parts)
                        or not resolved.is_relative_to(destination.resolve())
                    ):
                        raise NativeCLIError("managed_unsafe_archive")
                    continue
                if not (tar_member.isdir() or tar_member.isfile()):
                    raise NativeCLIError("managed_unsafe_archive")
                path = target(tar_member.name, tar_member.size, tar_member.isdir())
                if path is not None and tar_member.isfile():
                    incoming = tar_source.extractfile(tar_member)
                    if incoming is None:
                        raise NativeCLIError("managed_unsafe_archive")
                    copy(incoming, path, tar_member.mode)
    else:
        raise NativeCLIError("managed_unsafe_archive")
    return files


def tree_manifest(root: Path) -> dict[str, str]:
    files = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise NativeCLIError("managed_modified")
        if path.is_file():
            files[path.relative_to(root).as_posix()] = digest_file(path)
    return files


def verify_tree(root: Path, expected: dict[str, str]) -> bool:
    return root.is_dir() and tree_manifest(root) == expected


def platform_matches(row: dict[str, Any], platform_id: str) -> bool:
    operating_system, architecture = platform_id.rsplit("-", 1)
    system = {"windows": "win32", "linux-musl": "linux"}.get(operating_system, operating_system)
    cpu = "x64" if architecture == "amd64" else architecture
    for key, actual in (
        ("os", system),
        ("cpu", cpu),
        ("libc", "musl" if "musl" in operating_system else "glibc"),
    ):
        choices = row.get(key)
        if isinstance(choices, list) and (
            actual in {str(c).removeprefix("!") for c in choices if str(c).startswith("!")}
            or (any(not str(c).startswith("!") for c in choices) and actual not in choices)
        ):
            return False
    return True


async def install_component(
    descriptor: dict[str, Any],
    *,
    content: Path,
    download_file: Path,
    downloader: Any,
) -> list[Path]:
    await downloader(descriptor["url"], download_file, size_limit=int(descriptor["size"]))
    await asyncio.to_thread(verify_artifact, download_file, descriptor)
    destination = content / safe_relative(str(descriptor.get("target") or ""))
    files = await asyncio.to_thread(
        extract_tree,
        download_file,
        destination,
        descriptor["archive"],
        strip_prefix=str(descriptor.get("strip_prefix") or ""),
        skip_internal_links=bool(descriptor.get("skip_internal_links", False)),
    )
    for relative, expected in descriptor.get("checks", {}).items():
        path = destination / safe_relative(relative)
        if (
            not await asyncio.to_thread(path.is_file)
            or await asyncio.to_thread(digest_file, path) != expected
        ):
            raise NativeCLIError("managed_integrity")
    await asyncio.to_thread(download_file.unlink)
    return files


def locked_components(release: dict[str, Any], platform_id: str) -> list[dict[str, Any]]:
    name = release.get("npm_lock")
    if not name:
        return []
    path = Path(__file__).with_name("managed_locks") / safe_relative(str(name))
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != release["npm_lock_sha256"]:
        raise NativeCLIError("managed_integrity")
    lock = json.loads(raw)
    packages = lock["packages"]
    if len(packages) > 200:
        raise NativeCLIError("managed_integrity")
    prefix = safe_relative(str(release.get("lock_target") or "app"))
    skip = release.get("skip_locked") or []
    result = []
    for relative, row in packages.items():
        if relative in skip or not platform_matches(row, platform_id):
            continue
        if not relative.startswith("node_modules/"):
            raise NativeCLIError("managed_integrity")
        result.append(
            {
                **row,
                "target": (prefix / safe_relative(relative)).as_posix(),
                "strip_prefix": "package",
                "archive": "tar.gz",
            }
        )
    return result


async def download_license(
    release: dict[str, Any], content: Path, stage: Path, downloader: Any
) -> None:
    license_file = content / "OCTOP-UPSTREAM-LICENSE.txt"
    if release.get("license_archive"):
        descriptor = release["license_archive"]
        files = await install_component(
            descriptor,
            content=stage / "license-source",
            download_file=stage / ".license-download",
            downloader=downloader,
        )
        source = stage / "license-source" / safe_relative(descriptor["member"])
        if source not in files:
            raise NativeCLIError("managed_integrity")
        await asyncio.to_thread(shutil.copyfile, source, license_file)
    else:
        await downloader(release["license_url"], license_file, size_limit=1024 * 1024)
    if await asyncio.to_thread(digest_file, license_file) != release["license_sha256"]:
        raise NativeCLIError("managed_integrity")


async def decode_brotli(node: Path, source: Path, destination: Path) -> None:
    """Use the hash-verified private Node runtime's built-in codec only.

    No vendor CLI, lifecycle scripts, shell, modules, NODE_OPTIONS, profiles or
    login files execute. The fixed transform bounds output and creates a new
    file atomically inside the installation stage.
    """
    script = """
const fs = require('node:fs');
const zlib = require('node:zlib');
const { pipeline, Transform } = require('node:stream');
let count = 0;
const bound = new Transform({ transform(chunk, encoding, done) {
  count += chunk.length;
  done(count > 536870912 ? new Error('limit') : null, chunk);
}});
pipeline(fs.createReadStream(process.argv[1]), zlib.createBrotliDecompress(), bound,
  fs.createWriteStream(process.argv[2], { flags: 'wx', mode: 0o755 }),
  error => { if (error) process.exitCode = 1; });
"""
    env = {
        key: os.environ[key] for key in ("SYSTEMROOT", "SystemRoot", "WINDIR") if key in os.environ
    }
    process = await asyncio.create_subprocess_exec(
        str(node),
        "--input-type=commonjs",
        "-e",
        script,
        str(source),
        str(destination),
        env=env,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        result = await asyncio.wait_for(process.wait(), 120)
        if result != 0 or not await asyncio.to_thread(destination.is_file):
            raise NativeCLIError("managed_integrity")
        await asyncio.to_thread(destination.chmod, 0o755)
    finally:
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            await process.wait()
