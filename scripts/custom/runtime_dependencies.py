"""Verified PyPI wheel overlays for explicit portable platform compatibility.

No pip, build toolchain, installed user environment, or wheel code is executed.
Only the modules and metadata named in the reviewed lock can replace upstream files.
"""

from __future__ import annotations

import base64
import csv
import email
import hashlib
import io
import json
import re
import stat
import struct
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

LOCK_PATH = Path(__file__).with_name("runtime-dependencies.json")


def canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def validate_url(url: str, filename: str) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "files.pythonhosted.org"
        or parsed.query
        or parsed.fragment
        or not re.fullmatch(
            r"/packages/[0-9a-f]{2}/[0-9a-f]{2}/[0-9a-f]{60}/" + re.escape(filename), parsed.path
        )
    ):
        raise ValueError("Wheel URL must be an exact official PyPI file URL")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Wheel download redirects are refused")


def verify_download(path: Path, wheel: dict[str, Any]) -> None:
    if path.is_symlink() or not path.is_file() or path.stat().st_size != wheel["size"]:
        raise ValueError(f"Wheel size or file type mismatch: {path.name}")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != wheel["sha256"]:
        raise ValueError(f"Wheel SHA256 mismatch: {path.name}")


def obtain_wheel(wheel: dict[str, Any], cache: Path) -> Path:
    filename = wheel["filename"]
    if Path(filename).name != filename or not re.fullmatch(r"[A-Za-z0-9_.+-]+\.whl", filename):
        raise ValueError("Unsafe wheel filename")
    validate_url(wheel["url"], filename)
    if not re.fullmatch(r"[0-9a-f]{64}", wheel["sha256"]) or not 0 < wheel["size"] < 100_000_000:
        raise ValueError("Invalid locked wheel hash or size")
    cache.mkdir(parents=True, exist_ok=True)
    if cache.is_symlink():
        raise ValueError("Wheel cache must not be a symlink")
    destination = cache / filename
    if destination.exists() or destination.is_symlink():
        verify_download(destination, wheel)
        return destination
    temporary = cache / (filename + ".part")
    if temporary.exists() or temporary.is_symlink():
        raise ValueError("Review the unfinished wheel download before retrying")
    request = urllib.request.Request(wheel["url"], headers={"User-Agent": "Octop-custom-release"})
    try:
        with (
            urllib.request.build_opener(_NoRedirect()).open(request, timeout=60) as response,
            temporary.open("xb") as output,
        ):
            validate_url(response.geturl(), filename)
            received = 0
            while chunk := response.read(1024 * 1024):
                received += len(chunk)
                if received > wheel["size"]:
                    raise ValueError("Wheel download exceeded its locked size")
                output.write(chunk)
        verify_download(temporary, wheel)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def macho_targets(data: bytes) -> dict[str, str]:
    """Read each Mach-O slice's CPU and declared minimum macOS without executing it."""
    slices = [(0, len(data))]
    if data[:4] in (b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf"):
        wide = data[:4] == b"\xca\xfe\xba\xbf"
        count = struct.unpack_from(">I", data, 4)[0]
        if not 0 < count <= 8:
            raise ValueError("Invalid Mach-O architecture count")
        slices = []
        for number in range(count):
            position = 8 + number * (32 if wide else 20)
            offset, size = struct.unpack_from(">QQ" if wide else ">II", data, position + 8)
            if offset + size > len(data):
                raise ValueError("Mach-O slice exceeds its file")
            slices.append((offset, size))
    targets = {}
    for offset, size in slices:
        segment = data[offset : offset + size]
        if segment[:4] not in (b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf"):
            raise ValueError("Expected a 64-bit Mach-O native extension")
        endian = "<" if segment[:4] == b"\xcf\xfa\xed\xfe" else ">"
        cpu = struct.unpack_from(endian + "I", segment, 4)[0]
        name = {0x01000007: "x86_64", 0x0100000C: "arm64"}.get(cpu)
        if name is None or name in targets:
            raise ValueError("Unknown or duplicate Mach-O CPU")
        commands = struct.unpack_from(endian + "I", segment, 16)[0]
        position = 32
        minimum = None
        for _ in range(commands):
            command, length = struct.unpack_from(endian + "II", segment, position)
            if length < 8 or position + length > len(segment):
                raise ValueError("Invalid Mach-O load command")
            if command == 0x24:
                minimum = struct.unpack_from(endian + "I", segment, position + 8)[0]
            elif (
                command == 0x32 and struct.unpack_from(endian + "I", segment, position + 8)[0] == 1
            ):
                minimum = struct.unpack_from(endian + "I", segment, position + 12)[0]
            position += length
        if minimum is None:
            raise ValueError("Mach-O extension has no minimum macOS declaration")
        targets[name] = f"{minimum >> 16}.{(minimum >> 8) & 255}.{minimum & 255}"
    return targets


def replace_requirements(
    data: bytes, overrides: dict[str, list[str]]
) -> tuple[bytes, dict[str, Any]]:
    """Apply reviewed, exact dependency header changes; preserve all other metadata."""
    newline = b"\r\n" if b"\r\n" in data else b"\n"
    lines = data.splitlines(keepends=True)
    for original, replacements in overrides.items():
        if not replacements or any(
            "\n" in item or "\r" in item for item in [original, *replacements]
        ):
            raise ValueError("Invalid metadata requirement replacement")
        expected = b"Requires-Dist: " + original.encode()
        matches = [index for index, line in enumerate(lines) if line.rstrip(b"\r\n") == expected]
        if len(matches) != 1:
            raise ValueError(f"Review changed upstream metadata requirement: {original}")
        index = matches[0]
        if index + 1 < len(lines) and lines[index + 1].startswith((b" ", b"\t")):
            raise ValueError("Folded metadata requirement needs explicit review")
        lines[index] = b"".join(
            b"Requires-Dist: " + value.encode() + newline for value in replacements
        )
    updated = b"".join(lines)
    return updated, {
        "original_sha256": hashlib.sha256(data).hexdigest(),
        "sha256": hashlib.sha256(updated).hexdigest(),
        "requires_dist_overrides": overrides,
    }


def update_record(data: bytes, updates: dict[str, bytes]) -> bytes:
    records = list(csv.reader(io.StringIO(data.decode("utf-8"))))
    if len({row[0] for row in records}) != len(records):
        raise ValueError("Duplicate paths in distribution RECORD")
    for name, content in updates.items():
        matches = [row for row in records if row[0] == name]
        if len(matches) != 1:
            raise ValueError(f"Changed metadata is missing from its RECORD: {name}")
        digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode()
        matches[0][:] = [name, "sha256=" + digest, str(len(content))]
    result = io.StringIO()
    csv.writer(result).writerows(records)
    return result.getvalue().encode()


def wheel_files(
    path: Path, wheel: dict[str, Any], platform: str
) -> tuple[dict[str, bytes], dict[str, Any]]:
    verify_download(path, wheel)
    distribution = canonical_name(wheel["name"])
    dist_info = distribution.replace("-", "_") + "-" + wheel["version"] + ".dist-info"
    modules = set(wheel["modules"])
    if not modules or any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) for name in modules):
        raise ValueError("Invalid replacement module names")
    expected_filename = f"{distribution.replace('-', '_')}-{wheel['version']}-{wheel['tag']}.whl"
    if wheel["filename"] != expected_filename:
        raise ValueError("Locked wheel identity or tag mismatch")
    if platform != "darwin-amd64" or wheel["tag"] not in {
        "py3-none-any",
        "cp311-abi3-macosx_10_9_universal2",
        "cp312-cp312-macosx_10_13_x86_64",
    }:
        raise ValueError("Wheel is not approved for this Python 3.12 portable platform")
    files = {}
    native = {}
    with zipfile.ZipFile(path) as archive:
        for item in archive.infolist():
            parts = item.filename.rstrip("/").split("/")
            if (
                not item.filename
                or "\\" in item.filename
                or "\0" in item.filename
                or any(part in {"", ".", ".."} or ":" in part for part in parts)
                or PurePosixPath(item.filename).is_absolute()
                or stat.S_ISLNK(item.external_attr >> 16)
            ):
                raise ValueError(f"Unsafe wheel member: {item.filename}")
            if parts[0] not in modules | {dist_info}:
                raise ValueError(f"Unexpected wheel module or install scheme: {item.filename}")
            if item.is_dir():
                continue
            if item.filename in files or item.flag_bits & 1:
                raise ValueError(f"Duplicate or encrypted wheel member: {item.filename}")
            if (
                item.file_size > 100_000_000
                or sum(len(data) for data in files.values()) + item.file_size > 256_000_000
            ):
                raise ValueError("Wheel unpacked size exceeds the permitted limit")
            data = archive.read(item)
            files[item.filename] = data
            if item.filename.endswith((".so", ".dylib")):
                targets = macho_targets(data)
                if "x86_64" not in targets or tuple(map(int, targets["x86_64"].split("."))) > (
                    12,
                    0,
                    0,
                ):
                    raise ValueError("Native wheel extension requires unsupported Intel macOS")
                native[item.filename] = targets
        metadata = email.message_from_bytes(files[f"{dist_info}/METADATA"])
        tags = email.message_from_bytes(files[f"{dist_info}/WHEEL"]).get_all("Tag") or []
        if (
            canonical_name(metadata["Name"] or "") != distribution
            or metadata["Version"] != wheel["version"]
            or wheel["tag"] not in tags
        ):
            raise ValueError("Wheel metadata identity or compatibility tag mismatch")
        licenses = metadata.get_all("License-File") or []
        if not licenses or any(
            f"{dist_info}/{name}" not in files and f"{dist_info}/licenses/{name}" not in files
            for name in licenses
        ):
            raise ValueError("Wheel license files are missing")
        record_name = f"{dist_info}/RECORD"
        records = list(csv.reader(io.StringIO(files[record_name].decode("utf-8"))))
        if {row[0] for row in records} != set(files) or len(records) != len(files):
            raise ValueError("Wheel RECORD file set mismatch")
        for name, digest, size in records:
            if name == record_name and not digest and not size:
                continue
            actual = (
                "sha256="
                + base64.urlsafe_b64encode(hashlib.sha256(files[name]).digest())
                .rstrip(b"=")
                .decode()
            )
            if digest != actual or size != str(len(files[name])):
                raise ValueError(f"Wheel RECORD hash or size mismatch: {name}")
    provenance = {
        key: wheel[key]
        for key in ("name", "version", "filename", "url", "size", "sha256", "tag", "metadata_url")
    }
    provenance["native_macos_targets"] = native
    python_hashes = {
        name: hashlib.sha256(content).hexdigest()
        for name, content in files.items()
        if name.endswith(".py")
    }
    if wheel.get("requires_dist_overrides"):
        metadata_name = f"{dist_info}/METADATA"
        files[metadata_name], change = replace_requirements(
            files[metadata_name], wheel["requires_dist_overrides"]
        )
        previous_record = files[record_name]
        files[record_name] = update_record(previous_record, {metadata_name: files[metadata_name]})
        change["original_record_sha256"] = hashlib.sha256(previous_record).hexdigest()
        change["record_sha256"] = hashlib.sha256(files[record_name]).hexdigest()
        provenance["metadata_adjustment"] = change
    if python_hashes != {
        name: hashlib.sha256(content).hexdigest()
        for name, content in files.items()
        if name.endswith(".py")
    }:
        raise ValueError("Dependency metadata adjustment changed executable Python source")
    provenance["python_files_unchanged"] = len(python_hashes)
    provenance["python_source_tree_sha256"] = hashlib.sha256(
        json.dumps(python_hashes, sort_keys=True).encode()
    ).hexdigest()
    return files, provenance


class RuntimeDependencyOverlay:
    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.file_modes: dict[str, int] = {}
        self.distributions: set[str] = set()
        self.modules: set[str] = set()
        self.provenance: dict[str, Any] = {"wheels": []}

    def replaces(self, relative: str) -> bool:
        if relative in self.files:
            return True
        if not relative.startswith("packages/"):
            return False
        first = relative.removeprefix("packages/").split("/", 1)[0]
        return first in self.modules or any(
            first.startswith(name.replace("-", "_") + "-") and first.endswith(".dist-info")
            for name in self.distributions
        )


def prepare(platform: str, cache: Path, *, lock_path: Path = LOCK_PATH) -> RuntimeDependencyOverlay:
    overlay = RuntimeDependencyOverlay()
    raw = lock_path.read_bytes()
    lock = json.loads(raw)
    if lock["schema_version"] != 1:
        raise ValueError("Unknown runtime dependency lock schema")
    overlay.provenance["lock_sha256"] = hashlib.sha256(raw).hexdigest()
    overlay.provenance["platform"] = platform
    selected = lock["platforms"].get(platform, [])
    for wheel in selected:
        path = obtain_wheel(wheel, cache)
        files, provenance = wheel_files(path, wheel, platform)
        with zipfile.ZipFile(path) as archive:
            modes = {
                item.filename: 0o755 if (item.external_attr >> 16) & 0o111 else 0o644
                for item in archive.infolist()
                if not item.is_dir()
            }
        for name, data in files.items():
            relative = "packages/" + name
            if relative in overlay.files:
                raise ValueError(f"Runtime dependency collision: {relative}")
            overlay.files[relative] = data
            overlay.file_modes[relative] = modes[name]
        overlay.distributions.add(canonical_name(wheel["name"]))
        overlay.modules.update(wheel["modules"])
        overlay.provenance["wheels"].append(provenance)
    overlay.provenance["reason"] = (
        lock["reason"] if selected else "No supplemental dependencies on this platform"
    )
    if selected:
        overlay.provenance["compatibility_scope"] = lock["compatibility_scope"]
        overlay.provenance["sources"] = lock.get("sources", [])
    return overlay
