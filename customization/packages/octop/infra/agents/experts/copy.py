"""Copy an owned expert's definition into an independent, private expert."""

from __future__ import annotations

import asyncio
import copy
import json
from typing import Any

from octop.i18n import tr
from octop.infra.agents.experts.catalog import read_workspace_manifest_bytes
from octop.infra.agents.experts.publish import (
    _is_seedable_path,
    _logical_seed_path,
    _workspace_file_paths,
)
from octop.infra.agents.settings.profile import id_list_from_row, strip_profile_config
from octop.infra.errors import ErrorCode, OctopError


def owned_expert(registry: Any, agent_id: str, user_id: int) -> Any:
    row = registry.get_row(agent_id)
    if row is None:
        raise OctopError(ErrorCode.AGENT_NOT_FOUND, "expert not found")
    if row.user_id != user_id:
        raise OctopError(ErrorCode.FORBIDDEN, "expert must belong to the current user")
    if row.kind == "team":
        raise OctopError(ErrorCode.SLASH_BAD_ARGS, "select an individual expert")
    return row


async def copy_expert(
    registry: Any, source_id: str, *, user_id: int, name: str | None, locale: str
) -> Any:
    from octop.infra.agents.manager import AgentCreateSpec

    source = await asyncio.to_thread(owned_expert, registry, source_id, user_id)
    cfg = copy.deepcopy(await asyncio.to_thread(registry.get_config, source_id))
    cfg = strip_profile_config(cfg)
    for key in ("workspace_dir", "system_files_path", "avatar"):
        cfg.pop(key, None)
    # Runners and credentials are account settings, not new per-expert copies.
    if isinstance(cfg.get("acp"), dict):
        cfg["acp"].pop("runners", None)
    existing = {row.name for row in await asyncio.to_thread(registry.list_agents, user_id)}
    if name is None:
        base = tr("agents.copy_name", locale, name=source.name)
        name = base
        index = 2
        while name in existing:
            name = f"{base} {index}"
            index += 1
    name = name.strip()
    if not name:
        raise OctopError(ErrorCode.SLASH_BAD_ARGS, "expert name required")
    if name in existing:
        raise OctopError(ErrorCode.AGENT_NAME_TAKEN, "expert name already in use")
    source_ws = await asyncio.to_thread(registry.workspace_for_agent, source_id)
    if source_ws is None:
        raise OctopError(ErrorCode.AGENT_NOT_FOUND, "expert workspace unavailable")
    files = []
    for rel in await _workspace_file_paths(source_ws):
        logical = _logical_seed_path(rel)
        if not _is_seedable_path(rel) or logical == "USER.md":
            continue
        data = await source_ws.adownload_bytes(rel)
        if data is not None:
            files.append((logical, data))
    raw = await read_workspace_manifest_bytes(source_ws)
    manifest = json.loads(raw) if raw else {}
    welcome = {
        key: manifest[key]
        for key in ("welcome_message", "quick_prompts", "task_examples")
        if key in manifest
    }

    async def initialize(row: Any, workspace: Any) -> None:
        metadata = {
            **welcome,
            "id": row.agent_id,
            "label": {"zh": name, "en": name},
            "description": {"zh": source.description or "", "en": source.description or ""},
            "prompt_files": [rel for rel, _ in files if "/" not in rel and rel.endswith(".md")],
        }
        await workspace.aupload_many(
            [*files, (".octop/manifest.json", json.dumps(metadata, ensure_ascii=False).encode())]
        )

    spec = AgentCreateSpec(
        name=name,
        user_id=user_id,
        description=source.description,
        persona_mbti=source.persona_mbti,
        default_model=source.default_model,
        system_prompt=source.system_prompt,
        config=cfg,
        icon=source.icon,
        icon_name=source.icon_name,
        color=source.color,
        welcome_message=source.welcome_message,
        skill_package_ids=id_list_from_row(source, "skill_package_ids"),
        knowledge_base_ids=await asyncio.to_thread(
            registry.validate_knowledge_base_ids,
            user_id,
            id_list_from_row(source, "knowledge_base_ids"),
        ),
        mcp_servers=await asyncio.to_thread(
            registry.validate_mcp_servers, user_id, id_list_from_row(source, "mcp_servers")
        ),
    )
    return await registry.create(spec, workspace_initializer=initialize)
