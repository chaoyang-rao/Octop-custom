"""Explicit retry abandons pending Graph work without executing or deleting history."""

from __future__ import annotations

import asyncio
from typing import Any

from langchain_core.messages import ToolMessage
from langgraph.graph import END

from octop.i18n import tr
from octop.infra.agents.native_cli.reset import reset_native_session
from octop.infra.db.repos.tasks import TaskRow
from octop.infra.db.services import RepoBundle
from octop.infra.errors import ErrorCode, OctopError


def _data(message: Any) -> Any:
    return message.get("data", message) if isinstance(message, dict) else message


def _field(message: Any, key: str, default: Any = None) -> Any:
    value = _data(message)
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


async def abandon_graph_pending(graph: Any, thread_id: str, *, locale: str) -> int:
    config = {"configurable": {"thread_id": thread_id}}
    state = await graph.aget_state(config)
    if state is None:
        return 0
    messages = list((state.values or {}).get("messages") or [])
    outstanding: dict[str, str] = {}
    for message in messages:
        for call in _field(message, "tool_calls", []) or []:
            call_id = call.get("id") if isinstance(call, dict) else None
            if call_id:
                outstanding[str(call_id)] = str(call.get("name") or "")
        tool_id = _field(message, "tool_call_id")
        if tool_id:
            outstanding.pop(str(tool_id), None)
    pending = bool(
        getattr(state, "next", ())
        or any(getattr(task, "interrupts", ()) for task in getattr(state, "tasks", ()))
    )
    if not outstanding and not pending:
        return 0
    # LangGraph's explicit END update clears queued tasks/interrupts without
    # running a node. Message closure is a state write, never a tool execution.
    if outstanding and "tools" not in graph.get_graph().nodes:
        raise OctopError(
            ErrorCode.SLASH_BAD_ARGS,
            tr("tasks.errors.retry_unsupported", locale),
            status=409,
            details={"task_reason": "retry_unsupported"},
        )
    await graph.aupdate_state(config, None, as_node=END)
    if outstanding:
        closures = [
            ToolMessage(
                content=tr("tasks.retry_abandoned", locale),
                tool_call_id=key,
                name=name,
                status="error",
            )
            for key, name in outstanding.items()
        ]
        await graph.aupdate_state(config, {"messages": closures}, as_node="tools")
        await graph.aupdate_state(config, None, as_node=END)
    final = await graph.aget_state(config)
    if final and (final.next or any(getattr(task, "interrupts", ()) for task in final.tasks)):
        raise OctopError(
            ErrorCode.CHECKPOINT_DELETE_FAILED,
            tr("tasks.errors.retry_unsupported", locale),
            status=409,
        )
    return len(outstanding)


async def reset_for_retry(agents: Any, repos: RepoBundle, row: TaskRow, *, locale: str) -> None:
    if not row.thread_id:
        return
    thread = await asyncio.to_thread(repos.thread_repo.get, row.thread_id)
    if thread is None or thread.user_id != row.user_id or thread.agent_id != row.agent_id:
        raise OctopError(ErrorCode.FORBIDDEN, tr("tasks.errors.thread_not_owned", locale))
    resolver = getattr(agents, "native_execution_ref", None)
    native = await asyncio.to_thread(resolver, row.agent_id) if callable(resolver) else None
    target = row.agent_id
    if isinstance(native, str) and native.startswith("native_cli_"):
        target = await reset_native_session(
            agents, agent_id=row.agent_id, user_id=row.user_id, thread_id=row.thread_id
        )
    else:
        agent = await asyncio.to_thread(repos.agent_repo.get, row.agent_id)
        primary = getattr(getattr(agents, "teams", None), "primary_for_team", None)
        if agent is not None and agent.kind == "team" and callable(primary):
            real = await asyncio.to_thread(primary, row.agent_id)
            if real is None or real.user_id != row.user_id:
                raise OctopError(ErrorCode.FORBIDDEN, tr("tasks.errors.agent_not_owned", locale))
            target = str(real.agent_id)
    for agent_id in dict.fromkeys([target, row.agent_id]):
        await agents.start(agent_id)
        harness = agents.get_agent(agent_id)
        await abandon_graph_pending(harness.graph, row.thread_id, locale=locale)
