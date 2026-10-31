"""Explicit, pinned CLI installs inside OCTOP_HOME; never global CLI replacement."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import platform
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, cast
from urllib.parse import urljoin, urlsplit

import httpx

from octop.infra.agents.native_cli.config import NativeCLIError
from octop.infra.agents.native_cli.managed_artifacts import (
    artifact_identity,
    decode_brotli,
    download_license,
    install_component,
    locked_components,
    safe_relative,
    tree_manifest,
    verify_tree,
)
from octop.infra.agents.settings.cli_reuse import _busy
from octop.infra.utils.ssrf_guard import PinnedIPTransport, _resolve_validated_ip

_ALLOWED_DOWNLOAD_HOSTS = {
    "github.com",
    "release-assets.githubusercontent.com",
    "objects.githubusercontent.com",
    "github-releases.githubusercontent.com",
    "raw.githubusercontent.com",
    "registry.npmjs.org",
    "nodejs.org",
    "downloads.cursor.com",
    "cursor.com",
    "www.apache.org",
}


def host_platform() -> str:
    architecture = platform.machine().lower()
    arch = (
        "arm64"
        if architecture in {"arm64", "aarch64"}
        else "amd64"
        if architecture in {"x86_64", "amd64"}
        else architecture
    )
    if sys.platform == "darwin":
        return "darwin-" + arch
    if sys.platform == "win32":
        return "windows-" + arch
    libc = "-musl" if platform.libc_ver()[0] == "musl" else ""
    return f"linux{libc}-{arch}"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def download_pinned(url: str, destination: Path, *, size_limit: int) -> None:
    """Stream only approved HTTPS hosts, pin DNS and revalidate redirects."""
    current = url
    async with asyncio.timeout(300):
        for _ in range(6):
            parsed = urlsplit(current)
            if (
                parsed.scheme != "https"
                or parsed.hostname not in _ALLOWED_DOWNLOAD_HOSTS
                or parsed.username
                or parsed.port not in (None, 443)
            ):
                raise NativeCLIError("managed_download_failed")
            pin = await _resolve_validated_ip(current)
            async with (
                httpx.AsyncClient(
                    transport=PinnedIPTransport(parsed.hostname, pin),
                    timeout=30,
                    follow_redirects=False,
                ) as client,
                client.stream(
                    "GET", current, headers={"User-Agent": "Octop-managed-cli/1.0"}
                ) as response,
            ):
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("Location")
                    if not location:
                        raise NativeCLIError("managed_download_failed")
                    current = urljoin(current, location)
                    continue
                if response.status_code != 200:
                    raise NativeCLIError("managed_download_failed")
                count = 0
                target = await asyncio.to_thread(destination.open, "wb")
                try:
                    async for chunk in response.aiter_bytes(1024 * 1024):
                        count += len(chunk)
                        if count > size_limit:
                            raise NativeCLIError("managed_integrity")
                        await asyncio.to_thread(target.write, chunk)
                finally:
                    await asyncio.to_thread(target.close)
                return
        raise NativeCLIError("managed_download_failed")


def extract_managed(
    archive: Path, destination: Path, archive_format: str, binary_name: str
) -> Path:
    """Compatibility wrapper for a standalone reviewed executable archive."""
    from octop.infra.agents.native_cli.managed_artifacts import extract_tree

    files = extract_tree(archive, destination, archive_format)
    binaries = [path for path in files if path.name == binary_name]
    if len(binaries) != 1:
        raise NativeCLIError("managed_missing_binary")
    binaries[0].chmod(0o755)
    return binaries[0]


class ManagedCLI:
    def __init__(
        self,
        manager: Any,
        *,
        catalog: dict[str, Any] | None = None,
        platform_id: str | None = None,
        downloader: Any = download_pinned,
    ) -> None:
        self.manager = manager
        self.settings = manager._repos.settings_repo
        self.catalog = (
            catalog
            if catalog is not None
            else json.loads(Path(__file__).with_name("managed_catalog.json").read_text())
        )
        self.platform = platform_id or host_platform()
        self.downloader = downloader
        self.jobs: dict[tuple[int, str], asyncio.Task[None]] = {}
        self.locks: dict[tuple[int, str], asyncio.Lock] = {}

    def _root(self, user_id: int, package: str) -> Path:
        return Path(self.manager.paths.root) / "managed-cli" / str(user_id) / package

    async def _value(self, key: str) -> dict[str, Any]:
        raw = await asyncio.to_thread(self.settings.get, key)
        return json.loads(raw) if raw else {}

    async def _store(self, key: str, value: dict[str, Any]) -> None:
        await asyncio.to_thread(self.settings.set, key, json.dumps(value))

    def _package(self, package: str) -> dict[str, Any]:
        result = self.catalog["packages"].get(package)
        if not isinstance(result, dict):
            raise NativeCLIError("invalid_input")
        return result

    def _artifact(self, package: str, version: str) -> tuple[dict[str, Any], dict[str, Any]]:
        row = self._package(package)["versions"].get(version)
        if not isinstance(row, dict):
            raise NativeCLIError("invalid_input")
        artifact = row["platforms"].get(self.platform)
        if not isinstance(artifact, dict):
            raise NativeCLIError("managed_unsupported_platform")
        return row, artifact

    async def status(self, user_id: int) -> list[dict[str, Any]]:
        output = []
        for name, package in self.catalog["packages"].items():
            installed = await self._value(f"managed_cli.installed.{user_id}.{name}")
            active = await self._value(f"managed_cli.active.{user_id}.{name}")
            job = await self._value(f"managed_cli.state.{user_id}.{name}")
            if (
                job.get("phase") in {"downloading", "extracting", "queued"}
                and (user_id, name) not in self.jobs
            ):
                job = {**job, "phase": "interrupted"}
            versions = sorted(
                package["versions"],
                key=lambda value: tuple(int(part) for part in re.findall(r"\d+", value)),
            )
            output.append(
                {
                    "package": name,
                    "label": package["label"],
                    "license": package["license"],
                    "repository": package["repository"],
                    "runner": package["runner_name"],
                    "versions": versions,
                    "approved": [
                        {
                            "version": version,
                            **package["versions"][version]["platforms"][self.platform],
                            "license_url": package["versions"][version]["license_url"],
                            "license_sha256": package["versions"][version]["license_sha256"],
                            "release_url": package["versions"][version]["release_url"],
                            "integrity": package["versions"][version]["platforms"][
                                self.platform
                            ].get("integrity"),
                        }
                        for version in versions
                        if self.platform in package["versions"][version]["platforms"]
                    ],
                    "latest_approved": versions[-1],
                    "supported": self.platform in package["versions"][versions[-1]]["platforms"],
                    "platform": self.platform,
                    "installed": list(installed),
                    "active_version": active.get("version"),
                    "previous_version": active.get("previous_version"),
                    "state": job,
                }
            )
        return output

    async def install(self, user_id: int, package: str, version: str) -> dict[str, Any]:
        self._artifact(package, version)
        key = (user_id, package)
        if key in self.jobs:
            raise NativeCLIError("managed_busy")
        await self._store(
            f"managed_cli.state.{user_id}.{package}", {"phase": "queued", "version": version}
        )
        task = asyncio.create_task(
            self._install(user_id, package, version), name=f"managed-cli-{user_id}-{package}"
        )
        self.jobs[key] = task
        task.add_done_callback(lambda _: self.jobs.pop(key, None))
        return {"phase": "queued", "version": version}

    async def _install(self, user_id: int, package: str, version: str) -> None:
        key = f"managed_cli.state.{user_id}.{package}"
        stage: Path | None = None
        archive: Path | None = None
        try:
            async with self.locks.setdefault((user_id, package), asyncio.Lock()):
                release, artifact = self._artifact(package, version)
                root = self._root(user_id, package)
                await asyncio.to_thread(root.mkdir, parents=True, exist_ok=True, mode=0o700)
                stage = Path(await asyncio.to_thread(tempfile.mkdtemp, prefix=".stage-", dir=root))
                archive = stage / ".download"
                await self._store(key, {"phase": "downloading", "version": version})
                content = stage / "content"
                await asyncio.to_thread(content.mkdir)
                files = await install_component(
                    artifact, content=content, download_file=archive, downloader=self.downloader
                )
                if artifact.get("entry"):
                    binary = content / safe_relative(artifact["entry"])
                    if binary not in files:
                        raise NativeCLIError("managed_missing_binary")
                else:
                    binaries = [path for path in files if path.name == artifact["binary"]]
                    if len(binaries) != 1:
                        raise NativeCLIError("managed_missing_binary")
                    binary = binaries[0]
                await asyncio.to_thread(binary.chmod, 0o755)
                components = await asyncio.to_thread(locked_components, release, self.platform)
                if artifact.get("runtime"):
                    components.append(artifact["runtime"])
                for index, component in enumerate(components):
                    await install_component(
                        component,
                        content=content,
                        download_file=stage / f".component-{index}",
                        downloader=self.downloader,
                    )
                if artifact.get("brotli_output"):
                    runtime = artifact["runtime"]
                    node = (
                        content / safe_relative(runtime["target"]) / safe_relative(runtime["entry"])
                    )
                    decoded = content / safe_relative(artifact["brotli_output"])
                    await decode_brotli(node, binary, decoded)
                    binary = decoded
                await self._store(key, {"phase": "extracting", "version": version})
                await download_license(release, content, stage, self.downloader)
                profiles = self._package(package).get("profile_files", {})
                profile = root / "profile"
                for relative_name, data in profiles.items():
                    path = profile / safe_relative(relative_name)
                    await asyncio.to_thread(
                        path.parent.mkdir, parents=True, exist_ok=True, mode=0o700
                    )

                    def seed_profile(target_path: Path, contents: Any) -> None:
                        try:
                            with target_path.open("x", encoding="utf-8") as target:
                                target.write(json.dumps(contents, ensure_ascii=False))
                            target_path.chmod(0o600)
                        except FileExistsError:
                            pass

                    await asyncio.to_thread(seed_profile, path, data)
                relative = binary.relative_to(content)
                entry_relative = (
                    safe_relative(artifact["script"]) if artifact.get("script") else relative
                )
                if not await asyncio.to_thread((content / entry_relative).is_file):
                    raise NativeCLIError("managed_missing_binary")
                command_relative = relative
                arguments = list(
                    release.get("runner_args", self._package(package).get("runner_args", []))
                )
                if artifact.get("launch_command"):
                    command_relative = safe_relative(artifact["launch_command"])
                    if not await asyncio.to_thread((content / command_relative).is_file):
                        raise NativeCLIError("managed_missing_binary")
                    await asyncio.to_thread((content / command_relative).chmod, 0o755)
                    arguments = ["@entry", *arguments]
                if artifact.get("runtime") and not artifact.get("brotli_output"):
                    runtime = artifact["runtime"]
                    command_relative = safe_relative(runtime["target"]) / safe_relative(
                        runtime["entry"]
                    )
                    node = content / command_relative
                    if not await asyncio.to_thread(node.is_file):
                        raise NativeCLIError("managed_missing_binary")
                    await asyncio.to_thread(node.chmod, 0o755)
                    arguments = ["@entry", *arguments]
                manifest = await asyncio.to_thread(tree_manifest, content)
                final = root / f"{version}-{artifact_identity(artifact)}"
                if await asyncio.to_thread(final.exists):
                    if not await asyncio.to_thread(verify_tree, final, manifest):
                        raise NativeCLIError("managed_modified")
                else:
                    await asyncio.to_thread(os.replace, content, final)
                record = await self._value(f"managed_cli.installed.{user_id}.{package}")
                record[version] = {
                    "directory": str(final),
                    "binary": str(final / command_relative),
                    "binary_sha256": manifest[command_relative.as_posix()],
                    "archive_sha256": artifact.get("sha256"),
                    "integrity": artifact.get("integrity"),
                    "manifest": manifest,
                    "args": [
                        str(final / entry_relative) if arg == "@entry" else arg for arg in arguments
                    ],
                    "env": self._package(package).get("runner_env", {}),
                    "profile": str(profile) if profiles else None,
                    "path_dirs": [
                        *(
                            [str(final / relative.parent)]
                            if artifact.get("provide_on_path")
                            else []
                        ),
                        *(
                            [str(final / command_relative.parent)]
                            if artifact.get("runtime")
                            else []
                        ),
                    ],
                    "platform": self.platform,
                }
                await self._store(f"managed_cli.installed.{user_id}.{package}", record)
                await self._store(key, {"phase": "installed", "version": version})
        except asyncio.CancelledError:
            await self._store(key, {"phase": "interrupted", "version": version})
            raise
        except Exception as exc:
            code = exc.code if isinstance(exc, NativeCLIError) else "managed_install_failed"
            await self._store(key, {"phase": "failed", "version": version, "error_code": code})
        finally:
            if stage is not None:
                await asyncio.to_thread(shutil.rmtree, stage, True)

    async def activate(self, user_id: int, package: str, version: str) -> dict[str, Any]:
        self._artifact(package, version)
        if (user_id, package) in self.jobs:
            raise NativeCLIError("managed_busy")
        async with self.locks.setdefault((user_id, package), asyncio.Lock()):
            installed = await self._value(f"managed_cli.installed.{user_id}.{package}")
            record = installed.get(version)
            if not isinstance(record, dict):
                raise NativeCLIError("managed_not_installed")
            binary = Path(record["binary"])

            def intact() -> bool:
                return (
                    binary.resolve().is_relative_to(self._root(user_id, package).resolve())
                    and binary.is_file()
                    and file_sha256(binary) == record["binary_sha256"]
                    and (
                        not record.get("manifest")
                        or verify_tree(Path(record["directory"]), record["manifest"])
                    )
                )

            if not await asyncio.to_thread(intact):
                raise NativeCLIError("managed_modified")
            name = self._package(package)["runner_name"]
            active = await self._value(f"managed_cli.active.{user_id}.{package}")
            definitions = await asyncio.to_thread(self.manager.acp_settings.load_runners, user_id)
            current = definitions.get(name)
            if current:
                expected = active.get("runner_config")
                if (
                    not active
                    or (
                        expected is not None
                        and any(
                            current.get(k) != expected.get(k)
                            for k in (
                                "command",
                                "args",
                                "env",
                                "enabled",
                                "trusted",
                                "tool_parse_mode",
                            )
                        )
                    )
                    or (
                        expected is None
                        and (current.get("command") != active.get("binary") or current.get("args"))
                    )
                ):
                    raise NativeCLIError("managed_runner_changed")
            agents = await asyncio.to_thread(self.manager.list_agents, user_id)
            affected = []
            for row in agents:
                cfg = await asyncio.to_thread(self.manager.get_config, row.agent_id)
                if (cfg.get("native_cli") or {}).get("runner") == name:
                    affected.append(row.agent_id)
            held = []
            try:
                for aid in affected:
                    if not self.manager.try_begin_runtime_update(aid):
                        raise NativeCLIError("busy")
                    held.append(aid)
                for aid in affected:
                    if await _busy(self.manager, aid, user_id):
                        raise NativeCLIError("busy")
                async with self.manager.native_cli.maintenance:
                    for aid in affected:
                        await self.manager.native_cli.close_agent(aid)
                    definitions[name] = {
                        **(current or {}),
                        "enabled": True,
                        "command": str(binary),
                        "args": record.get("args", []),
                        "env": {**(current or {}).get("env", {}), **record.get("env", {})},
                        "trusted": bool((current or {}).get("trusted", False)),
                        "tool_parse_mode": (current or {}).get("tool_parse_mode", "call_detail"),
                    }
                    if record.get("profile"):
                        profile = Path(record["profile"])
                        if not profile.resolve().is_relative_to(
                            self._root(user_id, package).resolve()
                        ):
                            raise NativeCLIError("managed_modified")
                        profile_config = await asyncio.to_thread(
                            (profile / "cli-config.json").read_text
                        )
                        if json.loads(profile_config).get("channel") != "static":
                            raise NativeCLIError("managed_runner_changed")
                        definitions[name]["env"]["CURSOR_CONFIG_DIR"] = str(profile)
                    if record.get("path_dirs"):
                        definitions[name]["env"]["PATH"] = os.pathsep.join(
                            [
                                *record["path_dirs"],
                                os.environ.get("PATH", os.defpath),
                            ]
                        )
                    try:
                        await asyncio.to_thread(
                            self.manager.acp_settings.save_managed_runner,
                            user_id,
                            name,
                            definitions[name],
                        )
                    except ValueError:
                        raise NativeCLIError("managed_runner_changed") from None
                    # Native resolves runners on every turn. Existing ACP delegation
                    # sessions keep their current executable until normal reload.
                    await self._store(
                        f"managed_cli.active.{user_id}.{package}",
                        {
                            "version": version,
                            "binary": str(binary),
                            "runner_config": definitions[name],
                            "previous_version": active.get("version")
                            if active.get("version") != version
                            else active.get("previous_version"),
                        },
                    )
            finally:
                for aid in held:
                    self.manager.end_runtime_update(aid)
            return {"version": version, "runner": name}

    async def rollback(self, user_id: int, package: str) -> dict[str, Any]:
        active = await self._value(f"managed_cli.active.{user_id}.{package}")
        previous = active.get("previous_version")
        if not previous:
            raise NativeCLIError("managed_no_previous")
        return await self.activate(user_id, package, str(previous))

    async def aclose(self) -> None:
        tasks = list(self.jobs.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


async def managed_for(manager: Any) -> ManagedCLI:
    async with manager.native_cli.maintenance:
        if manager.native_cli.managed_packages is None:
            manager.native_cli.managed_packages = await asyncio.to_thread(ManagedCLI, manager)
        return cast(ManagedCLI, manager.native_cli.managed_packages)
