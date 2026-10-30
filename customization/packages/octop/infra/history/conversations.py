"""Read-only, current-user conversation retrieval for experts and team context."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any, Literal

from langchain_core.tools import StructuredTool
from langgraph.config import get_config

from octop.i18n import tr
from octop.infra.agents.teams.primary import current_primary_room, request_user_id
from octop.infra.utils.locale import DEFAULT_LOCALE


def visible_message(row: Any) -> dict[str, Any]:
    wire = json.loads(row.message_json)
    data = wire.get("data") if isinstance(wire.get("data"), dict) else wire
    content = data.get("content", "")
    attachments = []
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict) or block.get("type") == "text":
                continue
            kind = str(block.get("type") or "")
            if kind in {"image", "image_url", "input_image", "file", "audio", "video"}:
                item: dict[str, Any] = {"kind": kind}
                if isinstance(block.get("workspace_path"), str):
                    item["workspace_path"] = block["workspace_path"]
                if isinstance(block.get("filename"), str):
                    item["filename"] = block["filename"]
                attachments.append(item)
    if isinstance(content, list):
        content = "\n".join(
            str(block.get("text", ""))
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    role = {"human": "user", "ai": "assistant"}.get(row.role, row.role)
    return {
        "seq": row.seq,
        "message_id": row.message_id,
        "role": role,
        "content": content if isinstance(content, str) else "",
        "speaker_agent_id": (data.get("additional_kwargs") or {}).get("speaker_agent_id"),
        "created_at": row.created_at,
        "attachments": attachments,
    }


class ConversationHistory:
    def __init__(
        self,
        repos: Any,
        teams: Any = None,
        *,
        page_reader: Callable[..., Awaitable[dict[str, Any]]] | None = None,
    ) -> None:
        self.repos = repos
        self.teams = teams
        self.page_reader = page_reader

    def _is_admin(self, user_id: int) -> bool:
        user = self.repos.user_repo.get(user_id)
        return bool(user is not None and user.role == "admin")

    @staticmethod
    def _may_read_agent(user_id: int, agent: Any, is_admin: bool) -> bool:
        return bool(
            agent is not None and (agent.user_id == user_id or bool(agent.is_shared) or is_admin)
        )

    def require_visible_agent(self, user_id: int, agent_id: str) -> Any:
        agent = self.repos.agent_repo.get(agent_id)
        if not self._may_read_agent(user_id, agent, self._is_admin(user_id)):
            raise PermissionError("expert access unavailable")
        return agent

    def owned_thread(self, user_id: int, thread_id: str) -> Any:
        row = self.repos.thread_repo.get(thread_id)
        if row is None or row.user_id != user_id:
            raise PermissionError("conversation not owned")
        self.require_visible_agent(user_id, row.agent_id)
        return row

    def _summary(self, row: Any) -> dict[str, Any]:
        agent = self.repos.agent_repo.get(row.agent_id)
        primary = self.teams.primary_for_team(row.agent_id) if self.teams is not None else None
        return {
            "thread_id": row.thread_id,
            "agent_id": row.agent_id,
            "agent_name": agent.name if agent else row.agent_id,
            "primary_agent_id": primary.agent_id if primary else None,
            "primary_agent_name": primary.name if primary else None,
            "kind": getattr(agent, "kind", "expert"),
            "title": row.title,
            "last_active": row.last_active,
            "projection_status": self.repos.thread_message_repo.projection_status(row.thread_id),
        }

    def read(
        self,
        user_id: int,
        thread_id: str,
        *,
        before_seq: int | None = None,
        limit: int = 20,
        include_tools: bool = False,
    ) -> dict[str, Any]:
        thread = self.owned_thread(user_id, thread_id)
        end = (
            (before_seq - 1)
            if before_seq is not None
            else self.repos.thread_message_repo.head(thread_id)
        )
        rows = self.repos.thread_message_repo.range_page(thread_id, 0, end, limit + 1)
        more = len(rows) > limit
        selected = list(reversed(rows[:limit]))
        messages = []
        is_admin = self._is_admin(user_id)
        for row in selected:
            item = visible_message(row)
            if item["role"] == "system" or (item["role"] == "tool" and not include_tools):
                continue
            if item["role"] not in {"user", "assistant", "tool"}:
                continue
            if not item["speaker_agent_id"] and item["role"] != "user":
                item["speaker_agent_id"] = thread.agent_id
            speaker = (
                self.repos.agent_repo.get(item["speaker_agent_id"])
                if item["speaker_agent_id"]
                else None
            )
            item["speaker_name"] = (
                speaker.name
                if speaker is not None and self._may_read_agent(user_id, speaker, is_admin)
                else item["speaker_agent_id"]
            )
            if item["content"] or item["attachments"]:
                messages.append(item)
        return {
            **self._summary(thread),
            "history_ready": self.repos.thread_message_repo.projection_status(thread_id) == "ready",
            "messages": messages,
            "has_more": more,
            "next_before_seq": selected[0].seq if more and selected else None,
        }

    async def aread(
        self,
        user_id: int,
        thread_id: str,
        *,
        limit: int = 20,
        cursor: str | None = None,
        include_tools: bool = False,
    ) -> dict[str, Any]:
        if self.page_reader is None:
            return await asyncio.to_thread(
                self.read, user_id, thread_id, limit=limit, include_tools=include_tools
            )
        thread = await asyncio.to_thread(self.owned_thread, user_id, thread_id)
        page = await self.page_reader(thread.agent_id, thread_id, limit=limit, cursor=cursor)
        summary = await asyncio.to_thread(self._summary, thread)

        def project() -> list[dict[str, Any]]:
            result = []
            is_admin = self._is_admin(user_id)
            for wire in page["messages"]:
                data = wire.get("data") if isinstance(wire.get("data"), dict) else wire
                row = SimpleNamespace(
                    message_json=json.dumps(wire),
                    role=wire.get("type") or data.get("role"),
                    seq=None,
                    message_id=data.get("id"),
                    created_at=(data.get("additional_kwargs") or {}).get("checkpoint_ts"),
                )
                item = visible_message(row)
                if item["role"] not in (
                    {"user", "assistant", "tool"} if include_tools else {"user", "assistant"}
                ):
                    continue
                if not item["speaker_agent_id"] and item["role"] != "user":
                    primary = self.teams.primary_for_team(thread.agent_id) if self.teams else None
                    item["speaker_agent_id"] = primary.agent_id if primary else thread.agent_id
                speaker = (
                    self.repos.agent_repo.get(item["speaker_agent_id"])
                    if item["speaker_agent_id"]
                    else None
                )
                item["speaker_name"] = (
                    speaker.name
                    if speaker is not None and self._may_read_agent(user_id, speaker, is_admin)
                    else item["speaker_agent_id"]
                )
                if item["content"] or item["attachments"]:
                    result.append(item)
            return result

        return {
            **summary,
            "history_ready": True,
            "messages": await asyncio.to_thread(project),
            "has_more": page["has_more"],
            "next_cursor": page.get("next_cursor"),
        }

    def list(
        self, user_id: int, *, agent_id: str = "", limit: int = 20, offset: int = 0
    ) -> dict[str, Any]:
        rows = self.repos.thread_repo.list_owned_conversations(
            user_id,
            agent_id=agent_id,
            limit=limit + 1,
            offset=offset,
            is_admin=self._is_admin(user_id),
        )
        return {
            "conversations": [self._summary(row) for row in rows[:limit]],
            "has_more": len(rows) > limit,
            "next_offset": offset + min(len(rows), limit),
        }

    def search(
        self, user_id: int, query: str, *, agent_id: str = "", limit: int = 20, offset: int = 0
    ) -> dict[str, Any]:
        if not query.strip():
            raise ValueError("empty query")
        rows = self.repos.thread_message_repo.search_owned_conversations(
            user_id,
            query,
            agent_id=agent_id,
            limit=limit * 5,
            offset=offset,
            is_admin=self._is_admin(user_id),
        )
        matches = []
        scanned = 0
        for thread_id, row in rows:
            scanned += 1
            item = visible_message(row)
            if (
                item["role"] not in {"user", "assistant"}
                or query.casefold() not in item["content"].casefold()
            ):
                continue
            thread = self.owned_thread(user_id, thread_id)
            at = item["content"].casefold().index(query.casefold())
            matches.append(
                {
                    **self._summary(thread),
                    "seq": row.seq,
                    "snippet": item["content"][max(0, at - 120) : at + len(query) + 300],
                }
            )
            if len(matches) >= limit:
                break
        return {
            "matches": matches,
            "next_offset": offset + scanned,
            "has_more": scanned < len(rows) or len(rows) == limit * 5,
        }


def build_conversation_tools(
    repos: Any,
    teams: Any = None,
    *,
    page_reader: Callable[..., Awaitable[dict[str, Any]]] | None = None,
) -> list[StructuredTool]:
    history = ConversationHistory(repos, teams, page_reader=page_reader)

    async def conversation_history(
        action: Literal["list", "read", "search"] = "list",
        thread_id: str = "",
        query: str = "",
        cursor: str = "",
        agent_id: str = "",
        before_seq: int | None = None,
        limit: int = 20,
        offset: int = 0,
        include_tools: bool = False,
    ) -> str:
        """Retrieve relevant earlier private or group conversations for the current user.

        list discovers thread ids; search finds visible text and message seqs;
        read returns actual messages with speaker identity, oldest first. Read
        older pages with next_cursor when returned, otherwise next_before_seq. agent_id filters the room owner, not
        the speaker; omit it when looking for a member's group contributions.
        Never invent history. Private and group records remain separate.
        """
        locale: str = DEFAULT_LOCALE
        try:
            cfg = dict(get_config().get("configurable") or {})
            locale = str(cfg.get("locale") or DEFAULT_LOCALE)
            user_id = request_user_id({"configurable": cfg})
            scope = current_primary_room()
            if user_id is None and scope is not None:
                user_id = scope.user_id
            if user_id is None:
                raise PermissionError("missing current user")
            actor_id = str(cfg.get("agent_id") or (scope.primary_id if scope else ""))
            history.require_visible_agent(user_id, actor_id)
            limit = min(50, max(1, limit))
            if action == "read" and page_reader is not None and before_seq is None:
                result = await history.aread(
                    user_id,
                    thread_id,
                    limit=limit,
                    cursor=cursor or None,
                    include_tools=include_tools,
                )
            elif action == "read":
                result = await asyncio.to_thread(
                    history.read,
                    user_id,
                    thread_id,
                    before_seq=before_seq,
                    limit=limit,
                    include_tools=include_tools,
                )
            elif action == "search":
                result = await asyncio.to_thread(
                    history.search,
                    user_id,
                    query,
                    agent_id=agent_id,
                    limit=limit,
                    offset=max(0, offset),
                )
            else:
                result = await asyncio.to_thread(
                    history.list, user_id, agent_id=agent_id, limit=limit, offset=max(0, offset)
                )
            if action == "search":
                result["coverage"] = (
                    "Indexed projection text only; use list and paginated read for archive/checkpoint history. No matches does not prove absence."
                )
            return json.dumps(result, ensure_ascii=False)
        except (PermissionError, ValueError, RuntimeError):
            return json.dumps(
                {"error": tr("teams.history_unavailable", locale)}, ensure_ascii=False
            )

    return [
        StructuredTool.from_function(
            coroutine=conversation_history,
            name="conversation_history",
            description=conversation_history.__doc__ or "",
        )
    ]
