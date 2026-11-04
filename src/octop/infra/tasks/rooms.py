"""Owner-scoped task rooms backed by actual expert turns, never generated chatter."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from typing import Any
from urllib.parse import quote

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    ToolMessage,
    convert_to_messages,
    messages_from_dict,
)

from octop.i18n import tr
from octop.infra.agents.teams.primary import request_user_id
from octop.infra.agents.teams.service import TEAM_KIND, TEAM_TEMPLATE_NAME, is_team_agent
from octop.infra.errors import OctopError
from octop.infra.gateway.process.message_keys import CHECKPOINT_TS_KEY
from octop.infra.history.external import ExternalHistoryBusy, append_external_messages
from octop.infra.tasks.coordinator import scope_signature
from octop.infra.tasks.models import TERMINAL_STATES
from octop.infra.tasks.returns import _pull_request
from octop.infra.tasks.scope import current_coordinator_scope
from octop.infra.users.identity import User
from octop.infra.users.permissions import user_has_permission
from octop.infra.utils.locale import DEFAULT_LOCALE
from octop.infra.utils.ulid import new_ulid

logger = logging.getLogger(__name__)


def room_path(room: dict[str, Any]) -> str:
    return f"/chat/{quote(room['agent_id'], safe='')}/{quote(room['thread_id'], safe='')}"


def discussion_messages(
    messages: list[BaseMessage], *, prefix: str, speaker_id: str, allowed_speakers: set[str]
) -> list[BaseMessage]:
    """Namespace tool ids and retain complete pairs so the room remains model-readable."""
    replies = {item.tool_call_id for item in messages if isinstance(item, ToolMessage)}
    calls = {
        str(call["id"])
        for item in messages
        if isinstance(item, AIMessage)
        and str(item.additional_kwargs.get("speaker_agent_id") or speaker_id) in allowed_speakers
        for call in item.tool_calls
        if call.get("id") in replies
    }

    def call_id(identifier: str) -> str:
        return "task_" + hashlib.sha256(f"{prefix}:{identifier}".encode()).hexdigest()[:40]

    result: list[BaseMessage] = []
    for index, message in enumerate(messages):
        if not isinstance(message, (AIMessage, ToolMessage)):
            continue
        extra = dict(message.additional_kwargs)
        actual = str(extra.get("speaker_agent_id") or speaker_id)
        if actual not in allowed_speakers:
            continue
        extra.update(speaker_agent_id=actual, octop_task_room=True)
        updates: dict[str, Any] = {
            "id": f"{prefix}:{message.id or index}",
            "additional_kwargs": extra,
        }
        if isinstance(message, AIMessage):
            updates["tool_calls"] = [
                {**call, "id": call_id(str(call["id"]))}
                for call in message.tool_calls
                if call.get("id") in calls
            ]
            updates["invalid_tool_calls"] = []
            # Providers may retain a second raw copy with the old call ids.
            extra.pop("tool_calls", None)
            extra.pop("function_call", None)
            if isinstance(message.content, list):
                blocks = []
                for block in message.content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        if block.get("id") not in calls:
                            continue
                        block = {**block, "id": call_id(str(block["id"]))}
                    blocks.append(block)
                updates["content"] = blocks
            if not message.content and not updates["tool_calls"]:
                continue
        else:
            if message.tool_call_id not in calls:
                continue
            updates["tool_call_id"] = call_id(message.tool_call_id)
        result.append(message.model_copy(update=updates))
    return result


class TaskRooms:
    def __init__(self, manager: Any) -> None:
        self.manager = manager
        self.repos = manager._repos
        self.repo = self.repos.task_coordination_repo
        self.agents = manager._agents
        self.gateway = manager._gateway
        self._locks: dict[str, asyncio.Lock] = {}
        self._offset = 0
        self._live: dict[
            tuple[str, int], tuple[float, tuple[dict[str, Any], dict[str, Any]] | None]
        ] = {}
        self._tracked: dict[str, tuple[str, str, str]] = {}
        self._settled: dict[str, tuple[str, str, str]] = {}
        self._peer_jobs: dict[str, list[dict[str, Any]]] = {}

    def close(self) -> None:
        jobs = getattr(getattr(self.agents, "teams", None), "jobs", None)
        if jobs is not None:
            for job_id, (_scope, group, worker) in self._tracked.items():
                jobs.end(group, worker, job_id=job_id)
        self._tracked.clear()
        self._live.clear()
        self._settled.clear()
        if jobs is not None:
            for entries in self._peer_jobs.values():
                for entry in entries:
                    if entry.get("job_id"):
                        jobs.end(entry["group"], entry["member"], job_id=entry["job_id"])
        self._peer_jobs.clear()

    @staticmethod
    def _peer_key(call: Any) -> str:
        values = [
            call.from_agent_id,
            call.to_agent_id,
            str(call.user_id),
            call.source_thread_id,
            call.job_id,
            call.message,
        ]
        return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()

    def has_pending_peers(self, scope_id: str) -> bool:
        return any(
            entry["scope_id"] == scope_id
            for entries in self._peer_jobs.values()
            for entry in entries
        )

    async def register_peer(self, call: Any, thread_id: str) -> None:
        user_id = request_user_id({"configurable": {"user": call.user_id}})
        if user_id is None or not call.source_thread_id:
            return
        parent = await asyncio.to_thread(
            self.manager.bound_task, call.from_agent_id, user_id, call.source_thread_id
        )
        scope = None
        parent_id = parent.task_id if parent is not None else None
        attempt = parent.attempt if parent is not None else None
        if parent is not None:
            dispatch = await asyncio.to_thread(self.repos.task_dispatch_repo.get, parent.task_id)
            if dispatch and dispatch.get("scope_id"):
                scope = await asyncio.to_thread(self.repo.get, dispatch["scope_id"])
        context = current_coordinator_scope()
        if (
            scope is None
            and context is not None
            and context.user_id == user_id
            and context.origin_thread_id == call.source_thread_id
            and context.origin_agent_id == call.from_agent_id
        ):
            scope = await asyncio.to_thread(self.repo.get, context.scope_id)
            parent_id, attempt = context.parent_task_id, context.parent_attempt
        if scope is None:
            scope = await asyncio.to_thread(
                self.repo.scope_for_peer_thread, user_id, call.source_thread_id
            )
            if scope:
                parent_id, attempt = scope.get("execution_task_id"), scope.get("execution_attempt")
        if scope is None:
            scope = await asyncio.to_thread(
                self.repo.scope_for_room, user_id, call.source_thread_id
            )
        if scope is None or scope["state"] in {"idle", "stopped"}:
            return
        owner = await asyncio.to_thread(self._owner, scope)
        caller = await asyncio.to_thread(self.agents.principal_agent_id, call.from_agent_id)
        await asyncio.to_thread(
            self.agents.teams.validate_member_ids, owner, [caller, call.to_agent_id]
        )
        existing = await self.ensure(scope["scope_id"])
        native_room = bool(existing and existing.get("thread_id") == call.source_thread_id)
        from_row = await asyncio.to_thread(self.agents.get_row, call.from_agent_id)
        via_caller = native_room or bool(parent_id and (call.job_id or is_team_agent(from_row)))
        await asyncio.to_thread(
            self.repo.register_peer_source,
            scope["scope_id"],
            thread_id,
            call.to_agent_id,
            caller,
            parent_id,
            attempt,
            via_caller,
        )
        existing = await self.ensure(scope["scope_id"])
        job_id = ""
        if existing and existing.get("agent_id") and not native_room:
            job_id = f"task-peer:{new_ulid()}"
            self.agents.teams.jobs.begin(existing["agent_id"], call.to_agent_id, job_id=job_id)
        self._peer_jobs.setdefault(self._peer_key(call), []).append(
            {
                "scope_id": scope["scope_id"],
                "group": (existing or {}).get("agent_id"),
                "member": call.to_agent_id,
                "job_id": job_id,
                "async": bool(call.job_id),
                "parent_task_id": parent_id,
                "parent_attempt": attempt,
            }
        )
        if parent_id:
            for key in [key for key in self._live if key[0] == parent_id]:
                self._live.pop(key, None)

    async def finish_peer(self, call: Any) -> None:
        key = self._peer_key(call)
        entries = self._peer_jobs.get(key)
        if not entries:
            return
        entry = entries.pop(0)
        if not entries:
            self._peer_jobs.pop(key, None)
        if entry["job_id"]:
            self.agents.teams.jobs.end(entry["group"], entry["member"], job_id=entry["job_id"])
        if entry["async"]:
            await asyncio.to_thread(self.repo.bump_peer_revision, entry["scope_id"])
        self.manager._wake.set()

    async def _member_ids(self, members: list[dict[str, Any]]) -> list[str]:
        ids = []
        for item in members:
            row = await asyncio.to_thread(self.agents.get_row, item["agent_id"])
            if is_team_agent(row):
                ids.extend(await asyncio.to_thread(self.agents.teams.member_ids, row.agent_id))
            else:
                ids.append(item["agent_id"])
        return list(dict.fromkeys(ids))

    def _owner(self, scope: dict[str, Any]) -> User:
        row = self.repos.user_repo.get(scope["user_id"])
        if row is None or row.disabled:
            raise PermissionError("task room owner unavailable")
        user = User(
            id=row.id,
            username=row.username,
            role=row.role,
            display_name=row.display_name,
            locale=row.locale,
            permissions=list(row.permissions),
        )
        if not user_has_permission(user, "tasks"):
            raise PermissionError("task room permission unavailable")
        origin = self.repos.thread_repo.get(scope["origin_thread_id"])
        if (
            origin is None
            or origin.user_id != user.id
            or origin.agent_id != scope["origin_agent_id"]
        ):
            raise PermissionError("task room source unavailable")
        return user

    def _target(self, scope: dict[str, Any], agent_id: str, thread_id: str) -> str:
        self._owner(scope)
        thread = self.repos.thread_repo.get(thread_id)
        row = self.agents.get_row(agent_id)
        principal = self.agents.principal_agent_id(agent_id)
        actual = self.agents.get_row(principal)
        if (
            thread is None
            or thread.agent_id != agent_id
            or thread.user_id != scope["user_id"]
            or row is None
            or row.user_id != scope["user_id"]
            or not row.enabled
            or actual is None
            or actual.user_id != scope["user_id"]
            or not actual.enabled
        ):
            raise PermissionError("task room destination unavailable")
        return str(principal)

    async def public(self, scope: dict[str, Any]) -> dict[str, str] | None:
        room = await asyncio.to_thread(self.repo.room, scope["scope_id"])
        if not room or not room.get("agent_id") or not room.get("thread_id"):
            return None
        try:
            await asyncio.to_thread(self._target, scope, room["agent_id"], room["thread_id"])
        except PermissionError:
            return None
        row = await asyncio.to_thread(self.agents.get_row, room["agent_id"])
        if row is None:
            return None
        return {"agent_id": room["agent_id"], "thread_id": room["thread_id"], "name": row.name}

    async def record_input(
        self,
        user_id: int,
        thread_id: str,
        message_id: str,
        text: str,
        *,
        explicit_dispatch: bool = False,
    ) -> None:
        if not message_id or not text.strip():
            return
        scope = await asyncio.to_thread(self.repo.scope_for_room, user_id, thread_id)
        if scope is None or not await self.manager._room_parent_current(scope):
            return
        if scope["state"] == "idle" and not explicit_dispatch:
            return
        room = await asyncio.to_thread(self.repo.room, scope["scope_id"])
        if not room:
            return
        await asyncio.to_thread(self._target, scope, room["agent_id"], thread_id)
        # Let an admitted review finish. Cancelling its graph would strand a
        # pending tool/approval; the user's real room turn follows it instead.
        job = self.manager._coordinator.jobs.get(scope["scope_id"])
        if job is not None and job is not asyncio.current_task() and not job.done():
            await asyncio.gather(asyncio.shield(job), return_exceptions=True)
        if not await self.manager._room_parent_current(scope):
            return
        approval_paused = await asyncio.to_thread(self.manager._scope_approval_paused, scope)
        changed = await asyncio.to_thread(
            self.repo.record_room_input,
            scope["scope_id"],
            user_id,
            thread_id,
            message_id,
            text.strip()[:32000],
            resume=not approval_paused,
        )
        if changed:
            self.manager._wake.set()

    async def ensure(self, scope_id: str) -> dict[str, Any] | None:
        # Small embeddings can omit team creation; the production registry owns it.
        if not callable(getattr(self.agents, "create", None)):
            return None
        async with self._locks.setdefault(scope_id, asyncio.Lock()):
            scope = await asyncio.to_thread(self.repo.get, scope_id)
            if scope is None or scope["state"] == "stopped":
                existing_room = await asyncio.to_thread(self.repo.room, scope_id)
                return dict(existing_room) if existing_room is not None else None
            owner = await asyncio.to_thread(self._owner, scope)
            members = await asyncio.to_thread(self.repo.members, scope_id)
            sources = await asyncio.to_thread(self.repo.peer_sources, scope_id)
            primary = await asyncio.to_thread(self.agents.teams.require_primary, owner.id)
            task_actors = {item["agent_id"] for item in members}
            members = [*members, *({"agent_id": item["agent_id"]} for item in sources)]
            existing = await asyncio.to_thread(self.repo.room, scope_id)
            if existing is not None:
                if not existing.get("agent_id") or not existing.get("thread_id"):
                    return None  # Respect a user-deleted group/thread.
                await asyncio.to_thread(
                    self._target, scope, existing["agent_id"], existing["thread_id"]
                )
                await self._roster(existing["agent_id"], owner, members)
                return dict(existing)
            origin = await asyncio.to_thread(self.agents.get_row, scope["origin_agent_id"])
            if is_team_agent(origin):
                room = await asyncio.to_thread(
                    self.repo.bind_room, scope_id, origin.agent_id, scope["origin_thread_id"]
                )
                await self._roster(room["agent_id"], owner, members)
                return dict(room)
            for member in members:
                team = await asyncio.to_thread(self.agents.get_row, member["agent_id"])
                if is_team_agent(team) and member.get("thread_id"):
                    room = await asyncio.to_thread(
                        self.repo.bind_room, scope_id, team.agent_id, member["thread_id"]
                    )
                    await self._roster(team.agent_id, owner, members)
                    return dict(room)
            participants = task_actors | {
                item["agent_id"] for item in sources if item["agent_id"] != primary.agent_id
            }
            if len(participants) < 2:
                return None
            teams = self.agents.teams
            ids = await asyncio.to_thread(
                teams.validate_member_ids, owner, await self._member_ids(members)
            )
            suffix = hashlib.sha256(scope_id.encode()).hexdigest()[:20]
            agent_id = f"task-group-{suffix}"
            row = await asyncio.to_thread(self.agents.get_row, agent_id)
            if row is None:
                from octop.infra.agents.manager import AgentCreateSpec

                title = str(scope["goal_text"]).strip().splitlines()[0][:32] or scope_id[:8]
                row = await self.agents.create(
                    AgentCreateSpec(
                        agent_id=agent_id,
                        user_id=owner.id,
                        name=tr(
                            "tasks.rooms.title",
                            owner.locale or DEFAULT_LOCALE,
                            title=title,
                            suffix=suffix[:6],
                        ),
                        description=tr("tasks.rooms.description", owner.locale or DEFAULT_LOCALE),
                        template_name=TEAM_TEMPLATE_NAME,
                        kind=TEAM_KIND,
                        icon_name="users",
                        member_ids=ids,
                        mcp_servers=[],
                        config={"task_coordination_scope": scope_id},
                    )
                )
            elif (
                row.user_id != owner.id
                or not is_team_agent(row)
                or json.loads(row.config_json or "{}").get("task_coordination_scope") != scope_id
            ):
                raise PermissionError("task group identity collision")
            registry = self.gateway.thread_registry
            thread_id = await registry.get_or_create(
                agent_id=row.agent_id,
                user_id=owner.id,
                channel_type="dashboard",
                channel_subject_id=str(owner.id),
                channel_id=self.gateway.dashboard_channel_id,
            )
            await asyncio.to_thread(registry.set_title_if_null, thread_id, row.name)
            from octop.infra.agents.threads.project_runtime import inherit_task_project

            await asyncio.to_thread(
                inherit_task_project,
                self.repos.thread_repo,
                source_id=scope["origin_thread_id"],
                target_id=thread_id,
                user_id=owner.id,
                agent_id=row.agent_id,
            )
            room = await asyncio.to_thread(self.repo.bind_room, scope_id, row.agent_id, thread_id)
            await self._roster(room["agent_id"], owner, members)
            # The real primary performed the delegation; this is a recorded host event.
            locale = owner.locale or DEFAULT_LOCALE
            await self._append(
                scope,
                room["agent_id"],
                room["thread_id"],
                [
                    AIMessage(
                        id=f"task-room:{scope_id}:goal",
                        content=tr(
                            "tasks.rooms.goal", locale, goal=str(scope["goal_text"])[:12000]
                        ),
                        additional_kwargs={
                            "speaker_agent_id": primary.agent_id,
                            "octop_task_room_event": True,
                        },
                    )
                ],
            )
            return dict(room)

    async def _roster(self, agent_id: str, owner: User, members: list[dict[str, Any]]) -> None:
        current = await asyncio.to_thread(self.agents.teams.member_ids, agent_id)
        desired = await asyncio.to_thread(
            self.agents.teams.validate_member_ids,
            owner,
            list(dict.fromkeys([*current, *(await self._member_ids(members))])),
        )
        if desired != current:
            await asyncio.to_thread(self.agents.teams.replace_members, agent_id, desired)

    async def process(self) -> None:
        for key, entries in list(self._peer_jobs.items()):
            kept = []
            for entry in entries:
                scope = await asyncio.to_thread(self.repo.get, entry["scope_id"])
                parent = (
                    await asyncio.to_thread(self.repos.task_repo.get, entry["parent_task_id"])
                    if entry.get("parent_task_id")
                    else None
                )
                current = bool(
                    scope
                    and scope["state"] != "stopped"
                    and (
                        not entry.get("parent_task_id")
                        or (
                            parent
                            and parent.attempt == entry["parent_attempt"]
                            and parent.state not in {"cancelled", "interrupted"}
                        )
                    )
                )
                if current:
                    kept.append(entry)
                elif entry["job_id"]:
                    self.agents.teams.jobs.end(
                        entry["group"], entry["member"], job_id=entry["job_id"]
                    )
            if kept:
                self._peer_jobs[key] = kept
            else:
                self._peer_jobs.pop(key, None)
        for scope_id in {item[0] for item in self._tracked.values()}:
            binding = await asyncio.to_thread(self.repo.room, scope_id)
            if binding and binding.get("agent_id") and binding.get("thread_id"):
                continue
            jobs = getattr(self.agents.teams, "jobs", None)
            for job_id, (tracked_scope, group, worker) in list(self._tracked.items()):
                if tracked_scope == scope_id:
                    if jobs is not None:
                        jobs.end(group, worker, job_id=job_id)
                    self._tracked.pop(job_id, None)
        scopes = await asyncio.to_thread(self.repo.room_candidates, limit=20, offset=self._offset)
        self._offset = self._offset + len(scopes) if len(scopes) == 20 else 0
        for scope in scopes:
            try:
                members = await asyncio.to_thread(self.repo.members, scope["scope_id"])
                peer_heads = []
                for source in await asyncio.to_thread(self.repo.peer_sources, scope["scope_id"]):
                    peer_heads.append(
                        (
                            source["thread_id"],
                            await asyncio.to_thread(
                                self.repos.thread_message_repo.head, source["thread_id"]
                            ),
                        )
                    )
                signature = (
                    scope["state"],
                    str(scope.get("last_signature") or ""),
                    scope_signature(scope, members) + json.dumps(peer_heads),
                )
                if self._settled.get(scope["scope_id"]) == signature:
                    continue
                room = await self.ensure(scope["scope_id"])
                if room:
                    complete = await self._sync(scope, room)
                    if (
                        complete
                        and scope["state"] in {"idle", "stopped"}
                        and all(item["state"] in TERMINAL_STATES for item in members)
                    ):
                        self._settled[scope["scope_id"]] = signature
                elif scope["state"] in {"idle", "stopped"}:
                    self._settled[scope["scope_id"]] = signature
            except (OctopError, PermissionError, ValueError, RuntimeError, OSError):
                logger.warning(
                    "Task group delivery deferred scope=%s", scope["scope_id"], exc_info=True
                )

    async def _sync(self, scope: dict[str, Any], room: dict[str, Any]) -> bool:
        if not room.get("agent_id") or not room.get("thread_id"):
            return False
        complete = True
        primary = await asyncio.to_thread(self.agents.teams.require_primary, scope["user_id"])
        locale = self.manager._locales.get(scope["user_id"], DEFAULT_LOCALE)
        if scope["origin_thread_id"] != room["thread_id"]:
            goal = AIMessage(
                id=f"task-room:{scope['scope_id']}:goal",
                content=tr("tasks.rooms.goal", locale, goal=str(scope["goal_text"])[:12000]),
                additional_kwargs={
                    "speaker_agent_id": primary.agent_id,
                    "octop_task_room_event": True,
                },
            )
            if not await self._append(scope, room["agent_id"], room["thread_id"], [goal]):
                return False
            notice = AIMessage(
                id=f"task-room:{scope['scope_id']}:link",
                content=tr("tasks.rooms.created", locale, url=room_path(room)),
                additional_kwargs={
                    "speaker_agent_id": primary.agent_id,
                    "octop_task_room_event": True,
                },
            )
            complete = (
                await self._append(
                    scope, scope["origin_agent_id"], scope["origin_thread_id"], [notice]
                )
                and complete
            )
        members = await asyncio.to_thread(self.repo.members, scope["scope_id"])
        jobs = getattr(self.agents.teams, "jobs", None)
        active_jobs = set()
        if jobs is not None:
            for member in members:
                job_id = f"task-room:{member['task_id']}:{member['attempt']}"
                if member["state"] in {"running", "waiting"}:
                    jobs.begin(room["agent_id"], member["agent_id"], job_id=job_id)
                    self._tracked[job_id] = (
                        scope["scope_id"],
                        room["agent_id"],
                        member["agent_id"],
                    )
                    active_jobs.add(job_id)
            for job_id, (tracked_scope, group, tracked_worker) in list(self._tracked.items()):
                if tracked_scope == scope["scope_id"] and job_id not in active_jobs:
                    jobs.end(group, tracked_worker, job_id=job_id)
                    self._tracked.pop(job_id, None)
        allowed = set(await asyncio.to_thread(self.agents.teams.member_ids, room["agent_id"]))
        for item in members:
            worker = await asyncio.to_thread(self.agents.get_row, item["agent_id"])
            if worker is None or worker.user_id != scope["user_id"]:
                continue
            executor_id = await asyncio.to_thread(self.agents.principal_agent_id, worker.agent_id)
            executor = await asyncio.to_thread(self.agents.get_row, executor_id)
            if executor is None:
                continue
            actual_task = await asyncio.to_thread(self.repos.task_repo.get, item["task_id"])
            if actual_task is None:
                continue
            assignment = AIMessage(
                id=f"task-room:{item['task_id']}:assignment",
                content=tr(
                    "tasks.rooms.assignment",
                    locale,
                    name=worker.name,
                    title=item["title"],
                    prompt=str(actual_task.prompt)[:6000],
                ),
                additional_kwargs={
                    "speaker_agent_id": primary.agent_id,
                    "octop_task_room_event": True,
                },
            )
            if not await self._append(scope, room["agent_id"], room["thread_id"], [assignment]):
                return False
            if item.get("thread_id") and item["state"] not in {"running", "queued", "paused"}:
                copied = await self._copy(
                    scope,
                    room,
                    item["thread_id"],
                    executor.agent_id,
                    allowed,
                    primary_only=False,
                    allow_incomplete=item["state"] != "waiting",
                )
                complete = complete and copied
            if item["state"] in TERMINAL_STATES or item["state"] == "waiting":
                stage = AIMessage(
                    id=f"task-room:{item['task_id']}:event:{item['event_id']}",
                    content=tr(
                        "tasks.rooms.stage",
                        locale,
                        name=worker.name,
                        status=tr(
                            f"tasks.returns.{item['state']}",
                            locale,
                            name=executor.name,
                            title=item["title"],
                        ),
                        url=(
                            f"/chat/{quote(worker.agent_id, safe='')}/{quote(item['thread_id'], safe='')}"
                            if item.get("thread_id")
                            else "/task-queue"
                        ),
                    ),
                    additional_kwargs={
                        "speaker_agent_id": executor.agent_id,
                        "octop_task_room_event": True,
                    },
                )
                if item.get("coding_spec"):
                    stage.content = (
                        str(stage.content)
                        + "\n\n"
                        + tr("tasks.returns.task_link", locale, url="/task-queue")
                    )
                    run = item.get("coding_run") or {}
                    verification = run.get("verification") or []
                    if verification:
                        stage.content += "\n" + tr(
                            "tasks.rooms.verification",
                            locale,
                            passed=sum(record.get("passed") is True for record in verification),
                            total=len(verification),
                        )
                    pr = _pull_request(run.get("pr_url"))
                    if pr:
                        stage.content += "\n" + tr(
                            "tasks.returns.pull_request_link", locale, url=pr
                        )
                complete = (
                    await self._append(scope, room["agent_id"], room["thread_id"], [stage])
                    and complete
                )
        if scope["state"] != "stopped":
            for source in await asyncio.to_thread(self.repo.peer_sources, scope["scope_id"]):
                if source["via_caller"]:
                    continue
                parent = (
                    await asyncio.to_thread(self.repos.task_repo.get, source["parent_task_id"])
                    if source.get("parent_task_id")
                    else None
                )
                if source.get("parent_task_id") and (
                    parent is None
                    or parent.attempt != source.get("parent_attempt")
                    or parent.state in {"cancelled", "interrupted"}
                ):
                    continue
                copied = await self._copy(
                    scope,
                    room,
                    source["thread_id"],
                    source["agent_id"],
                    allowed,
                    primary_only=False,
                    allow_incomplete=False,
                    consultation=source,
                )
                complete = copied and complete
        if scope["state"] != "running" and scope["origin_thread_id"] != room["thread_id"]:
            copied = await self._copy(
                scope,
                room,
                scope["origin_thread_id"],
                primary.agent_id,
                allowed,
                primary_only=True,
                allow_incomplete=scope["state"] in {"idle", "stopped"},
            )
            complete = complete and copied
        text = ""
        if scope["state"] == "idle" and scope.get("decision") == "ready" and scope.get("summary"):
            text = tr("tasks.rooms.review", locale, summary=scope["summary"])
        elif scope["state"] == "needs_user" and scope.get("question"):
            text = tr("tasks.rooms.attention", locale, question=scope["question"])
        elif scope["state"] == "stopped":
            text = tr("tasks.rooms.stopped", locale)
        if text:
            event = hashlib.sha256(
                json.dumps(
                    [
                        scope["state"],
                        scope.get("last_signature"),
                        scope.get("summary"),
                        scope.get("question"),
                        scope.get("resume_seq", 0),
                    ]
                ).encode()
            ).hexdigest()
            status = AIMessage(
                id=f"task-room:{scope['scope_id']}:review:{event}",
                content=text,
                additional_kwargs={
                    "speaker_agent_id": primary.agent_id,
                    "octop_task_room_event": True,
                },
            )
            complete = (
                await self._append(scope, room["agent_id"], room["thread_id"], [status])
                and complete
            )
            if scope["origin_thread_id"] != room["thread_id"]:
                original_status = status.model_copy(
                    update={
                        "content": text
                        + "\n\n"
                        + tr("tasks.rooms.link", locale, url=room_path(room))
                    }
                )
                complete = (
                    await self._append(
                        scope,
                        scope["origin_agent_id"],
                        scope["origin_thread_id"],
                        [original_status],
                    )
                    and complete
                )
        return complete

    async def _copy(
        self,
        scope: dict[str, Any],
        room: dict[str, Any],
        source: str,
        speaker: str,
        allowed: set[str],
        *,
        primary_only: bool,
        allow_incomplete: bool,
        consultation: dict[str, Any] | None = None,
    ) -> bool:
        row = await asyncio.to_thread(self.repos.thread_repo.get, source)
        if row is None or row.user_id != scope["user_id"] or source == room["thread_id"]:
            return True
        kind, rows, more = await self._source_rows(scope, row)
        if not rows:
            return True
        decoded = [item for _seq, item in rows]
        if consultation is not None:
            caller = await asyncio.to_thread(self.agents.get_row, consultation["caller_id"])
            callee = await asyncio.to_thread(self.agents.get_row, consultation["agent_id"])
            if caller is None or callee is None:
                return True
            locale = self.manager._locales.get(scope["user_id"], DEFAULT_LOCALE)
            replacements = {}
            for item in decoded:
                if isinstance(item, HumanMessage):
                    question = str(
                        item.additional_kwargs.get("octop_peer_question") or item.content
                    )
                    replacements[str(item.id)] = AIMessage(
                        id=str(item.id),
                        content=tr(
                            "tasks.rooms.consultation",
                            locale,
                            caller=caller.name,
                            name=callee.name,
                            question=question[:6000],
                            url=f"/chat/{quote(callee.agent_id, safe='')}/{quote(source, safe='')}",
                        ),
                        additional_kwargs={
                            **item.additional_kwargs,
                            "speaker_agent_id": caller.agent_id,
                            "octop_task_room_event": True,
                        },
                    )
            decoded = [replacements.get(str(item.id), item) for item in decoded]
        if primary_only:
            selected: list[BaseMessage] = []
            active_calls: set[str] = set()
            for item in decoded:
                tagged = item.additional_kwargs.get("octop_task_scope_id") == scope["scope_id"]
                if isinstance(item, AIMessage):
                    active_calls = (
                        {str(call["id"]) for call in item.tool_calls} if tagged else set()
                    )
                    if tagged:
                        selected.append(item)
                elif isinstance(item, ToolMessage) and (
                    tagged or item.tool_call_id in active_calls
                ):
                    selected.append(item)
                    active_calls.discard(item.tool_call_id)
                else:
                    active_calls.clear()
            decoded = selected
        # Keep an unfinished tool group for a later completed checkpoint.
        replies = {item.tool_call_id for item in decoded if isinstance(item, ToolMessage)}
        unfinished = next(
            (
                item
                for item in decoded
                if isinstance(item, AIMessage)
                and any(call.get("id") not in replies for call in item.tool_calls)
            ),
            None,
        )
        if unfinished is not None and (more or not allow_incomplete):
            boundary = next(
                index for index, (_seq, item) in enumerate(rows) if item.id == unfinished.id
            )
            rows = rows[:boundary]
            if not rows:
                return True
            cutoff = {item.id for _seq, item in rows}
            decoded = [item for item in decoded if item.id in cutoff]
        messages = discussion_messages(
            decoded,
            prefix=f"task-room:{scope['scope_id']}:{source}",
            speaker_id=speaker,
            allowed_speakers=allowed,
        )
        if messages and not await self._append(
            scope, room["agent_id"], room["thread_id"], messages
        ):
            return False
        await asyncio.to_thread(
            self.repo.advance_room_cursor,
            scope["scope_id"],
            source,
            rows[-1][0],
            kind,
            str(rows[-1][1].id or ""),
        )
        if not primary_only and not more and allow_incomplete:
            teams = getattr(getattr(self.gateway, "processor", None), "teams", None)
            finish = getattr(teams, "finish_task_wall", None)
            if callable(finish):
                await finish(room["thread_id"], speaker)
        return not more

    async def _source_rows(
        self, scope: dict[str, Any], source: Any
    ) -> tuple[str, list[tuple[int, BaseMessage]], bool]:
        position = await asyncio.to_thread(
            self.repo.room_position, scope["scope_id"], source.thread_id
        )
        projection = self.repos.thread_message_repo
        status = await asyncio.to_thread(projection.projection_status, source.thread_id)
        archive = getattr(self.agents, "history_archive", None)
        segments = (
            await asyncio.to_thread(archive.store.segments, source.thread_id)
            if archive is not None
            else []
        )
        kind = "projection" if status == "ready" else ("archive" if segments else "checkpoint")
        start = int(position["last_seq"]) if position["source_kind"] == kind else 0
        rows: list[tuple[int, BaseMessage]] = []
        if kind == "projection":
            head = await asyncio.to_thread(projection.head, source.thread_id)
            raw = await asyncio.to_thread(
                projection.range_rows, source.thread_id, start, min(head, start + 200)
            )
            rows = [
                (item.seq, messages_from_dict([json.loads(item.message_json)])[0]) for item in raw
            ]
            more = bool(raw and raw[-1].seq < head)
        elif kind == "archive":
            assert archive is not None
            raw_docs = await asyncio.to_thread(
                archive.store.messages_after, source.thread_id, start, 201
            )
            rows = [
                (item["seq"], messages_from_dict([item["value"]])[0]) for item in raw_docs[:200]
            ]
            more = len(raw_docs) > 200
        else:
            principal = await asyncio.to_thread(self.agents.principal_agent_id, source.agent_id)
            state = await self.agents.get_agent(principal).graph.aget_state(
                {"configurable": {"thread_id": source.thread_id}}
            )
            raw_messages = list((getattr(state, "values", {}) or {}).get("messages") or [])

            def decode(item: Any) -> BaseMessage:
                if isinstance(item, BaseMessage):
                    return item
                return (
                    messages_from_dict([item])[0]
                    if isinstance(item, dict) and "data" in item
                    else convert_to_messages([item])[0]
                )

            if start > len(raw_messages) or (
                start
                and position["last_id"]
                and str(decode(raw_messages[start - 1]).id or "") != position["last_id"]
            ):
                start = 0
            rows = [
                (index + 1, decode(raw_messages[index]))
                for index in range(start, min(len(raw_messages), start + 200))
            ]
            more = start + 200 < len(raw_messages)
        rows = [
            (seq, item if item.id else item.model_copy(update={"id": f"source-row:{kind}:{seq}"}))
            for seq, item in rows
        ]
        return kind, rows, more

    async def _append(
        self, scope: dict[str, Any], agent_id: str, thread_id: str, messages: list[BaseMessage]
    ) -> bool:
        messages = [
            message
            if message.additional_kwargs.get(CHECKPOINT_TS_KEY)
            else message.model_copy(
                update={
                    "additional_kwargs": {
                        **message.additional_kwargs,
                        CHECKPOINT_TS_KEY: int(time.time() * 1000),
                    }
                }
            )
            for message in messages
        ]
        started = asyncio.Event()
        admission_open = True
        outcome = False

        async def operation() -> None:
            nonlocal outcome
            if admission_open:
                started.set()
                outcome = await self._append_locked(scope, agent_id, thread_id, messages)

        channels = self.gateway.channel_manager
        if channels is None:
            return False
        job = asyncio.create_task(
            channels.run_in_session(
                self.gateway.dashboard_channel_id, f"thread:{thread_id}", operation
            )
        )
        waiting = asyncio.create_task(started.wait())
        try:
            await asyncio.wait({job, waiting}, timeout=0.1, return_when=asyncio.FIRST_COMPLETED)
            if job.done():
                job.result()
                return outcome
            if started.is_set():
                await asyncio.shield(job)
                return outcome
            admission_open = False
            job.cancel()
            await asyncio.gather(job, return_exceptions=True)
            return False
        except asyncio.CancelledError:
            admission_open = False
            if started.is_set():
                await asyncio.shield(job)
            else:
                job.cancel()
                await asyncio.gather(job, return_exceptions=True)
            raise
        finally:
            waiting.cancel()
            await asyncio.gather(waiting, return_exceptions=True)

    async def _append_locked(
        self, scope: dict[str, Any], agent_id: str, thread_id: str, messages: list[BaseMessage]
    ) -> bool:
        if not messages:
            return True
        try:
            principal = await asyncio.to_thread(self._target, scope, agent_id, thread_id)
        except PermissionError:
            return False
        known = await asyncio.to_thread(
            self.repos.thread_message_repo.message_roles,
            thread_id,
            [str(item.id) for item in messages],
        )
        if all(known.get(str(item.id)) == item.type for item in messages):
            return True
        if self.gateway.ws_hub.is_turn_active(thread_id) or self.gateway.steer.is_hitl_paused(
            thread_id
        ):
            return False
        if not self.agents.try_begin_history_backfill(principal):
            return False
        try:

            async def authorize() -> None:
                if await asyncio.to_thread(self._target, scope, agent_id, thread_id) != principal:
                    raise PermissionError("task room principal changed")
                if self.gateway.ws_hub.is_turn_active(
                    thread_id
                ) or self.gateway.steer.is_hitl_paused(thread_id):
                    raise ExternalHistoryBusy("task room is occupied")

            await append_external_messages(
                archive=getattr(self.agents, "history_archive", None),
                harness=self.agents.get_agent(principal),
                agent_id=agent_id,
                thread_id=thread_id,
                messages=messages,
                projection=self.repos.thread_message_repo,
                before_write=authorize,
            )
            sessions = await asyncio.to_thread(
                self.gateway.thread_registry.sessions_for_thread, thread_id
            )
            for session in sessions:
                if session.user_id == scope["user_id"] and session.agent_id == agent_id:
                    await self.gateway.notify_dashboard_push(
                        session, agent_id, "", notify=False, toast=False
                    )
            return True
        except (ExternalHistoryBusy, PermissionError, ValueError, RuntimeError, OSError):
            return False
        finally:
            self.agents.end_history_backfill(principal)

    async def relay(self, row: Any, chunk: dict[str, Any]) -> None:
        if chunk.get("type") not in {
            "token",
            "thinking",
            "tool_start",
            "tool_end",
            "done",
            "turn.ended",
        }:
            return
        key = (row.task_id, row.attempt)
        cached = self._live.get(key)
        if cached is not None and cached[0] > time.monotonic():
            if cached[1] is None:
                return
            scope, room = cached[1]
            await self._relay_bound(row, chunk, scope, room)
            return
        self._live[key] = (time.monotonic() + 1, None)
        context = await asyncio.to_thread(self.repos.task_dispatch_repo.get, row.task_id)
        scope_id = (context or {}).get("scope_id")
        if not scope_id:
            return
        room = await asyncio.to_thread(self.repo.room, scope_id)
        if not room or not room.get("thread_id") or room["thread_id"] == row.thread_id:
            return
        scope = await asyncio.to_thread(self.repo.get, scope_id)
        if scope is None:
            return
        try:
            await asyncio.to_thread(self._target, scope, room["agent_id"], room["thread_id"])
            current = await asyncio.to_thread(self.repos.task_repo.get, row.task_id)
            if current is None or current.attempt != row.attempt or current.state != "running":
                return
            if current.thread_id == room["thread_id"]:
                return
            live_room = {
                **room,
                "allowed_speakers": set(
                    await asyncio.to_thread(self.agents.teams.member_ids, room["agent_id"])
                ),
                "fallback_speaker": await asyncio.to_thread(
                    self.agents.principal_agent_id, row.agent_id
                ),
            }
            self._live[key] = (time.monotonic() + 1, (scope, live_room))
            await self._relay_bound(row, chunk, scope, live_room)
        except (PermissionError, ValueError, RuntimeError):
            return

    async def _relay_bound(
        self, row: Any, chunk: dict[str, Any], scope: dict[str, Any], room: dict[str, Any]
    ) -> None:
        teams = getattr(getattr(self.gateway, "processor", None), "teams", None)
        relay = getattr(teams, "relay_task_chunk", None)
        if callable(relay):
            candidate = str(chunk.get("speaker_agent_id") or chunk.get("agent_id") or "")
            speaker_id = (
                candidate
                if candidate in room.get("allowed_speakers", set())
                else room.get("fallback_speaker", row.agent_id)
            )
            await relay(chunk, room_thread_id=room["thread_id"], speaker_id=speaker_id)
        if chunk.get("type") in {"done", "turn.ended"}:
            self._live.pop((row.task_id, row.attempt), None)
