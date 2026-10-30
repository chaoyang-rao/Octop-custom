"""Ephemeral room context for the real expert; never merge independent chat logs."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import HumanMessage, SystemMessage
from octop_harness.middleware.runtime import runtime_config

from octop.i18n import tr
from octop.infra.agents.teams.primary import current_primary_room, request_user_id
from octop.infra.history.conversations import ConversationHistory
from octop.infra.utils.locale import DEFAULT_LOCALE


class TeamConversationContextMiddleware(AgentMiddleware[Any, Any]):
    def __init__(
        self,
        *,
        repos: Any,
        teams: Any,
        workspace_for: Callable[[str], Any] | None = None,
        page_reader: Callable[..., Awaitable[dict[str, Any]]] | None = None,
    ) -> None:
        self._repos = repos
        self._teams = teams
        self._history = ConversationHistory(repos, teams, page_reader=page_reader)
        self._workspace_for = workspace_for

    def _prefix(self, cfg: dict[str, Any], tools: Any) -> tuple[list[Any], str | None, str | None]:
        locale = str(cfg.get("locale") or DEFAULT_LOCALE)
        names = {
            getattr(tool, "name", "")
            if not isinstance(tool, dict)
            else tool.get("name") or (tool.get("function") or {}).get("name")
            for tool in tools or []
        }
        prefix: list[Any] = []
        if "conversation_history" in names:
            prefix.append(SystemMessage(content=tr("teams.history_access_briefing", locale)))
        team_id = str(cfg.get("octop_team_id") or "")
        room_id = str(cfg.get("octop_team_thread_id") or "")
        user_id = request_user_id({"configurable": cfg})
        scope = current_primary_room()
        if not team_id and scope is not None and str(cfg.get("thread_id") or "") == scope.thread_id:
            team_id, room_id = scope.team_id, scope.thread_id
            user_id = user_id or scope.user_id
        if not team_id and user_id is not None:
            account_primary = self._teams.primary_expert_for_user(user_id)
            if account_primary is not None and account_primary.agent_id == str(
                cfg.get("agent_id") or ""
            ):
                prefix.append(
                    SystemMessage(
                        content=tr(
                            "teams.primary_account_briefing", locale, name=account_primary.name
                        )
                    )
                )
        if not team_id and user_id is not None:
            thread_id = str(cfg.get("thread_id") or "")
            candidate = self._repos.thread_repo.get(thread_id) if thread_id else None
            if candidate is not None and candidate.user_id == user_id:
                primary = self._teams.primary_for_team(candidate.agent_id)
                if primary is not None and primary.agent_id == str(cfg.get("agent_id") or ""):
                    team_id, room_id = candidate.agent_id, candidate.thread_id
        if not team_id or not room_id:
            return prefix, None, None
        if user_id is None:
            raise PermissionError(tr("teams.history_unavailable", locale))
        thread = self._history.owned_thread(user_id, room_id)
        team = self._repos.agent_repo.get(team_id)
        if thread.agent_id != team_id or team is None:
            raise PermissionError(tr("teams.history_unavailable", locale))
        primary = self._teams.require_primary(team.user_id)
        actor_id = str(cfg.get("agent_id") or (scope.primary_id if scope else ""))
        if actor_id not in self._teams.visible_member_ids(team_id):
            raise PermissionError(tr("teams.history_unavailable", locale))
        actor = self._history.require_visible_agent(user_id, actor_id)
        role_key = (
            "teams.primary_room_briefing"
            if actor_id == primary.agent_id
            else "teams.member_room_briefing"
        )
        prefix.append(
            SystemMessage(
                content=tr(
                    role_key,
                    locale,
                    name=actor.name if actor else actor_id,
                    team=team.name,
                    primary=primary.name,
                )
            )
        )
        return prefix, team_id, room_id

    def _transcript(
        self, team_id: str, room_id: str, page: dict[str, Any], locale: str
    ) -> HumanMessage:
        team = self._repos.agent_repo.get(team_id)
        primary = self._teams.require_primary(team.user_id)
        # Keep model input bounded. Full older messages remain available through
        # the explicit paginated history tool, without touching either checkpoint.
        messages = page["messages"]
        while len(messages) > 1 and len(json.dumps(messages, ensure_ascii=False)) > 32000:
            messages = messages[1:]
            page["has_more"] = True
        if messages and len(json.dumps(messages, ensure_ascii=False)) > 32000:
            messages = [
                {**messages[-1], "content": messages[-1]["content"][-30000:], "excerpt": True}
            ]
            page["has_more"] = True
        payload = {
            "group": {
                "name": team.name,
                "description": team.description,
                "primary_agent_id": primary.agent_id,
                "members": self._teams.visible_member_ids(team_id),
            },
            "thread_id": room_id,
            "messages": messages,
            "has_more": page["has_more"],
            "older_before_seq": page.get("next_before_seq"),
            "next_cursor": page.get("next_cursor"),
        }
        return HumanMessage(
            content=tr("teams.room_transcript_header", locale)
            + "\n"
            + json.dumps(payload, ensure_ascii=False)
        )

    def wrap_model_call(
        self, request: ModelRequest[Any], handler: Callable[[ModelRequest[Any]], ModelResponse[Any]]
    ) -> ModelResponse[Any]:
        cfg = dict(runtime_config(request).get("configurable") or {})
        prefix, team_id, room_id = self._prefix(cfg, request.tools)
        if team_id and room_id:
            scope = current_primary_room()
            user_id = request_user_id({"configurable": cfg}) or (scope.user_id if scope else None)
            assert user_id is not None
            page = self._history.read(user_id, room_id, limit=100)
            prefix.append(
                self._transcript(team_id, room_id, page, str(cfg.get("locale") or DEFAULT_LOCALE))
            )
        prepared = request.override(messages=[*prefix, *request.messages])
        if team_id and self._workspace_for is not None:
            from octop.infra.agents.middleware.workspace_image import (
                WorkspaceImageMaterializeMiddleware,
            )

            workspace = self._workspace_for(team_id)
            if workspace is not None:
                return WorkspaceImageMaterializeMiddleware(workspace=workspace).wrap_model_call(
                    prepared, handler
                )
        return handler(prepared)

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        cfg = dict(runtime_config(request).get("configurable") or {})
        prefix, team_id, room_id = await asyncio.to_thread(self._prefix, cfg, request.tools)
        if team_id and room_id:
            scope = current_primary_room()
            user_id = request_user_id({"configurable": cfg}) or (scope.user_id if scope else None)
            assert user_id is not None
            page = await self._history.aread(user_id, room_id, limit=100)
            prefix.append(
                await asyncio.to_thread(
                    self._transcript,
                    team_id,
                    room_id,
                    page,
                    str(cfg.get("locale") or DEFAULT_LOCALE),
                )
            )
        prepared = request.override(messages=[*prefix, *request.messages])
        if team_id and self._workspace_for is not None:
            from octop.infra.agents.middleware.workspace_image import (
                WorkspaceImageMaterializeMiddleware,
            )

            workspace = await asyncio.to_thread(self._workspace_for, team_id)
            if workspace is not None:
                return await WorkspaceImageMaterializeMiddleware(
                    workspace=workspace
                ).awrap_model_call(prepared, handler)
        return await handler(prepared)
