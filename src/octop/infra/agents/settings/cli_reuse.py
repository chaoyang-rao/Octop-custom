"""Reuse the current account's ACP configuration on selected owned experts."""

from __future__ import annotations

import asyncio
import copy
import json
from typing import Any

from octop.infra.agents.experts.copy import owned_expert
from octop.infra.errors import ErrorCode, OctopError


async def _busy(registry: Any, agent_id: str, user_id: int) -> bool:
    if registry.is_agent_active(agent_id) or registry.teams.jobs.is_member_busy(agent_id):
        return True
    processor = getattr(registry, "_team_processor", None)
    store = getattr(getattr(processor, "hitl_coordinator", None), "store", None)
    if store is None:
        return False

    def aliases() -> list[str]:
        return [
            agent_id,
            *[
                row.agent_id
                for row in registry.list_agents(user_id)
                if row.kind == "team" and registry.principal_agent_id(row.agent_id) == agent_id
            ],
        ]

    return any(
        store.pending_thread_ids(agent_id=aid, user_id=user_id)
        for aid in await asyncio.to_thread(aliases)
    )


async def reuse_cli_config(
    registry: Any, source_id: str, targets: list[str], *, user_id: int
) -> dict[str, Any]:
    await asyncio.to_thread(owned_expert, registry, source_id, user_id)
    ids = list(dict.fromkeys(aid for aid in targets if aid != source_id))
    if not ids:
        raise OctopError(ErrorCode.SLASH_BAD_ARGS, "select at least one target expert")
    source_cfg = await asyncio.to_thread(registry.get_config, source_id)
    # Validate the entire selection before changing any expert.
    for aid in ids:
        await asyncio.to_thread(owned_expert, registry, aid, user_id)
        if await _busy(registry, aid, user_id):
            raise OctopError.localized(ErrorCode.AGENT_BUSY)
    # Migrates historical per-expert runner definitions once; definitions remain
    # account-scoped, so command/args/env are not duplicated into target rows.
    await asyncio.to_thread(registry.acp_settings.load_runners, user_id)
    acp = copy.deepcopy(source_cfg.get("acp") or {})
    acp.pop("runners", None)
    source_disabled = "acp_runner" in (source_cfg.get("tools_disabled") or [])
    for aid in ids:
        cfg = await asyncio.to_thread(registry.get_config, aid)
        cfg["acp"] = copy.deepcopy(acp)
        disabled = set(cfg.get("tools_disabled") or [])
        if source_disabled:
            disabled.add("acp_runner")
        else:
            disabled.discard("acp_runner")
        cfg["tools_disabled"] = sorted(disabled)
        await registry.update_config_json(aid, json.dumps(cfg, ensure_ascii=False))
    return {
        "source_agent_id": source_id,
        "agent_ids": ids,
        "tool_enabled": bool(acp.get("tool_enabled", False)),
        "tool_disabled": source_disabled,
    }
