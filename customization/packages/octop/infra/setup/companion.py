"""One-click, explicitly requested installation/launch of the independent Mac pet."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import plistlib
import shutil
import stat
import subprocess
import sys
import uuid
import zipfile
from pathlib import Path
from typing import Any, Literal

import anyio
import httpx

from octop.infra.auth.enterprise import client_for
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.setup.companion_package import BUNDLE_ID, CompanionInstaller
from octop.infra.users.identity import User


async def companion_access(server: Any, user: User, *, force: bool = False) -> dict[str, Any]:
    client = client_for(server)
    if client is None:
        raise OctopError.localized(ErrorCode.ENTERPRISE_NOT_CONFIGURED)
    await client.authorize(user, force=force)
    status = client.cached_member_access(user.id)
    return {
        "allowed": status.get("companion") is True if status else True,
        "managed": bool(status and status.get("configured")),
        "supported": sys.platform in {"darwin", "win32"},
    }


def validate_archive(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if not entries or len(entries) > 200000 or sum(e.file_size for e in entries) > 2 * 1024**3:
            raise OctopError.localized(ErrorCode.COMPANION_INSTALL_FAILED)
        for entry in entries:
            parts = entry.filename.split("/")
            if (
                parts[0] not in {"哆啦.app", "__MACOSX"}
                or entry.filename.startswith("/")
                or ".." in parts
                or "\\" in entry.filename
                or stat.S_ISLNK(entry.external_attr >> 16)
            ):
                raise OctopError.localized(ErrorCode.COMPANION_INSTALL_FAILED)


def installed_version(path: Path) -> tuple[int, ...] | None:
    info = path / "Contents/Info.plist"
    if not info.is_file():
        return None
    try:
        value = plistlib.loads(info.read_bytes())
        if value.get("CFBundleIdentifier") != BUNDLE_ID:
            return None
        return tuple(int(part) for part in value["CFBundleShortVersionString"].split("."))
    except (ValueError, KeyError, plistlib.InvalidFileException):
        return None


class CompanionLauncher:
    def __init__(self, server: Any) -> None:
        self.server = server
        self._lock = asyncio.Lock()

    async def _download(
        self,
        user: User,
        metadata: CompanionInstaller,
        *,
        component: Literal["macos", "windows-amd64", "artwork"] = "macos",
    ) -> Path:
        client = client_for(self.server)
        if client is None:
            raise OctopError.localized(ErrorCode.ENTERPRISE_NOT_CONFIGURED)
        state = await asyncio.to_thread(client._state, user.id)
        folder = Path(self.server.paths.root) / "downloads" / "companion"
        await asyncio.to_thread(folder.mkdir, mode=0o700, parents=True, exist_ok=True)
        path = folder / metadata.filename

        def verified() -> bool:
            if not path.is_file() or path.is_symlink() or path.stat().st_size != metadata.size:
                return False
            with path.open("rb") as stream:
                return hashlib.file_digest(stream, "sha256").hexdigest() == metadata.sha256

        if await asyncio.to_thread(verified):
            return path
        temporary = folder / (metadata.filename + "." + uuid.uuid4().hex + ".part")
        total = 0
        digest = hashlib.sha256()
        try:
            async with (
                httpx.AsyncClient(
                    trust_env=False, follow_redirects=False, timeout=httpx.Timeout(120, connect=10)
                ) as transport,
                transport.stream(
                    "GET",
                    client.authority
                    + (
                        "/api/enterprise/companion/artwork/file"
                        if component == "artwork"
                        else "/api/enterprise/companion/installer/file"
                        + ("?platform=windows-amd64" if component == "windows-amd64" else "")
                    ),
                    headers={"Authorization": "Bearer " + state["token"]},
                ) as response,
            ):
                response.raise_for_status()
                async with await anyio.open_file(temporary, "wb") as stream:
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > metadata.size:
                            raise OctopError.localized(ErrorCode.COMPANION_INSTALL_FAILED)
                        digest.update(chunk)
                        await stream.write(chunk)
            if total != metadata.size or digest.hexdigest() != metadata.sha256:
                raise OctopError.localized(ErrorCode.COMPANION_INSTALL_FAILED)
            await asyncio.to_thread(temporary.replace, path)
            return path
        except httpx.HTTPError:
            raise OctopError.localized(ErrorCode.COMPANION_INSTALL_FAILED) from None
        finally:
            await asyncio.to_thread(temporary.unlink, missing_ok=True)

    async def artwork(self, user: User) -> tuple[CompanionInstaller, Path]:
        async with self._lock:
            access = await companion_access(self.server, user, force=True)
            if not access["allowed"]:
                raise OctopError.localized(ErrorCode.COMPANION_ACCESS_DENIED)
            client = client_for(self.server)
            assert client is not None
            state = await asyncio.to_thread(client._state, user.id)
            metadata = CompanionInstaller.model_validate(
                await client._remote(
                    "GET", "/api/enterprise/companion/artwork", token=state["token"]
                )
            )
            metadata.verify()
            return metadata, await self._download(user, metadata, component="artwork")

    def _install(self, archive: Path, metadata: CompanionInstaller) -> Path:
        validate_archive(archive)
        apps = Path.home() / "Applications"
        apps.mkdir(parents=True, exist_ok=True)
        stage = apps / (".dora-install-" + uuid.uuid4().hex)
        stage.mkdir(mode=0o700)
        target = apps / "哆啦.app"
        previous = apps / (".dora-previous-" + uuid.uuid4().hex + ".app")
        try:
            subprocess.run(
                ["/usr/bin/ditto", "-x", "-k", str(archive), str(stage)],
                check=True,
                capture_output=True,
                timeout=120,
            )
            candidate = stage / "哆啦.app"
            expected = tuple(int(x) for x in metadata.version.split("."))
            if installed_version(candidate) != expected:
                raise OctopError.localized(ErrorCode.COMPANION_INSTALL_FAILED)
            subprocess.run(
                ["/usr/bin/codesign", "--verify", "--deep", "--strict", str(candidate)],
                check=True,
                capture_output=True,
                timeout=60,
            )
            if target.exists():
                if installed_version(target) is None:
                    raise OctopError.localized(ErrorCode.COMPANION_INSTALL_FAILED)
                target.rename(previous)
            try:
                candidate.rename(target)
            except BaseException:
                if previous.exists():
                    previous.rename(target)
                raise
            receipt = self.server.paths.root / "companion-installation.json"
            receipt.write_text(
                json.dumps(
                    {"version": metadata.version, "sha256": metadata.sha256, "path": str(target)},
                    ensure_ascii=False,
                )
                + "\n"
            )
            receipt.chmod(0o600)
            return target
        except (subprocess.SubprocessError, OSError):
            raise OctopError.localized(ErrorCode.COMPANION_INSTALL_FAILED) from None
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    async def launch(self, user: User, action: Literal["open", "size"] = "open") -> dict[str, Any]:
        if sys.platform == "win32":
            from octop.infra.setup.companion_windows import launch_windows

            return await launch_windows(self, user, action)
        if sys.platform != "darwin":
            raise OctopError.localized(ErrorCode.COMPANION_PLATFORM_UNSUPPORTED)
        async with self._lock:
            access = await companion_access(self.server, user, force=True)
            if not access["allowed"]:
                raise OctopError.localized(ErrorCode.COMPANION_ACCESS_DENIED)
            client = client_for(self.server)
            assert client is not None
            state = await asyncio.to_thread(client._state, user.id)
            metadata = CompanionInstaller.model_validate(
                await client._remote(
                    "GET", "/api/enterprise/companion/installer", token=state["token"]
                )
            )
            metadata.verify()
            wanted = tuple(int(x) for x in metadata.version.split("."))
            candidates = [Path.home() / "Applications/哆啦.app", Path("/Applications/哆啦.app")]
            versions = await asyncio.to_thread(
                lambda: [(path, installed_version(path)) for path in candidates]
            )
            target = next(
                (path for path, version in versions if version is not None and version >= wanted),
                None,
            )
            running = await asyncio.to_thread(
                subprocess.run,
                ["/usr/bin/pgrep", "-u", str(os.getuid()), "-x", "OctopCompanion"],
                capture_output=True,
            )
            installed = False
            if target is None and running.returncode == 0:
                existing = next((path for path, version in versions if version is not None), None)
                if existing is None:
                    raise OctopError.localized(ErrorCode.COMPANION_INSTALL_FAILED)
                target = existing
            elif target is None:
                archive = await self._download(user, metadata)
                target = await asyncio.to_thread(self._install, archive, metadata)
                installed = True
            if not (await companion_access(self.server, user, force=True))["allowed"]:
                raise OctopError.localized(ErrorCode.COMPANION_ACCESS_DENIED)
            command = ["/usr/bin/open", "-a", str(target)]
            command += ["octop-companion://size"] if action == "size" else ["--args", "--show-chat"]
            try:
                await asyncio.to_thread(
                    subprocess.run, command, check=True, capture_output=True, timeout=15
                )
            except (subprocess.SubprocessError, OSError):
                raise OctopError.localized(ErrorCode.COMPANION_INSTALL_FAILED) from None
            actual = await asyncio.to_thread(installed_version, target)
            if actual is None:
                raise OctopError.localized(ErrorCode.COMPANION_INSTALL_FAILED)
            return {
                "opened": True,
                "installed": installed,
                "update_pending": actual < wanted,
                "version": ".".join(str(x) for x in actual),
            }


def launcher_for(server: Any) -> CompanionLauncher:
    value = getattr(server, "_companion_launcher", None)
    if value is None:
        value = CompanionLauncher(server)
        server._companion_launcher = value
    return value
