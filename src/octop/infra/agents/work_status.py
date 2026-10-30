"""Current-viewer activity summaries; loaded/online does not imply working.

Only bound thread identities are read. Message content, prompts and credentials
are never part of the snapshot. Threadless internal work is deliberately not
attributed to a viewer via a global agent busy flag.
"""

from __future__ import annotations

import asyncio
from typing import Any

_LIFECYCLE = {
    "stopped": "stopped",
    "offline": "stopped",
    "starting": "starting",
    "stopping": "stopping",
    "failed": "failed",
    "error": "failed",
}


async def attach_expert_work_status(
    server: Any, user_id: int, payloads: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Attach per-user visible working/waiting counts to existing agent rows."""
    for payload in payloads:
        state = str(payload.get("state") or "").strip().lower()
        payload.update(
            work_status=_LIFECYCLE.get(state, "unknown"),
            working_count=0,
            waiting_count=0,
        )
    running = [p for p in payloads if str(p.get("state") or "").strip().lower() == "running"]
    if not running:
        return payloads
    runtime = getattr(server, "app_runtime", None)
    services = getattr(server, "services", None)
    registry = getattr(runtime, "agent_registry", None)
    gateway = getattr(runtime, "gateway", None)
    hub = getattr(gateway, "ws_hub", None)
    coordinator = getattr(getattr(gateway, "processor", None), "hitl_coordinator", None)
    store = getattr(coordinator, "store", None)
    list_pairs = getattr(getattr(services, "thread_repo", None), "list_for_user", None)
    active_threads = getattr(registry, "active_thread_ids", None)
    acp_snapshot = getattr(registry, "acp_activity_snapshot", None)
    is_turn_active = getattr(hub, "is_turn_active", None)
    pending_threads = getattr(store, "pending_thread_ids", None)
    # Compatibility with legacy runtimes/test doubles: never invent idle from
    # missing activity data, and never consult unscoped is_agent_active().
    if (
        not callable(list_pairs)
        or not callable(active_threads)
        or not callable(acp_snapshot)
        or not callable(is_turn_active)
        or not callable(pending_threads)
    ):
        return payloads
    pairs = await asyncio.to_thread(list_pairs, user_id)
    agent_ids = {p["agent_id"] for p in running}
    visible: dict[str, set[str]] = {agent_id: set() for agent_id in agent_ids}
    for agent_id, thread_id in pairs:
        if agent_id in visible:
            visible[agent_id].add(thread_id)

    primary_rooms: dict[str, list[str]] = {}
    for payload in payloads:
        primary_id = payload.get("primary_agent_id")
        team_id = payload["agent_id"]
        if payload.get("kind") == "team" and primary_id in visible:
            visible[primary_id].update(visible.get(team_id, set()))
            primary_rooms.setdefault(primary_id, []).append(team_id)

    async def update(payload: dict[str, Any]) -> None:
        agent_id = payload["agent_id"]
        allowed = frozenset(visible[agent_id])
        waiting = set(pending_threads(agent_id=agent_id, user_id=user_id)) & allowed
        for team_id in primary_rooms.get(agent_id, ()):
            waiting.update(set(pending_threads(agent_id=team_id, user_id=user_id)) & allowed)
        regular = (set(active_threads(agent_id)) & allowed) | {
            thread_id for thread_id in allowed if is_turn_active(thread_id)
        }
        acp = await acp_snapshot(agent_id, allowed)
        if acp is None:
            return
        waiting.update(set(acp.get("waiting_thread_ids", ())) & allowed)
        # Explicit ACP execution can coexist with another runner waiting on
        # the same thread. Ordinary invocation/WS flags on a paused thread do
        # not by themselves mean that work is progressing.
        working = (regular - waiting) | (set(acp.get("working_thread_ids", ())) & allowed)
        payload.update(
            work_status="working" if working else "waiting" if waiting else "idle",
            working_count=len(working),
            waiting_count=len(waiting),
        )

    await asyncio.gather(*(update(payload) for payload in running))
    return payloads
