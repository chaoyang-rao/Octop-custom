"""Minimal share-sheet access to owned experts and their normal inbound uploads."""

from __future__ import annotations

import asyncio
from typing import Any

from octop.infra.errors import ErrorCode, OctopError
from octop.infra.mobile_access.access import effective_device_scopes
from octop.infra.mobile_access.service import service_for
from octop.infra.users.permissions import user_has_permission


async def share_expert_labels(server: Any, user_id: int) -> list[dict[str, str]]:
    rows = await asyncio.to_thread(
        server.services.agent_repo.list_by_user, user_id, include_disabled=False
    )
    return [{"agent_id": row.agent_id, "name": row.name} for row in rows]


async def prepare_share_upload(server: Any, *, token: str, agent_id: str) -> None:
    """Called only for an explicit share send, before the regular upload adapter.

    Starting the owned runtime does not invoke a model; TaskManager's enqueue
    and execution still enforce the account's current task permission.
    """
    session = await asyncio.to_thread(service_for(server).authenticate, token)
    owner = await asyncio.to_thread(server.user_manager.get_by_id, session.user_id)
    if owner is None:
        raise OctopError(ErrorCode.USER_DISABLED, "user not active")
    scopes = set(effective_device_scopes(owner, session.scopes))
    if (
        session.kind != "share"
        or not {"chat", "files", "tasks"} <= scopes
        or not user_has_permission(owner, "tasks")
    ):
        raise OctopError(
            ErrorCode.FORBIDDEN, "sharing files to a task requires the existing task grant"
        )
    row = await asyncio.to_thread(server.services.agent_repo.get, agent_id)
    if row is None or row.user_id != owner.id or not row.enabled:
        raise OctopError(ErrorCode.FORBIDDEN, "owned enabled expert required")
    await server.app_runtime.agent_registry.start(agent_id)
