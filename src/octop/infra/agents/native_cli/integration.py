"""Small hooks keeping native execution inside the existing harness graph."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Any

from langchain_core.tools import StructuredTool
from octop_harness.config import HarnessAgentConfig
from pydantic import BaseModel, Field

from octop.i18n import tr
from octop.infra.agents.native_cli.config import (
    NativeCLIError,
    NativeSpec,
    native_provider,
    native_ref,
)
from octop.infra.agents.native_cli.factory import NativeRoutingFactory
from octop.infra.agents.native_cli.runtime import NativeContext
from octop.infra.agents.teams.primary import current_primary_room


class NativePermissionArguments(BaseModel):
    request_id: str = Field(min_length=1, max_length=100)
    runner: str
    title: str
    operation: dict[str, Any]


def native_permission_tool(locale: str) -> Any:
    import json

    async def approve(request_id: str, runner: str, title: str, operation: dict[str, Any]) -> str:
        return json.dumps({"approved": True, "request_id": request_id})

    return StructuredTool.from_function(
        name="native_cli_permission",
        coroutine=approve,
        args_schema=NativePermissionArguments,
        description=tr("nativeCli.tools.permission", locale),
    )


def native_owner(manager: Any, agent_id: str) -> int | None:
    row = manager.get_row(agent_id)
    if row is None or row.user_id is None or bool(row.is_shared):
        return None
    user = manager._repos.user_repo.get(row.user_id)
    if user is None or user.disabled or user.role != "admin":
        return None
    spec = NativeSpec.from_config(manager.get_config(agent_id))
    return int(row.user_id) if spec.enabled else None


async def resolve_native_context(
    manager: Any, agent_id: str, thread_id: str, user_id: int
) -> NativeContext:
    def resolve() -> NativeContext:
        row = manager.get_row(agent_id)
        if row is None or row.user_id != user_id or bool(row.is_shared):
            raise NativeCLIError("actor_required")
        user = manager._repos.user_repo.get(user_id)
        locale = str(user.locale or "en") if user else "en"
        if user is None or user.disabled or user.role != "admin":
            raise NativeCLIError("admin_required", locale)
        thread = manager._repos.thread_repo.get(thread_id)
        room = current_primary_room()
        allowed_team = bool(
            room
            and room.primary_id == agent_id
            and room.thread_id == thread_id
            and room.user_id == user_id
            and thread
            and thread.agent_id == room.team_id
        )
        if (
            thread is None
            or thread.user_id != user_id
            or (thread.agent_id != agent_id and not allowed_team)
        ):
            raise NativeCLIError("thread_not_owned", locale)
        config = manager.get_config(agent_id)
        spec = NativeSpec.from_config(config)
        if not spec.enabled:
            raise NativeCLIError("not_configured", locale)
        from octop_harness.acp.models import ACPRunnerConfig

        runners = manager.acp_settings.load_runners(user_id)
        raw = runners.get(spec.runner)
        runner = ACPRunnerConfig.from_dict(raw) if isinstance(raw, dict) else None
        if runner is None or not runner.enabled:
            raise NativeCLIError("runner_disabled", locale)
        project = str(getattr(thread, "project_path", None) or "").strip()
        if project:
            cwd = Path(project).expanduser().resolve()
        else:
            # Workspace path mapping stays in Octop's existing workspace layer.
            # Remote content continues through graph MCP tools; no implicit copy.
            cwd = manager.resolve_workspace_dir(agent_id, persist_if_missing=False).resolve()
        if not cwd.is_dir():
            raise NativeCLIError("cwd_unavailable", locale)
        return NativeContext(user_id, agent_id, thread_id, str(cwd), spec, runner, locale)

    return await asyncio.to_thread(resolve)


def apply_native_config(manager: Any, row: Any, config: HarnessAgentConfig) -> HarnessAgentConfig:
    spec = NativeSpec.from_config(manager.get_config(row.agent_id))
    if not spec.enabled:
        effective = manager.native_execution_ref(row.agent_id) if row.kind == "team" else None
        if effective:
            primary_id = effective.partition("/")[0].removeprefix("native_cli_")
            factory = manager._harness_manager.shared_factory if manager._harness_manager else None
            if not isinstance(factory, NativeRoutingFactory):
                raise NativeCLIError("not_configured")
            factory.ensure_native_provider(primary_id)
            return replace(
                config,
                providers=[
                    native_provider(primary_id),
                    *(p for p in config.providers if not p.id.startswith("native_cli_")),
                ],
                default_model=effective,
                model_retry_enabled=False,
            )
        return config
    owner = native_owner(manager, row.agent_id)
    if owner is None:
        raise NativeCLIError("actor_required")
    factory = manager._harness_manager.shared_factory if manager._harness_manager else None
    if not isinstance(factory, NativeRoutingFactory):
        raise NativeCLIError("not_configured")
    factory.ensure_native_provider(row.agent_id)
    user = manager._repos.user_repo.get(owner)
    locale = str(user.locale or "en") if user else "en"
    # This entry is added after global/thread approval bypass has been applied.
    interrupt_on = {
        **(config.interrupt_on or {}),
        "native_cli_permission": {"allowed_decisions": ["approve", "reject"]},
    }
    providers = [
        native_provider(row.agent_id),
        *(p for p in config.providers if not p.id.startswith("native_cli_")),
    ]
    return replace(
        config,
        providers=providers,
        default_model=native_ref(row.agent_id),
        multimodal_model=None,
        model_selector=lambda _state, _config: native_ref(row.agent_id),
        model_retry_enabled=False,
        interrupt_on=interrupt_on,
        tools=[*(config.tools or []), native_permission_tool(locale)],
    )
