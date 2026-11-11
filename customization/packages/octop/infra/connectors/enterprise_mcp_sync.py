"""Pull company definitions and apply them only while affected runtimes are idle."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Any

from octop.i18n.domains.errors import error_message
from octop.infra.auth.enterprise import client_for
from octop.infra.connectors.enterprise_catalog import entry_fingerprint, validate_snapshot
from octop.infra.connectors.enterprise_mcp_store import EnterpriseMcpStore, authorization_headers
from octop.infra.connectors.probe import probe_custom_mcp_server
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.users.identity import User

logger = logging.getLogger(__name__)


class EnterpriseMcpSync:
    def __init__(self, server: Any) -> None:
        self.server = server
        services = server.services
        self.services = services
        self.store = EnterpriseMcpStore(
            services.settings_repo,
            services.secret_repo,
            str(getattr(services.config, "enterprise_authority_url", "")),
        )
        self._locks: dict[int, asyncio.Lock] = {}
        self._task: asyncio.Task[None] | None = None
        self._last_attempt: dict[int, float] = {}
        try:
            self._loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None

    def _lock(self, user_id: int) -> asyncio.Lock:
        return self._locks.setdefault(user_id, asyncio.Lock())

    @property
    def enabled(self) -> bool:
        return bool(self.store.authority)

    def _registry(self) -> Any:
        runtime = self.server.app_runtime
        return runtime.agent_registry if runtime is not None else None

    def _existing_names(self, user_id: int) -> set[str]:
        from octop.infra.connectors.service import ConnectorService

        services = self.server.services
        svc = ConnectorService(
            repo=services.connector_repo,
            secret_repo=services.secret_repo,
            settings_repo=services.settings_repo,
            config=services.config,
        )
        return {
            str(item["mcp_server_name"])
            for item in svc.list_instances_for_api(user_id)
            if item["kind"] != "enterprise-mcp"
        }

    def status(self, user: User) -> dict[str, Any]:
        state = self.store.state(user.id)
        desired = self.store._entries(state, "desired")
        combined = {**self.store._entries(state, "applied"), **desired}
        existing = self._existing_names(user.id) if self.enabled else set()
        entries = []
        for entry_id, entry in sorted(combined.items()):
            enabled = bool(entry.enabled and entry_id in desired)
            name = self.store.server_name(entry_id, user_id=user.id)
            authorized = self.store.authorized(user.id, entry)
            entries.append(
                {
                    **entry.model_dump(mode="json"),
                    "enabled": enabled,
                    "server_name": name,
                    "fingerprint": entry_fingerprint(entry),
                    "authorized": authorized,
                    "local_disabled": entry_id in state["local_disabled"],
                    "needs_reauthorization": entry.auth_kind != "none" and not authorized,
                    "configuration_error": (
                        error_message(ErrorCode.CONNECTOR_NAME_TAKEN.value, user.locale)
                        if name in existing
                        else None
                    ),
                }
            )
        return {
            "enabled": self.enabled,
            "authority_url": self.store.authority or None,
            "revision": state["desired"]["revision"],
            "last_synced_at": state["last_synced_at"],
            "sync_error": (
                error_message(state["sync_error"], user.locale) if state["sync_error"] else None
            ),
            "pending_apply": self.store.pending(user.id),
            "entries": entries,
        }

    async def _fetch(self, user: User) -> None:
        client = client_for(self.server)
        if client is None:
            raise OctopError.localized(ErrorCode.ENTERPRISE_NOT_CONFIGURED, user.locale)
        subject, raw = await client.fetch_mcp_catalog(user)
        snapshot = validate_snapshot(raw)
        await asyncio.to_thread(self.store.receive, user.id, subject, snapshot)

    async def sync(self, user: User) -> dict[str, Any]:
        async with self._lock(user.id):
            try:
                await self._fetch(user)
                await self._apply(user.id)
            except OctopError as exc:
                await asyncio.to_thread(self.store.mark_error, user.id, exc.code)
                raise
        return await asyncio.to_thread(self.status, user)

    async def _apply(self, user_id: int) -> bool:
        if not await asyncio.to_thread(self.store.pending, user_id):
            return True
        registry = self._registry()
        if registry is None:
            return False
        rows = await asyncio.to_thread(
            self.server.services.agent_repo.list_by_user, user_id, include_disabled=False
        )
        shared = await asyncio.to_thread(
            self.server.services.agent_repo.list_all, include_disabled=False
        )
        ids = sorted({row.agent_id for row in rows + [r for r in shared if r.user_id is None]})
        held: list[str] = []
        for agent_id in ids:
            if not registry.try_begin_runtime_update(agent_id):
                for reserved in held:
                    registry.end_runtime_update(reserved)
                return False
            held.append(agent_id)
        before: dict[str, Any] | None = None
        names: set[str] = set()
        try:
            old_configs = await asyncio.to_thread(self.store.harness_configs, user_id)
            old_bindings = await asyncio.to_thread(self.store.runtime_bindings, user_id)
            before = await asyncio.to_thread(self.store.activate_pending, user_id)
            entry_ids = {
                item["entry_id"]
                for which in ("applied", "desired")
                for item in before[which]["entries"]
            }
            reserved_names = await asyncio.to_thread(self._existing_names, user_id)
            names = {
                name
                for entry_id in entry_ids
                if (
                    name := self.store.server_name(
                        entry_id, user_id=user_id, subject=str(before["subject"])
                    )
                )
                not in reserved_names
            }
            new_configs = await asyncio.to_thread(self.store.harness_configs, user_id)
            new_bindings = await asyncio.to_thread(self.store.runtime_bindings, user_id)
            definitions_changed = before["applied"]["checksum"] != before["desired"]["checksum"]
            had_runtime = bool(
                before["applied_auth"]
                or before["desired_auth"]
                or any(entry["auth_kind"] == "none" for entry in before["applied"]["entries"])
            )
            if names and (
                old_configs != new_configs
                or old_bindings != new_bindings
                or definitions_changed
                and had_runtime
            ):
                registry.invalidate_mcp_tool_cache(user_id, server_names=names)
                for agent_id in ids:
                    await registry.reload_connectors(agent_id, connector_user_id=user_id)
            await asyncio.to_thread(self.store.finish_apply, user_id, before)
            return True
        except Exception:
            if before is not None:
                await asyncio.to_thread(self.store.restore_active, user_id, before)
                registry.invalidate_mcp_tool_cache(user_id, server_names=names)
                for agent_id in ids:
                    with contextlib.suppress(Exception):
                        await registry.reload_connectors(agent_id, connector_user_id=user_id)
            raise OctopError.localized(ErrorCode.ENTERPRISE_MCP_SYNC_FAILED) from None
        finally:
            for agent_id in held:
                registry.end_runtime_update(agent_id)

    async def save_credentials(
        self,
        user: User,
        entry_id: str,
        incoming: dict[str, str],
        expected_fingerprint: str,
    ) -> dict[str, Any]:
        await self.sync(user)
        async with self._lock(user.id):
            entry = await asyncio.to_thread(self.store.desired_entry, user.id, entry_id)
            if entry_fingerprint(entry) != expected_fingerprint:
                raise OctopError.localized(ErrorCode.ENTERPRISE_MCP_CATALOG_CONFLICT, user.locale)
            server_name = await asyncio.to_thread(self.store.server_name, entry_id, user_id=user.id)
            if server_name in await asyncio.to_thread(self._existing_names, user.id):
                raise OctopError.localized(ErrorCode.CONNECTOR_NAME_TAKEN, user.locale)
            fields = (
                ("token",)
                if entry.auth_kind == "bearer"
                else ("username", "password")
                if entry.auth_kind == "basic"
                else ()
            )
            credentials = {key: incoming.get(key, "") for key in fields}
            headers = authorization_headers(entry, credentials)
            # Probe protocol initialization/tool listing, never a business tool call.
            result = await probe_custom_mcp_server(
                {"transport": "streamable_http", "url": entry.url, "headers": headers}
            )
            if result.get("ok") is not True:
                code = (
                    ErrorCode.CONNECTOR_INVALID_CREDENTIALS
                    if result.get("error_type") == "auth"
                    else ErrorCode.ENTERPRISE_UNAVAILABLE
                )
                raise OctopError.localized(code, user.locale)
            await self._fetch(user)
            latest = await asyncio.to_thread(self.store.desired_entry, user.id, entry_id)
            if entry_fingerprint(latest) != expected_fingerprint:
                raise OctopError.localized(ErrorCode.ENTERPRISE_MCP_CATALOG_CONFLICT, user.locale)
            await asyncio.to_thread(self.store.stage_credentials, user.id, entry, credentials)
            await self._apply(user.id)
        return await asyncio.to_thread(self.status, user)

    async def revoke_credentials(self, user: User, entry_id: str) -> dict[str, Any]:
        async with self._lock(user.id):
            if not await asyncio.to_thread(self.store.has_entry, user.id, entry_id):
                raise OctopError.localized(ErrorCode.CONNECTOR_NOT_FOUND, user.locale)
            await asyncio.to_thread(self.store.revoke, user.id, entry_id)
            await self._apply(user.id)
        return await asyncio.to_thread(self.status, user)

    async def check_call(self, user_id: int, server_name: str, fingerprint: str) -> None:
        from octop.infra.connectors.accounts.actor import current_vault_actor

        scoped, actor = current_vault_actor()
        if not scoped or actor != user_id:
            raise OctopError.localized(ErrorCode.ENTERPRISE_ACCESS_DENIED)
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        elif self._loop is not loop:
            if not self._loop.is_running():
                raise OctopError.localized(ErrorCode.ENTERPRISE_UNAVAILABLE)
            await asyncio.wrap_future(
                asyncio.run_coroutine_threadsafe(
                    self.check_call(user_id, server_name, fingerprint), self._loop
                )
            )
            return
        user = await asyncio.to_thread(self.server.user_manager.get_by_id, user_id)
        if user is None:
            raise OctopError.localized(ErrorCode.ENTERPRISE_ACCESS_DENIED)
        client = client_for(self.server)
        if client is None:
            raise OctopError.localized(ErrorCode.ENTERPRISE_NOT_CONFIGURED, user.locale)
        async with self._lock(user_id):
            # Refresh visibility/disable state even if a running turn still owns old tools.
            try:
                await self._fetch(user)
            except OctopError as exc:
                await asyncio.to_thread(self.store.mark_error, user_id, exc.code)
                raise
            entry = await asyncio.to_thread(
                self.store.callable_entry, user_id, server_name, fingerprint
            )
        if entry is None:
            raise OctopError.localized(ErrorCode.ENTERPRISE_ACCESS_DENIED, user.locale)

    def start(self) -> None:
        if self.enabled and (self._task is None or self._task.done()):
            self._task = asyncio.create_task(self._run(), name="enterprise-mcp-sync")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while True:
            try:
                rows = await asyncio.to_thread(self.server.services.user_repo.list)
            except Exception as exc:
                logger.warning("Company MCP user scan failed (%s); retrying", type(exc).__name__)
                await asyncio.sleep(3)
                continue
            for row in rows:
                try:
                    identity = await asyncio.to_thread(
                        self.server.services.secret_repo.get, f"enterprise.identity.{row.id}"
                    )
                    if not identity:
                        continue
                    user = await asyncio.to_thread(self.server.user_manager.get_by_id, row.id)
                    if user is None:
                        continue
                    now = time.monotonic()
                    if now - self._last_attempt.get(user.id, 0) >= 30:
                        self._last_attempt[user.id] = now
                        await self.sync(user)
                    elif await asyncio.to_thread(self.store.pending, user.id):
                        async with self._lock(user.id):
                            await self._apply(user.id)
                except OctopError:
                    pass  # sync() records the localized status for the member.
                except Exception as exc:
                    logger.warning(
                        "Company MCP sync failed for user=%s (%s); retrying",
                        row.id,
                        type(exc).__name__,
                    )
            await asyncio.sleep(3)


def sync_for(server: Any) -> EnterpriseMcpSync:
    syncer = getattr(server, "_enterprise_mcp_sync", None)
    if syncer is None or syncer.services is not server.services:
        syncer = EnterpriseMcpSync(server)
        server._enterprise_mcp_sync = syncer
    return syncer
