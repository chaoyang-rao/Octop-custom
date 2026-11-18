"""Member update polling, bounded downloads and short-lived native install tickets."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import platform
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
from packaging.version import Version

from octop.infra.agents.work_status import attach_expert_work_status
from octop.infra.auth.enterprise import client_for
from octop.infra.client_updates.github import github_download_host
from octop.infra.client_updates.models import (
    ClientRelease,
    DeviceReport,
    Platform,
    SignedRelease,
    canonical,
    failure,
    verify_release,
)
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.users.identity import User

NAMESPACE = "client-updates"


def host_platform() -> Platform | None:
    machine = platform.machine().lower()
    if os.name == "nt" and machine in {"amd64", "x86_64"}:
        return "windows-amd64"
    if platform.system() == "Darwin":
        return "darwin-arm64" if machine == "arm64" else "darwin-amd64"
    return None


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".writing-" + uuid.uuid4().hex)
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            os.chmod(temporary, 0o600)
            stream.write(canonical(value).decode())
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class ClientUpdateNode:
    def __init__(self, server: Any, *, native_platform: Platform | None = None) -> None:
        self.server = server
        self.settings = server.services.settings_repo
        self.platform = native_platform or host_platform()
        self.root = Path(server.paths.root) / NAMESPACE
        self._lock = asyncio.Lock()
        self._downloads: dict[str, asyncio.Task[None]] = {}
        self._task: asyncio.Task[None] | None = None
        self._last_poll: dict[int, float] = {}
        self._lease: tuple[str, float] | None = None
        self._local_database = self._database_is_local()
        self._pending = bool(
            re.fullmatch(r"[0-9a-f]{32}", os.environ.get("OCTOP_CLIENT_UPDATE_PENDING", ""))
        )

    @property
    def native_version(self) -> str:
        return str(os.environ.get("OCTOP_DESKTOP_CLIENT_VERSION") or "")

    def _database_is_local(self, resolve: bool = False) -> bool:
        database = self.server.services.config.database
        path = database.resolve_sqlite_path(self.server.paths.root)
        root = Path(self.server.paths.root)
        if resolve:
            path, root = path.resolve(), root.resolve()
        else:
            path, root = Path(os.path.abspath(path)), Path(os.path.abspath(root))
        return bool(database.driver == "sqlite" and path.is_relative_to(root))

    @property
    def supported(self) -> bool:
        return bool(
            self.platform
            and self.native_version
            and os.environ.get("OCTOP_DESKTOP_UPDATER_PROTOCOL") == "1"
            and os.environ.get("OCTOP_DESKTOP_PROGRAM_ROOT")
            and getattr(self.server.services.db, "dialect", "") == "sqlite"
            and self._local_database
            and client_for(self.server) is not None
        )

    @property
    def applying(self) -> bool:
        return self._lease is not None or self.pending_activation()

    def pending_activation(self) -> bool:
        return self._pending

    def _key(self, user_id: int) -> str:
        return f"enterprise.client_updates.node.{user_id}"

    def _state(self, user_id: int) -> dict[str, Any]:
        return dict(
            json.loads(
                self.settings.get(self._key(user_id))
                or '{"revision":0,"envelope":null,"job_id":null,"last_check":null}'
            )
        )

    def _change(self, user_id: int, changes: dict[str, Any]) -> dict[str, Any]:
        for _ in range(5):
            raw = self.settings.get(self._key(user_id))
            state = self._state(user_id)
            if "revision" in changes and changes["revision"] < state["revision"]:
                raise failure(ErrorCode.CLIENT_UPDATE_INTEGRITY)
            if changes.get("subject") and changes["subject"] != state.get("subject"):
                state["job_id"] = None
            state.update(changes)
            if self.settings.compare_and_set(self._key(user_id), raw, canonical(state).decode()):
                return state
        raise failure(ErrorCode.CLIENT_UPDATE_CONFLICT)

    def _directory(self, identifier: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", identifier):
            raise failure()
        directory = self.root / "jobs" / identifier
        for parent in [self.root, self.root / "jobs", directory]:
            if parent.is_symlink():
                raise failure(ErrorCode.CLIENT_UPDATE_INTEGRITY)
        return directory

    def _job(self, identifier: str) -> dict[str, Any]:
        path = self._directory(identifier) / "job.json"
        if path.is_symlink() or path.stat().st_size > 1_000_000:
            raise failure(ErrorCode.CLIENT_UPDATE_INTEGRITY)
        return dict(json.loads(path.read_text()))

    def _write_job(self, value: dict[str, Any]) -> None:
        atomic_json(self._directory(value["id"]) / "job.json", value)

    async def _fetch(self, user: User) -> tuple[dict[str, Any], ClientRelease | None]:
        client = client_for(self.server)
        if client is None:
            raise failure(ErrorCode.ENTERPRISE_NOT_CONFIGURED)
        self._local_database = await asyncio.to_thread(self._database_is_local, True)
        await client.authorize(user)
        credentials = await asyncio.to_thread(client._state, user.id)
        response = await client._remote(
            "GET", "/api/enterprise/client-updates/catalog", token=credentials["token"]
        )
        state = await asyncio.to_thread(self._state, user.id)
        revision = int(response["revision"])
        if revision < state["revision"]:
            raise failure(ErrorCode.CLIENT_UPDATE_INTEGRITY)
        envelope = (
            SignedRelease.model_validate(response["envelope"]) if response.get("envelope") else None
        )
        release = (
            await asyncio.to_thread(verify_release, envelope, client.authority)
            if envelope
            else None
        )
        if release and release.revision != revision:
            raise failure(ErrorCode.CLIENT_UPDATE_INTEGRITY)
        state = await asyncio.to_thread(
            self._change,
            user.id,
            {
                "revision": revision,
                "envelope": envelope.model_dump(mode="json") if envelope else None,
                "last_check": int(time.time()),
                "subject": credentials["subject"],
            },
        )
        return state, release

    async def busy(self) -> bool:
        runtime = getattr(self.server, "app_runtime", None)
        registry = getattr(runtime, "agent_registry", None)
        if registry is None or bool(getattr(self.server, "_client_update_mutations", None)):
            return True
        rows = await asyncio.to_thread(self.server.services.agent_repo.list_all)
        if any(registry.is_agent_active(row.id) for row in rows):
            return True
        for owner in {row.user_id for row in rows}:
            payloads = [
                {"agent_id": row.id, "state": "running"} for row in rows if row.user_id == owner
            ]
            await attach_expert_work_status(self.server, owner, payloads)
            if any(row["work_status"] != "idle" for row in payloads):
                return True
        return False

    async def status(self, user: User, *, refresh: bool = False) -> dict[str, Any]:
        state = await asyncio.to_thread(self._state, user.id)
        error = None
        client = client_for(self.server)
        release = None
        try:
            if client and (
                refresh or not state["last_check"] or time.time() - state["last_check"] >= 30
            ):
                state, release = await self._fetch(user)
            elif client and state["envelope"]:
                release = await asyncio.to_thread(
                    verify_release,
                    SignedRelease.model_validate(state["envelope"]),
                    client.authority,
                )
        except OctopError as exc:
            error = exc.code.value
        available = bool(
            release
            and release.enabled
            and self.native_version
            and Version(release.version) > Version(self.native_version)
        )
        job = None
        if state["job_id"]:
            with contextlib.suppress(OSError, ValueError, KeyError, OctopError):
                saved = await asyncio.to_thread(self._job, state["job_id"])
                if saved["owner_user_id"] == user.id:
                    job = {
                        key: saved.get(key)
                        for key in (
                            "id",
                            "phase",
                            "downloaded_bytes",
                            "total_bytes",
                            "error_code",
                            "target_version",
                        )
                    }
        return {
            "supported": self.supported,
            "platform": self.platform,
            "current_version": self.native_version or None,
            "revision": state["revision"],
            "available": available,
            "version": release.version if release else None,
            "notes": release.notes if release else "",
            "last_check": state["last_check"],
            "busy": await self.busy() if self.supported else False,
            "job": job,
            "error_code": error,
        }

    async def download(self, user: User) -> dict[str, Any]:
        if not self.supported:
            raise failure(ErrorCode.CLIENT_UPDATE_UNSUPPORTED)
        async with self._lock:
            if self.applying:
                raise failure(ErrorCode.CLIENT_UPDATE_BUSY)
            if any(not task.done() for task in self._downloads.values()):
                raise failure(ErrorCode.CLIENT_UPDATE_BUSY)
            state, release = await self._fetch(user)
            if (
                not self.supported
                or not release
                or not release.enabled
                or Version(release.version) <= Version(self.native_version)
            ):
                raise failure(ErrorCode.CLIENT_UPDATE_CONFLICT)
            package = next(item for item in release.packages if item.platform == self.platform)
            if (
                await asyncio.to_thread(shutil.disk_usage, self.server.paths.root)
            ).free < package.size * 3:
                raise failure(ErrorCode.CLIENT_UPDATE_DOWNLOAD_FAILED)
            identifier = uuid.uuid4().hex
            value = {
                "schema_version": 1,
                "id": identifier,
                "owner_user_id": user.id,
                "subject": state["subject"],
                "platform": self.platform,
                "current_version": self.native_version,
                "target_version": release.version,
                "revision": release.revision,
                "phase": "downloading",
                "downloaded_bytes": 0,
                "total_bytes": package.size,
                "envelope": state["envelope"],
                "error_code": None,
            }
            await asyncio.to_thread(self._write_job, value)
            await asyncio.to_thread(self._change, user.id, {"job_id": identifier})
            self._downloads[identifier] = asyncio.create_task(
                self._download(user, value, package.url, package.sha256),
                name="client-update-download",
            )
        return await self.status(user)

    async def _download(
        self, user: User, value: dict[str, Any], url: str, expected_sha: str
    ) -> None:
        directory = await asyncio.to_thread(self._directory, value["id"])
        partial = directory / "payload.part"
        try:
            digest = hashlib.sha256()
            count = 0
            last_write = time.monotonic()
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(30, read=120), follow_redirects=False
            ) as client:
                for _ in range(5):
                    if not github_download_host(url):
                        raise failure(ErrorCode.CLIENT_UPDATE_INTEGRITY)
                    async with client.stream(
                        "GET", url, headers={"User-Agent": "OctopCustom-Updater/1"}
                    ) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            url = str(response.url.join(response.headers["location"]))
                            continue
                        response.raise_for_status()
                        stream = await asyncio.to_thread(partial.open, "xb")
                        try:
                            await asyncio.to_thread(os.chmod, partial, 0o600)
                            async for block in response.aiter_bytes(1024 * 1024):
                                count += len(block)
                                if count > value["total_bytes"]:
                                    raise failure(ErrorCode.CLIENT_UPDATE_INTEGRITY)
                                digest.update(block)
                                await asyncio.to_thread(stream.write, block)
                                if time.monotonic() - last_write >= 0.5:
                                    value["downloaded_bytes"] = count
                                    await asyncio.to_thread(self._write_job, value)
                                    last_write = time.monotonic()
                        finally:
                            await asyncio.to_thread(stream.close)
                        break
                else:
                    raise failure(ErrorCode.CLIENT_UPDATE_DOWNLOAD_FAILED)
            if count != value["total_bytes"] or digest.hexdigest() != expected_sha:
                raise failure(ErrorCode.CLIENT_UPDATE_INTEGRITY)
            _, latest = await self._fetch(user)
            if not latest or not latest.enabled or latest.revision != value["revision"]:
                raise failure(ErrorCode.CLIENT_UPDATE_CONFLICT)
            await asyncio.to_thread(partial.replace, directory / "payload.zip")
            value.update(phase="downloaded", downloaded_bytes=count)
        except asyncio.CancelledError:
            value.update(phase="cancelled")
        except (OctopError, OSError, httpx.HTTPError, ValueError, KeyError) as exc:
            value.update(
                phase="failed",
                error_code=exc.code.value
                if isinstance(exc, OctopError)
                else ErrorCode.CLIENT_UPDATE_DOWNLOAD_FAILED.value,
            )
        finally:
            await asyncio.to_thread(partial.unlink, missing_ok=True)
            await asyncio.to_thread(self._write_job, value)
            with contextlib.suppress(OctopError):
                await self.report(user, value)

    async def prepare_install(self, user: User, identifier: str) -> dict[str, str]:
        if not self.supported:
            raise failure(ErrorCode.CLIENT_UPDATE_UNSUPPORTED)
        async with self._lock:
            value = await asyncio.to_thread(self._job, identifier)
            if value["owner_user_id"] != user.id or value["phase"] not in {
                "downloaded",
                "waiting_idle",
            }:
                raise failure(ErrorCode.CLIENT_UPDATE_CONFLICT)
            state, release = await self._fetch(user)
            if value.get("subject") != state["subject"]:
                raise failure(ErrorCode.CLIENT_UPDATE_CONFLICT)
            if (
                not self.supported
                or not release
                or not release.enabled
                or release.revision != value["revision"]
            ):
                raise failure(ErrorCode.CLIENT_UPDATE_CONFLICT)
            if await self.busy():
                value["phase"] = "waiting_idle"
                await asyncio.to_thread(self._write_job, value)
                raise failure(ErrorCode.CLIENT_UPDATE_BUSY)
            registry = self.server.app_runtime.agent_registry
            if not registry.try_begin_application_update():
                raise failure(ErrorCode.CLIENT_UPDATE_BUSY)
            self._lease = (identifier, time.monotonic() + 120)
            try:
                if await self.busy():
                    raise failure(ErrorCode.CLIENT_UPDATE_BUSY)
                value.update(
                    phase="applying",
                    approved_at=int(time.time()),
                    expires_at=int(time.time()) + 120,
                    app_root=os.environ["OCTOP_DESKTOP_PROGRAM_ROOT"],
                    data_root=str(self.server.paths.root),
                )
                await asyncio.to_thread(self._write_job, value)
            except BaseException:
                self.release_install()
                raise
            return {"job_id": identifier}

    def release_install(self) -> None:
        runtime = getattr(self.server, "app_runtime", None)
        registry = getattr(runtime, "agent_registry", None)
        if registry is not None:
            registry.end_application_update()
        self._lease = None

    async def abort_install(self, user: User, identifier: str) -> dict[str, Any]:
        async with self._lock:
            value = await asyncio.to_thread(self._job, identifier)
            if value["owner_user_id"] != user.id or not self._lease or self._lease[0] != identifier:
                raise failure(ErrorCode.CLIENT_UPDATE_CONFLICT)
            self.release_install()
            value.update(phase="downloaded", expires_at=0)
            await asyncio.to_thread(self._write_job, value)
        return await self.status(user)

    async def cancel(self, user: User, identifier: str) -> dict[str, Any]:
        value = await asyncio.to_thread(self._job, identifier)
        if value["owner_user_id"] != user.id:
            raise failure(ErrorCode.FORBIDDEN)
        if value["phase"] not in {
            "downloading",
            "downloaded",
            "waiting_idle",
            "failed",
            "rolled_back",
            "cancelled",
        }:
            raise failure(ErrorCode.CLIENT_UPDATE_CONFLICT)
        task = self._downloads.get(identifier)
        if task and not task.done():
            task.cancel()
            await task
        else:
            value["phase"] = "cancelled"
            await asyncio.to_thread(self._write_job, value)
        return await self.status(user)

    async def report(self, user: User, value: dict[str, Any] | None = None) -> None:
        if not self.supported:
            return
        client = client_for(self.server)
        if client is None:
            return
        assert self.platform is not None
        credentials = await asyncio.to_thread(client._state, user.id)
        if value and value.get("subject") != credentials["subject"]:
            return
        report = DeviceReport(
            platform=self.platform,
            device_name=platform.node()[:80],
            current_version=self.native_version,
            target_version=value.get("target_version") if value else None,
            phase=value["phase"] if value else "idle",
            error_code=value.get("error_code") if value else None,
        )
        await client._remote(
            "POST",
            "/api/enterprise/client-updates/report",
            token=credentials["token"],
            body=report.model_dump(mode="json"),
        )

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="company-client-updates")

    async def stop(self) -> None:
        for task in self._downloads.values():
            task.cancel()
        if self._downloads:
            await asyncio.gather(*self._downloads.values(), return_exceptions=True)
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _run(self) -> None:
        while True:
            if self._lease and time.monotonic() > self._lease[1]:
                self.release_install()
            if self._pending:
                with contextlib.suppress(OSError, ValueError, KeyError, OctopError):
                    value = await asyncio.to_thread(
                        self._job, os.environ["OCTOP_CLIENT_UPDATE_PENDING"]
                    )
                    if value["phase"] == "accepted":
                        await self.server.resume_after_client_update()
                        self._pending = False
            if self.supported and not self.pending_activation():
                users = await asyncio.to_thread(self.server.services.user_repo.list)
                for row in users:
                    if time.monotonic() - self._last_poll.get(row.id, 0) < 30:
                        continue
                    self._last_poll[row.id] = time.monotonic()
                    user = await asyncio.to_thread(self.server.user_manager.get_by_id, row.id)
                    if user is None:
                        continue
                    with contextlib.suppress(OctopError, ValueError, OSError, KeyError):
                        state, release = await self._fetch(user)
                        job = (
                            await asyncio.to_thread(self._job, state["job_id"])
                            if state["job_id"]
                            else None
                        )
                        if (
                            job is None
                            and release
                            and release.enabled
                            and Version(release.version) > Version(self.native_version)
                        ):
                            job = {
                                "subject": state["subject"],
                                "phase": "available",
                                "target_version": release.version,
                            }
                        await self.report(user, job)
            await asyncio.sleep(1)


def updates_for(server: Any) -> ClientUpdateNode:
    value = getattr(server, "_client_updates", None)
    if value is None:
        value = ClientUpdateNode(server)
        server._client_updates = value
    return value
