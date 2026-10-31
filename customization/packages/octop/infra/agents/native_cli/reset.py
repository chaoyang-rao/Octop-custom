"""Explicit task retry closes exactly its owned native conversation mapping."""

from __future__ import annotations

import asyncio
from typing import Any

from octop.infra.agents.native_cli.config import NativeCLIError


async def reset_native_session(manager: Any, *, agent_id: str, user_id: int, thread_id: str) -> str:
    """Return the real executor ID after closing its native process/session.

    Caller must first cancel and await its task worker. Canonical graph pending
    calls/HITL are abandoned by the task retry coordinator; history and project
    metadata are never deleted here.
    """

    def executor() -> str:
        row = manager.get_row(agent_id)
        if row is None or row.user_id != user_id:
            raise NativeCLIError("thread_not_owned")
        primary = manager.teams.primary_for_team(agent_id) if row.kind == "team" else row
        if primary is None or primary.user_id != user_id:
            raise NativeCLIError("thread_not_owned")
        thread = manager._repos.thread_repo.get(thread_id)
        if (
            thread is None
            or thread.user_id != user_id
            or thread.agent_id not in {agent_id, primary.agent_id}
        ):
            raise NativeCLIError("thread_not_owned")
        return str(primary.agent_id)

    target = await asyncio.to_thread(executor)
    await manager.native_cli.close_thread(user_id=user_id, agent_id=target, thread_id=thread_id)
    return target
