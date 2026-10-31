"""Owned conversation controls and message references resolved from real history."""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any, cast

from octop.i18n import tr
from octop.infra.agents.threads.fork import fork_dashboard_thread
from octop.infra.conversations.models import MessageLocator, QuotedMessage, QuoteReference
from octop.infra.db.repos.threads import ThreadRow
from octop.infra.db.services import RepoBundle
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.gateway.threads import ThreadRegistry
from octop.infra.history.conversations import ConversationHistory
from octop.infra.history.reader import read_page
from octop.infra.users.identity import User
from octop.infra.users.permissions import user_has_permission
from octop.infra.utils.locale import DEFAULT_LOCALE
from octop.infra.utils.ulid import new_ulid

REACTIONS = ("👍", "❤️", "🎉", "💡", "🤔", "👎")


class ConversationService:
    def __init__(
        self,
        *,
        repos: RepoBundle,
        agents: Any,
        gateway: Any,
        archive: Any = None,
        skill_store: Any = None,
        task_manager: Any = None,
    ) -> None:
        self.repos = repos
        self.agents = agents
        self.gateway = gateway
        self.archive = archive
        self.skill_store = skill_store
        self.task_manager = task_manager
        self._locales: dict[int, str] = {}
        self.history = ConversationHistory(
            repos, getattr(agents, "teams", None), page_reader=self._read_page
        )

    async def _read_page(self, agent_id: str, thread_id: str, **kwargs: Any) -> dict[str, Any]:
        return await read_page(
            self.archive,
            self.agents,
            agent_id,
            thread_id,
            messages=self.repos.thread_message_repo,
            **kwargs,
        )

    def identity(self, user_id: int, permission: str | None = None) -> User:
        row = self.repos.user_repo.get(user_id)
        if row is None or row.disabled:
            raise self.error("forbidden", user_id, 403)
        user = User(
            id=row.id,
            username=row.username,
            role=row.role,
            display_name=row.display_name,
            locale=row.locale,
            permissions=list(row.permissions),
        )
        self._locales[user_id] = row.locale
        if permission and not user_has_permission(user, permission):
            raise self.error("forbidden", user_id, 403)
        return user

    def error(self, reason: str, user_id: int, status: int = 400) -> OctopError:
        return OctopError(
            ErrorCode.SLASH_BAD_ARGS,
            tr(f"conversations.errors.{reason}", self._locales.get(user_id, DEFAULT_LOCALE)),
            status=status,
            details={"conversation_reason": reason},
        )

    def owned(self, user_id: int, thread_id: str) -> ThreadRow:
        self.identity(user_id)
        try:
            return cast(ThreadRow, self.history.owned_thread(user_id, thread_id))
        except PermissionError:
            raise self.error("not_found", user_id, 404) from None

    def owned_agent(self, user_id: int, agent_id: str) -> Any:
        self.identity(user_id)
        row = self.repos.agent_repo.get(agent_id)
        if row is None or row.user_id != user_id:
            raise self.error("agent_not_owned", user_id, 404)
        return row

    async def browse(
        self,
        user_id: int,
        *,
        archived: bool = False,
        agent_id: str = "",
        query: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        await asyncio.to_thread(self.identity, user_id)
        rows = await asyncio.to_thread(
            self.repos.conversation_repo.browse,
            user_id,
            archived=archived,
            agent_id=agent_id,
            query=query.strip(),
            limit=limit + 1,
            offset=offset,
        )
        items = []
        for row in rows[:limit]:
            try:
                await asyncio.to_thread(self.owned, user_id, row.thread_id)
            except OctopError:
                continue
            items.append(await self.summary(user_id, row))
        return {
            "conversations": items,
            "has_more": len(rows) > limit,
            "next_offset": offset + limit,
        }

    async def summary(self, user_id: int, row: ThreadRow) -> dict[str, Any]:
        agent = await asyncio.to_thread(self.repos.agent_repo.get, row.agent_id)
        origin = await asyncio.to_thread(self.repos.conversation_repo.origin, row.thread_id)
        return {
            "thread_id": row.thread_id,
            "agent_id": row.agent_id,
            "agent_name": agent.name if agent else row.agent_id,
            "kind": agent.kind if agent else "expert",
            "title": row.title,
            "archived": row.archived,
            "last_active": row.last_active,
            "created_at": row.created_at,
            "project_name": row.project_name,
            "origin": origin,
        }

    async def archive_thread(self, user_id: int, thread_id: str, archived: bool) -> dict[str, Any]:
        row = await asyncio.to_thread(self.owned, user_id, thread_id)
        # An archived chat stays readable, and active executions keep their own locks/history.
        await asyncio.to_thread(
            self.repos.thread_repo.set_archived, thread_id, user_id=user_id, archived=archived
        )
        if archived:
            await asyncio.to_thread(self.repos.session_repo.clear_unread_for_thread, thread_id)
            await asyncio.to_thread(
                self.repos.session_repo.detach_archived_dashboard_thread, thread_id, user_id
            )
        updated = await asyncio.to_thread(self.repos.thread_repo.get, thread_id)
        assert updated is not None
        await self._changed(user_id, row, "archived" if archived else "restored")
        return await self.summary(user_id, updated)

    async def messages(
        self, user_id: int, thread_id: str, *, limit: int = 50, cursor: str | None = None
    ) -> dict[str, Any]:
        await asyncio.to_thread(self.owned, user_id, thread_id)
        return await self.history.aread(user_id, thread_id, limit=limit, cursor=cursor)

    async def resolve(self, user_id: int, thread_id: str, locator: MessageLocator) -> QuotedMessage:
        thread = await asyncio.to_thread(self.owned, user_id, thread_id)
        cursor = None
        found: list[dict[str, Any]] = []
        # Bound work for a click; never fall back to trusting client-supplied content.
        for _ in range(100):
            page = await self.messages(user_id, thread_id, limit=100, cursor=cursor)
            found = [*page["messages"], *found]
            if not page["has_more"]:
                break
            cursor = page.get("next_cursor")
            if not cursor:
                raise self.error("history_unavailable", user_id, 409)
        else:
            raise self.error("history_too_large", user_id, 409)
        candidates = [
            m
            for m in found
            if m["role"] == locator.role and m.get("content") and not m.get("has_tool_calls")
        ]
        matches = [
            m
            for m in candidates
            if locator.message_id and m.get("message_id") == locator.message_id
        ]
        selected = matches[0] if len(matches) == 1 else None
        if selected is None and locator.content is not None:
            matches = [m for m in candidates if m["content"].strip() == locator.content.strip()]
            if len(matches) == 1:
                selected = matches[0]
        if selected is None:
            raise self.error("message_changed", user_id, 409)
        digest = hashlib.sha256((locator.role + "\0" + selected["content"]).encode()).hexdigest()
        key = selected.get("message_id") or f"content:{digest}"
        return QuotedMessage(
            source_thread_id=thread_id,
            source_agent_id=thread.agent_id,
            message_key=key,
            role=locator.role,
            content=selected["content"][:128000],
            speaker_agent_id=selected.get("speaker_agent_id"),
            speaker_name=selected.get("speaker_name"),
        )

    async def resolve_quote(
        self, user_id: int, target_agent_id: str, reference: QuoteReference
    ) -> QuotedMessage:
        await asyncio.to_thread(self.identity, user_id)
        try:
            await asyncio.to_thread(self.history.require_visible_agent, user_id, target_agent_id)
        except PermissionError:
            raise self.error("agent_not_owned", user_id, 404) from None
        quote = await self.resolve(user_id, reference.source_thread_id, reference.message)
        # Quotations are data inside a user message, never system/tool instructions.
        return quote.model_copy(update={"content": quote.content[:8000]})

    @staticmethod
    def quote_text(quote: QuotedMessage, locale: str = DEFAULT_LOCALE) -> str:
        return (
            tr("conversations.quote_label", locale)
            + "\n"
            + json.dumps(quote.model_dump(), ensure_ascii=False)
            + "\n\n"
        )

    async def imported_context(self, user_id: int, thread_id: str) -> str:
        """Continue an imported transcript as bounded user data, not foreign graph state."""
        await asyncio.to_thread(self.owned, user_id, thread_id)
        origin = await asyncio.to_thread(self.repos.conversation_repo.origin, thread_id)
        if not origin or origin["source"] not in {"grok-history", "octop-transfer"}:
            return ""
        head = await asyncio.to_thread(self.repos.thread_message_repo.head, thread_id)
        rows = await asyncio.to_thread(
            self.repos.thread_message_repo.range_page, thread_id, 0, head, 100
        )
        records = []
        remaining = 30000
        for row in rows:
            wire = json.loads(row.message_json)
            data = wire.get("data", wire)
            if not (data.get("additional_kwargs") or {}).get("octop_imported"):
                continue
            text = data.get("content")
            role = {"human": "user", "ai": "assistant"}.get(wire.get("type"))
            if role not in {"user", "assistant"} or not isinstance(text, str):
                continue
            text = text[-remaining:]
            records.append({"role": role, "content": text})
            remaining -= len(text)
            if remaining <= 0 or len(records) >= 30:
                break
        if not records:
            return ""
        locale = self._locales.get(user_id, DEFAULT_LOCALE)
        return (
            tr("conversations.imported_context_label", locale)
            + "\n"
            + json.dumps(list(reversed(records)), ensure_ascii=False)
            + "\n\n"
        )

    async def annotations(self, user_id: int, thread_id: str) -> dict[str, Any]:
        await asyncio.to_thread(self.owned, user_id, thread_id)
        rows = await asyncio.to_thread(self.repos.conversation_repo.reactions, user_id, thread_id)
        return {"reactions": rows, "allowed": list(REACTIONS)}

    async def react(
        self, user_id: int, thread_id: str, locator: MessageLocator, emoji: str, active: bool
    ) -> dict[str, Any]:
        if emoji not in REACTIONS:
            raise self.error("invalid_reaction", user_id)
        message = await self.resolve(user_id, thread_id, locator)
        digest = hashlib.sha256((message.role + "\0" + message.content).encode()).hexdigest()
        await asyncio.to_thread(
            self.repos.conversation_repo.react,
            reaction_id=new_ulid(),
            user_id=user_id,
            thread_id=thread_id,
            message_key=message.message_key,
            digest=digest,
            role=message.role,
            emoji=emoji,
            active=active,
        )
        return {
            "message_key": message.message_key,
            "reactions": (await self.annotations(user_id, thread_id))["reactions"],
        }

    async def side_question(
        self, user_id: int, thread_id: str, locator: MessageLocator
    ) -> dict[str, Any]:
        source = await asyncio.to_thread(self.owned, user_id, thread_id)
        if locator.role != "assistant":
            raise self.error("assistant_required", user_id)
        selected = await self.resolve(user_id, thread_id, locator)
        agent = await asyncio.to_thread(self.repos.agent_repo.get, source.agent_id)
        if agent is None or not agent.enabled:
            raise self.error("agent_disabled", user_id, 409)
        await self.agents.start(source.agent_id)
        harness = self.agents.get_agent(source.agent_id)
        if harness is None:
            raise self.error("history_unavailable", user_id, 409)
        key = ThreadRegistry.make_key(
            agent_id=source.agent_id,
            channel_type="dashboard",
            channel_subject_id=str(user_id),
            channel_chat_type=f"side-{new_ulid()}",
        )
        result = await fork_dashboard_thread(
            thread_registry=self.gateway.thread_registry,
            harness=harness,
            source=source,
            user_id=user_id,
            message_id=selected.message_key,
            content=selected.content,
            locale=(await asyncio.to_thread(self.identity, user_id)).locale,
            thread_message_repo=self.repos.thread_message_repo,
            history_archive=self.archive,
            independent_session_key=key,
            activate=False,
        )
        target = str(result["thread_id"])
        await asyncio.to_thread(
            self.repos.thread_repo.inherit_project, thread_id, target, user_id=user_id
        )
        await asyncio.to_thread(
            self.repos.thread_repo.update_composer, target, conversation_mode="ask"
        )
        await asyncio.to_thread(
            self.repos.conversation_repo.set_origin,
            origin_id=new_ulid(),
            user_id=user_id,
            thread_id=target,
            source="side-question",
            external_id=selected.message_key,
            source_title=source.title,
            source_thread=thread_id,
        )
        return {**result, "agent_id": source.agent_id, "conversation_mode": "ask"}

    async def _changed(self, user_id: int, row: ThreadRow, action: str) -> None:
        hub = getattr(self.gateway, "ws_hub", None)
        if hub is not None:
            await hub.push_to_user(
                user_id,
                {
                    "type": "conversation.updated",
                    "thread_id": row.thread_id,
                    "agent_id": row.agent_id,
                    "action": action,
                    "notify": False,
                },
            )
