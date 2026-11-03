"""Resume a coordinator through the ordinary processor, history and WS turn path."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from octop_gateway.models import ChannelSubject, InboundMessage

from octop.infra.gateway.process.harness_request import coordinator_input_message_id
from octop.infra.history.projection import message_input
from octop.infra.tasks.scope import CoordinatorContext, coordinator_scope, current_coordinator_scope
from octop.infra.users.identity import User
from octop.infra.users.permissions import user_has_permission
from octop.infra.utils.ulid import new_ulid


class CoordinatorTurnBusy(RuntimeError):
    """A source session is occupied or has unresolved graph/HITL work."""


@dataclass(frozen=True)
class _HistoryBoundary:
    scope_id: str
    previous: frozenset[str]


_BOUNDARY: ContextVar[_HistoryBoundary | None] = ContextVar(
    "coordinator_history_boundary", default=None
)


def _message_id(message: Any) -> str:
    if isinstance(message, dict):
        data = message.get("data", message)
        return str(data.get("id") or "") if isinstance(data, dict) else ""
    return str(getattr(message, "id", "") or "")


def _message_key(message: Any) -> str | None:
    item = message_input(message)
    if item is None:
        return None
    return (
        "id:" + item.message_id
        if item.message_id
        else "wire:" + hashlib.sha256(item.message_json.encode()).hexdigest()
    )


@contextmanager
def _history_boundary(scope_id: str, messages: list[Any]) -> Iterator[None]:
    value = _HistoryBoundary(
        scope_id,
        frozenset(key for message in messages if (key := _message_key(message)) is not None),
    )
    token = _BOUNDARY.set(value)
    try:
        yield
    finally:
        _BOUNDARY.reset(token)


def coordinator_history_chunk(request: dict[str, Any], chunk: dict[str, Any]) -> dict[str, Any]:
    """Prevent old user turns being re-recorded by the last-human projection."""
    context = current_coordinator_scope()
    if (
        context is None
        or request.get("thread_id") != context.origin_thread_id
        or request.get("agent_id") != context.origin_agent_id
        or str(request.get("user")) != str(context.user_id)
        or chunk.get("type") not in {"state_snapshot", "state_update"}
    ):
        return chunk
    data = chunk.get("data")
    messages = data.get("messages") if isinstance(data, dict) else data
    if not isinstance(messages, list):
        return chunk
    seeds = request.get("messages") or []
    seed_ids = {_message_id(message) for message in seeds} - {""}
    human_ids = {
        _message_id(message) for message in seeds if getattr(message, "type", None) == "human"
    }
    anchor = next(
        (index for index, message in enumerate(messages) if _message_id(message) in seed_ids), None
    )
    selected = messages[anchor:] if anchor is not None else messages
    boundary = _BOUNDARY.get()
    previous = (
        boundary.previous
        if boundary is not None and boundary.scope_id == context.scope_id
        else frozenset()
    )
    retained = []
    for message in selected:
        role = (
            (message.get("role") or message.get("type"))
            if isinstance(message, dict)
            else getattr(message, "type", None)
        )
        if role in {"human", "user"} and _message_id(message) not in human_ids:
            continue
        if anchor is None and (key := _message_key(message)) is not None and key in previous:
            continue
        if role in {"ai", "assistant", "tool"}:
            if isinstance(message, dict):
                extra = dict(message.get("additional_kwargs") or {})
                extra["octop_task_scope_id"] = context.scope_id
                message = {**message, "additional_kwargs": extra}
            else:
                extra = dict(getattr(message, "additional_kwargs", None) or {})
                extra["octop_task_scope_id"] = context.scope_id
                message = message.model_copy(update={"additional_kwargs": extra})
        retained.append(message)
    return {**chunk, "data": {**data, "messages": retained} if isinstance(data, dict) else retained}


def _context(scope: dict[str, Any], prompt: str, user_input: str) -> CoordinatorContext:
    user_id = scope.get("user_id")
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
        raise ValueError("coordinator_scope_invalid")
    for field in ("scope_id", "origin_agent_id", "origin_thread_id"):
        if not isinstance(scope.get(field), str) or not scope[field].strip():
            raise ValueError("coordinator_scope_invalid")
    return CoordinatorContext(
        scope_id=scope["scope_id"],
        user_id=user_id,
        origin_agent_id=scope["origin_agent_id"],
        origin_thread_id=scope["origin_thread_id"],
        parent_task_id=scope.get("parent_task_id"),
        parent_attempt=scope.get("parent_attempt"),
        allow_publish=scope.get("allow_publish") in (True, 1),
        active_signature=str(scope.get("active_signature") or ""),
        system_prompt=prompt,
        user_input=user_input,
    )


async def _ready(
    agents: Any, gateway: Any, context: CoordinatorContext
) -> tuple[Any, Any, list[Any]]:
    registry = gateway.thread_registry
    thread = await asyncio.to_thread(registry.get_thread, context.origin_thread_id)
    owner = await asyncio.to_thread(agents.get_row, context.origin_agent_id)
    if (
        thread is None
        or owner is None
        or thread.agent_id != context.origin_agent_id
        or thread.user_id != context.user_id
        or owner.user_id != context.user_id
        or not owner.enabled
    ):
        raise PermissionError("coordinator_origin_unavailable")
    repos = getattr(agents, "_repos", None)
    users = getattr(repos, "user_repo", None) or getattr(gateway.processor, "_user_repo", None)
    if users is None:
        raise PermissionError("coordinator_origin_unavailable")
    user = await asyncio.to_thread(users.get, context.user_id)
    if user is None or user.disabled:
        raise PermissionError("coordinator_origin_unavailable")
    identity = User(
        id=user.id,
        username=user.username,
        role=user.role,
        display_name=user.display_name,
        locale=user.locale,
        permissions=list(user.permissions),
    )
    if not user_has_permission(identity, "tasks"):
        raise PermissionError("coordinator_origin_unavailable")
    if gateway.ws_hub.is_turn_active(thread.thread_id) or gateway.steer.is_hitl_paused(
        thread.thread_id
    ):
        raise CoordinatorTurnBusy("coordinator_turn_busy")
    principal_id = agents.principal_agent_id(context.origin_agent_id)
    principal = await asyncio.to_thread(agents.get_row, principal_id)
    if principal is None or principal.user_id != context.user_id or not principal.enabled:
        raise PermissionError("coordinator_origin_unavailable")
    pending = gateway.processor.hitl_coordinator.store
    for agent_id in {context.origin_agent_id, principal_id}:
        if thread.thread_id in pending.pending_thread_ids(
            agent_id=agent_id, user_id=context.user_id
        ):
            raise CoordinatorTurnBusy("coordinator_hitl_pending")
    harness = agents.get_agent(principal_id)
    state = await harness.graph.aget_state({"configurable": {"thread_id": thread.thread_id}})
    if state is not None and (
        getattr(state, "next", False)
        or any(getattr(task, "interrupts", ()) for task in getattr(state, "tasks", ()))
    ):
        raise CoordinatorTurnBusy("coordinator_graph_pending")
    scopes = getattr(repos, "task_coordination_repo", None)
    room = await asyncio.to_thread(scopes.room, context.scope_id) if scopes is not None else None
    if room and room.get("thread_id") and room["thread_id"] != thread.thread_id:
        target = await asyncio.to_thread(registry.get_thread, room["thread_id"])
        actor = await asyncio.to_thread(agents.get_row, room.get("agent_id"))
        if (
            target is None
            or actor is None
            or target.user_id != context.user_id
            or actor.user_id != context.user_id
            or not actor.enabled
            or target.agent_id != actor.agent_id
        ):
            raise PermissionError("coordinator_origin_unavailable")
        if gateway.ws_hub.is_turn_active(target.thread_id) or gateway.steer.is_hitl_paused(
            target.thread_id
        ):
            raise CoordinatorTurnBusy("coordinator_room_busy")
        for aid in {actor.agent_id, principal_id}:
            if target.thread_id in pending.pending_thread_ids(
                agent_id=aid, user_id=context.user_id
            ):
                raise CoordinatorTurnBusy("coordinator_hitl_pending")
        room_state = await harness.graph.aget_state(
            {"configurable": {"thread_id": target.thread_id}}
        )
        if room_state is not None and (
            getattr(room_state, "next", False)
            or any(getattr(task, "interrupts", ()) for task in getattr(room_state, "tasks", ()))
        ):
            raise CoordinatorTurnBusy("coordinator_graph_pending")
    return thread, identity, list((getattr(state, "values", {}) or {}).get("messages") or [])


async def run_coordinator_turn(
    agents: Any, gateway: Any, scope: dict[str, Any], context_prompt: str, user_input: str = ""
) -> dict[str, Any]:
    """Run an internal host event in the existing source room, without a fake user."""
    context = _context(scope, context_prompt, user_input)
    # Check first so an ordinary active/HITL turn is never touched or queued.
    await _ready(agents, gateway, context)
    manager = gateway.channel_manager
    channel = manager.get_channel(gateway.dashboard_channel_id) if manager is not None else None
    if manager is None or channel is None:
        raise RuntimeError("coordinator_gateway_unavailable")
    started = asyncio.Event()
    admission_open = True
    outcome: dict[str, Any] = {"output": "", "failed": True, "paused": False}

    async def operation() -> None:
        nonlocal outcome
        if not admission_open:
            return
        started.set()
        thread, identity, previous = await _ready(agents, gateway, context)
        connection = f"coordinator:{context.scope_id}:{new_ulid()}"
        completion: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()

        async def observe(_frame: dict[str, Any]) -> None:
            return None

        metadata: dict[str, Any] = {
            "thread_id": thread.thread_id,
            "session_key": thread.session_key,
            "ws_connection_id": connection,
            "user_is_admin": identity.is_admin,
            "_octop_turn_completion": completion,
        }
        if user_input:
            resume_seq = scope.get("resume_seq", 0)
            if isinstance(resume_seq, bool) or not isinstance(resume_seq, int) or resume_seq < 0:
                raise ValueError("coordinator_scope_invalid")
            metadata["client_message_id"] = coordinator_input_message_id(
                context.scope_id, resume_seq, user_input
            )
        message = InboundMessage(
            channel_id=gateway.dashboard_channel_id,
            channel_type="dashboard",
            tenant_id=context.origin_agent_id,
            channel_subject=ChannelSubject(subject_id=str(context.user_id), chat_type="dm"),
            content=[],
            metadata=metadata,
        )
        gateway.ws_hub.register(connection, observe)
        try:
            with coordinator_scope(context), _history_boundary(context.scope_id, previous):
                await channel.handle_inbound(message)
            if not completion.done():
                raise RuntimeError("coordinator_turn_incomplete")
            result = completion.result()
            outcome = {
                "output": str(result.get("output") or ""),
                "failed": bool(result.get("failed")),
                "paused": bool(result.get("paused")),
            }
        except asyncio.CancelledError:
            # Still inside this turn's transport lock: a later user turn cannot
            # accidentally receive this cancellation signal.
            agents.cancel_stream(context.origin_agent_id, context.origin_thread_id)
            raise
        finally:
            if not completion.done():
                completion.cancel()
            gateway.ws_hub.unregister(connection)

    job = asyncio.create_task(
        manager.run_in_session(
            gateway.dashboard_channel_id, f"thread:{context.origin_thread_id}", operation
        )
    )
    entered = asyncio.create_task(started.wait())
    try:
        await asyncio.wait({job, entered}, timeout=0.1, return_when=asyncio.FIRST_COMPLETED)
        if not started.is_set():
            admission_open = False
            if job.done():
                await job
            else:
                job.cancel()
                await asyncio.gather(job, return_exceptions=True)
            raise CoordinatorTurnBusy("coordinator_transport_busy")
        await job
        return outcome
    except asyncio.CancelledError:
        admission_open = False
        job.cancel()
        await asyncio.gather(job, return_exceptions=True)
        raise
    finally:
        entered.cancel()
        await asyncio.gather(entered, return_exceptions=True)
