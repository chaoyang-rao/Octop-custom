"""Product-specific coordinator instructions for durable expert tasks."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from deepagents.middleware._utils import append_to_system_message
from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from octop_harness.middleware.runtime import runtime_config

from octop.i18n import tr
from octop.infra.agents.teams.primary import current_primary_room, request_user_id
from octop.infra.tasks.scope import current_coordinator_scope
from octop.infra.utils.locale import DEFAULT_LOCALE


class TaskDispatchMiddleware(AgentMiddleware[Any, Any]):
    def __init__(self, teams: Any, manager_for: Callable[[], Any]) -> None:
        self._teams = teams
        self._manager_for = manager_for

    def _with_briefing(self, request: ModelRequest) -> ModelRequest:
        cfg = runtime_config(request).get("configurable") or {}
        user_id = request_user_id({"configurable": cfg})
        if user_id is None:
            return request
        manager = self._manager_for()
        room = current_primary_room()
        actor = str(cfg.get("agent_id") or "")
        owner = (
            room.team_id
            if room
            and room.primary_id == actor
            and room.thread_id == str(cfg.get("thread_id") or "")
            else actor
        )
        coordination = current_coordinator_scope()
        if (
            coordination is not None
            and coordination.user_id == user_id
            and coordination.origin_agent_id == owner
            and coordination.origin_thread_id == str(cfg.get("thread_id") or "")
        ):
            return request
        task = (
            manager.bound_task(owner, user_id, str(cfg.get("thread_id") or ""))
            if manager is not None
            else None
        )
        if task is not None:
            text = tr("tasks.execution_briefing", str(cfg.get("locale") or DEFAULT_LOCALE))
            dispatch = manager._repos.task_dispatch_repo.get(task.task_id)
            binding = (
                manager._repos.task_coordination_repo.room(dispatch["scope_id"])
                if dispatch and dispatch.get("scope_id")
                else None
            )
            if binding and binding.get("agent_id") and binding.get("thread_id"):
                text += "\n\n" + tr(
                    "tasks.rooms.executor_briefing",
                    str(cfg.get("locale") or DEFAULT_LOCALE),
                    agent_id=binding["agent_id"],
                    thread_id=binding["thread_id"],
                )
            return request.override(
                system_message=append_to_system_message(request.system_message, text)
            )
        if manager is not None:
            peer_goal = manager._repos.task_coordination_repo.scope_for_peer_thread(
                user_id, str(cfg.get("thread_id") or ""), include_closed=True
            )
            if peer_goal is not None:
                text = tr(
                    "tasks.rooms.consultant_briefing", str(cfg.get("locale") or DEFAULT_LOCALE)
                )
                binding = manager._repos.task_coordination_repo.room(peer_goal["scope_id"])
                if binding and binding.get("agent_id") and binding.get("thread_id"):
                    text += "\n\n" + tr(
                        "tasks.rooms.executor_briefing",
                        str(cfg.get("locale") or DEFAULT_LOCALE),
                        agent_id=binding["agent_id"],
                        thread_id=binding["thread_id"],
                    )
                return request.override(
                    system_message=append_to_system_message(request.system_message, text)
                )
        primary = self._teams.primary_expert_for_user(user_id)
        if primary is None or primary.agent_id != cfg.get("agent_id"):
            return request
        text = tr("tasks.dispatch_briefing", str(cfg.get("locale") or DEFAULT_LOCALE))
        if manager is not None:
            goal = manager._repos.task_coordination_repo.scope_for_room(
                user_id, str(cfg.get("thread_id") or ""), include_stopped=True
            )
            if goal is not None:
                members = manager._repos.task_coordination_repo.members(goal["scope_id"])
                text += (
                    "\n\n"
                    + tr("tasks.rooms.group_briefing", str(cfg.get("locale") or DEFAULT_LOCALE))
                    + "\n"
                    + json.dumps(
                        {
                            "scope_id": goal["scope_id"],
                            "state": goal["state"],
                            "original_user_goal": str(goal["goal_text"])[:12000],
                            "user_followup": str(goal.get("user_input") or "")[:6000],
                            "original_conversation": {
                                "agent_id": goal["origin_agent_id"],
                                "thread_id": goal["origin_thread_id"],
                            },
                            "tasks": [
                                {
                                    key: item[key]
                                    for key in ("task_id", "agent_id", "title", "state", "attempt")
                                }
                                for item in members
                            ],
                        },
                        ensure_ascii=False,
                    ).replace("<", "\\u003c")
                )
        return request.override(
            system_message=append_to_system_message(request.system_message, text)
        )

    def wrap_model_call(self, request: ModelRequest, handler: Any) -> ModelResponse:
        return self._tag_review(request, handler(self._with_briefing(request)))

    async def awrap_model_call(self, request: ModelRequest, handler: Any) -> ModelResponse:
        enriched = await asyncio.to_thread(self._with_briefing, request)
        return self._tag_review(request, await handler(enriched))

    def _tag_review(self, request: ModelRequest, response: ModelResponse) -> ModelResponse:
        context = current_coordinator_scope()
        cfg = runtime_config(request).get("configurable") or {}
        room = current_primary_room()
        actor = str(cfg.get("agent_id") or "")
        owner = (
            room.team_id
            if room
            and room.primary_id == actor
            and room.thread_id == str(cfg.get("thread_id") or "")
            else actor
        )
        if (
            context is None
            or context.user_id != request_user_id({"configurable": cfg})
            or context.origin_agent_id != owner
            or context.origin_thread_id != str(cfg.get("thread_id") or "")
        ):
            return response
        return replace(
            response,
            result=[
                message.model_copy(
                    update={
                        "additional_kwargs": {
                            **message.additional_kwargs,
                            "octop_task_scope_id": context.scope_id,
                        }
                    }
                )
                for message in response.result
            ],
        )
