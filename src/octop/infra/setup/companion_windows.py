"""Windows companion installation; application replacement never touches member data."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import stat
import subprocess
import uuid
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from octop.infra.auth.enterprise import client_for
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.setup.companion_package import BUNDLE_ID, CompanionInstaller
from octop.infra.users.identity import User

if TYPE_CHECKING:
    from octop.infra.setup.companion import CompanionLauncher


def installed_version(path: Path) -> tuple[int, ...] | None:
    try:
        value = json.loads((path / "companion-version.json").read_text(encoding="utf-8"))
        if value.get("bundle_id") != BUNDLE_ID or not (path / "Dora.exe").is_file():
            return None
        version = str(value["version"])
        if not re.fullmatch(r"\d+\.\d+\.\d+", version):
            return None
        return tuple(int(part) for part in version.split("."))
    except (OSError, ValueError, KeyError):
        return None


def validate_archive(archive: Path) -> None:
    seen: set[str] = set()
    with zipfile.ZipFile(archive) as bundle:
        entries = bundle.infolist()
        if not entries or len(entries) > 100000 or sum(e.file_size for e in entries) > 3 * 1024**3:
            raise OctopError.localized(ErrorCode.COMPANION_INSTALL_FAILED)
        for entry in entries:
            original = entry.orig_filename
            parts = original.rstrip("/").split("/")
            key = "/".join(parts).casefold()
            if (
                parts[0] != "Dora"
                or original != entry.filename
                or key in seen
                or "\\" in original
                or any(
                    not p
                    or p in {".", ".."}
                    or re.search(r'[\x00-\x1f:<>"|?*]', p)
                    or p.endswith((".", " "))
                    or re.match(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)", p, re.I)
                    for p in parts
                )
                or stat.S_ISLNK(entry.external_attr >> 16)
            ):
                raise OctopError.localized(ErrorCode.COMPANION_INSTALL_FAILED)
            seen.add(key)


def install(archive: Path, metadata: CompanionInstaller, programs: Path) -> Path:
    validate_archive(archive)
    programs.mkdir(parents=True, exist_ok=True)
    stage = programs / (".dora-install-" + uuid.uuid4().hex)
    previous = programs / (".dora-previous-" + uuid.uuid4().hex)
    target = programs / "OctopCompanion"
    stage.mkdir()
    moved = False
    try:
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(stage)
        candidate = stage / "Dora"
        if installed_version(candidate) != tuple(int(x) for x in metadata.version.split(".")):
            raise OctopError.localized(ErrorCode.COMPANION_INSTALL_FAILED)
        if target.exists():
            if installed_version(target) is None or target.is_symlink():
                raise OctopError.localized(ErrorCode.COMPANION_INSTALL_FAILED)
            target.rename(previous)
            moved = True
        try:
            candidate.rename(target)
        except OSError:
            if moved:
                previous.rename(target)
            raise
        if moved:
            shutil.rmtree(previous, ignore_errors=True)
        return target
    finally:
        shutil.rmtree(stage, ignore_errors=True)


async def launch_windows(
    launcher: CompanionLauncher, user: User, action: Literal["open", "size"]
) -> dict[str, Any]:
    from octop.infra.setup.companion import companion_access

    async with launcher._lock:
        if not (await companion_access(launcher.server, user, force=True))["allowed"]:
            raise OctopError.localized(ErrorCode.COMPANION_ACCESS_DENIED)
        client = client_for(launcher.server)
        assert client is not None
        state = await asyncio.to_thread(client._state, user.id)
        metadata = CompanionInstaller.model_validate(
            await client._remote(
                "GET",
                "/api/enterprise/companion/installer?platform=windows-amd64",
                token=state["token"],
            )
        )
        metadata.verify()
        wanted = tuple(int(x) for x in metadata.version.split("."))
        programs = (
            Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "Programs"
        )
        target = programs / "OctopCompanion"
        actual = await asyncio.to_thread(installed_version, target)
        installed = False
        if actual is None or actual < wanted:
            archive = await launcher._download(user, metadata, component="windows-amd64")
            try:
                target = await asyncio.to_thread(install, archive, metadata, programs)
                actual = wanted
                installed = True
            except PermissionError:
                # A running older copy may hold files open. Open it and defer replacement.
                if actual is None:
                    raise OctopError.localized(ErrorCode.COMPANION_INSTALL_FAILED) from None
        if not (await companion_access(launcher.server, user, force=True))["allowed"]:
            raise OctopError.localized(ErrorCode.COMPANION_ACCESS_DENIED)
        try:
            await asyncio.to_thread(
                subprocess.Popen,
                [
                    str(target / "Dora.exe"),
                    "octop-companion://size" if action == "size" else "--show-chat",
                ],
                cwd=target,
                close_fds=True,
            )
        except OSError:
            raise OctopError.localized(ErrorCode.COMPANION_INSTALL_FAILED) from None
        assert actual is not None
        return {
            "opened": True,
            "installed": installed,
            "update_pending": actual < wanted,
            "version": ".".join(str(x) for x in actual),
        }
