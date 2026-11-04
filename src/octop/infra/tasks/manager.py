"""Durable FIFO orchestration, with normal Octop history and approval semantics."""

from __future__ import annotations

import asyncio
import builtins
import contextlib
import hashlib
import hmac
import json
import logging
import secrets
import time
from collections import defaultdict, deque
from typing import Any

from octop_gateway.models import ChannelSubject, InboundMessage, TextContent

from octop.config import OctopConfig
from octop.i18n import tr
from octop.infra.db.repos._base import now_ts
from octop.infra.db.repos.tasks import TaskRow, WorkflowRow
from octop.infra.db.repos.users import UserRow
from octop.infra.db.services import RepoBundle
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.gateway.media.attachment_hints import inbound_attachments_from_parts
from octop.infra.gateway.process.message_keys import INBOUND_ATTACHMENTS_KEY
from octop.infra.tasks.attachments import (
    TaskAttachmentError,
    authorize_uploads,
    content_parts,
    validate_references,
)
from octop.infra.tasks.models import (
    TERMINAL_STATES,
    TaskAttachment,
    TaskCreate,
    TaskOptions,
    WorkflowDefinition,
)
from octop.infra.tasks.resume import TaskResumeLease
from octop.infra.tasks.retry import reset_for_retry
from octop.infra.tasks.scheduling import calendar_document, next_occurrence
from octop.infra.tasks.team_completion import (
    background_completion,
    cancel_scoped_jobs,
    close_background,
)
from octop.infra.users.identity import User
from octop.infra.users.permissions import user_has_permission
from octop.infra.utils.locale import DEFAULT_LOCALE
from octop.infra.utils.ulid import new_ulid

logger = logging.getLogger(__name__)


def _identity(row: UserRow) -> User:
    return User(
        id=row.id,
        username=row.username,
        role=row.role,
        display_name=row.display_name,
        locale=row.locale,
        permissions=list(row.permissions),
    )


class TaskManager:
    """One manager per Octop process, matching the repository's single-host model.

    A task is claimed before execution. A host crash never replays a task that
    may already have used an external tool; those become ``interrupted`` and
    require an explicit retry. Pending tasks remain in SQLite/PostgreSQL.
    """

    def __init__(
        self, *, repos: RepoBundle, gateway: Any, agent_manager: Any, config: OctopConfig
    ) -> None:
        self._timezone = config.default_timezone
        self._repos = repos
        self._repo = repos.task_repo
        self._gateway = gateway
        self._agents = agent_manager
        self._loop: asyncio.Task[None] | None = None
        self._running: dict[str, asyncio.Task[None]] = {}
        self._finalizers: set[asyncio.Task[None]] = set()
        self._continuations: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._wake = asyncio.Event()
        self._locales: dict[int, str] = {}
        self._mutation_locks: dict[str, asyncio.Lock] = {}
        self._resume_leases: dict[str, set[TaskResumeLease]] = {}
        self._bindings: dict[tuple[str, int, str], tuple[str, int]] = {}
        self._hook_calls: dict[str, deque[float]] = defaultdict(deque)
        self._coding_service: Any = None
        self._return_service: Any = None
        self._return_locks: dict[str, asyncio.Lock] = {}
        self._delegated_waiters: set[str] = set()
        self._settled_children: dict[tuple[str, int], set[str]] = {}
        self._verification_tasks: dict[tuple[str, int], asyncio.Task[Any]] = {}
        self._return_offset = 0
        from octop.infra.tasks.coordinator import TaskCoordinator

        self._coordinator = TaskCoordinator(self)
        from octop.infra.tasks.rooms import TaskRooms

        self._rooms = TaskRooms(self)

    def _error(self, key: str, *, user_id: int | None = None, status: int = 400) -> OctopError:
        locale = self._locales.get(user_id or 0, DEFAULT_LOCALE)
        return OctopError(
            ErrorCode.SLASH_BAD_ARGS,
            tr(f"tasks.errors.{key}", locale),
            status=status,
            details={"task_reason": key},
        )

    def _owned_agent(self, agent_id: str, user_id: int) -> Any:
        agent = self._repos.agent_repo.get(agent_id)
        if agent is None or agent.user_id != user_id:
            raise self._error("agent_not_owned", user_id=user_id, status=404)
        return agent

    def _owned_task(self, task_id: str, user_id: int) -> TaskRow:
        task = self._repo.get(task_id)
        if task is None or task.user_id != user_id:
            raise self._error("not_found", user_id=user_id, status=404)
        return task

    def _owned_workflow(self, workflow_id: str, user_id: int) -> WorkflowRow:
        row = self._repo.workflow(workflow_id)
        if row is None or row.user_id != user_id:
            raise self._error("not_found", user_id=user_id, status=404)
        return row

    async def start(self) -> None:
        if self._loop:
            return
        recovered = await asyncio.to_thread(self._repo.recover)
        await self._coordinator.start()
        for task_id in recovered:
            task = await asyncio.to_thread(self._repo.get, task_id)
            if task and task.run_id:
                await self._apply_failure_policy(task.run_id)
        active = await asyncio.to_thread(self._repo.runtime_rows)
        self._bindings = {
            (row.agent_id, row.user_id, row.thread_id or ""): (row.task_id, row.attempt)
            for row in active
            if row.state != "completed"
        }
        self._loop = asyncio.create_task(self._serve(), name="octop-task-queue")

    async def stop(self) -> None:
        await self._coordinator.stop()
        self._rooms.close()
        for leases in list(self._resume_leases.values()):
            for lease in list(leases):
                lease.cancel()
        if self._loop:
            self._loop.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._loop
            self._loop = None
        for completion in list(self._continuations.values()):
            completion.cancel()
        tasks = list(self._running.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._running.clear()
        finalizers = list(self._finalizers)
        for task in finalizers:
            task.cancel()
        if finalizers:
            await asyncio.gather(*finalizers, return_exceptions=True)
        self._finalizers.clear()
        self._continuations.clear()
        self._delegated_waiters.clear()
        self._settled_children.clear()

    def replace_repos(self, repos: RepoBundle) -> None:
        if self._running or self._finalizers or self._coordinator.jobs:
            raise RuntimeError("stop task manager before rebinding persistence")
        self._rooms.close()
        self._repos = repos
        self._repo = repos.task_repo
        self._return_service = None
        self._delegated_waiters.clear()
        self._settled_children.clear()
        self._return_offset = 0
        from octop.infra.tasks.coordinator import TaskCoordinator

        self._coordinator = TaskCoordinator(self)
        from octop.infra.tasks.rooms import TaskRooms

        self._rooms = TaskRooms(self)

    async def enqueue(
        self,
        user_id: int,
        body: TaskCreate,
        *,
        request_key: str | None = None,
        coordination: dict[str, Any] | None = None,
    ) -> TaskRow:
        await asyncio.to_thread(self._validate_task, user_id, body)
        if coordination is not None:
            from octop.infra.tasks.scope import current_coordinator_scope

            if current_coordinator_scope() is None and body.origin_thread_id:
                bound_scope = await asyncio.to_thread(
                    self._repos.task_coordination_repo.scope_for_room,
                    user_id,
                    body.origin_thread_id,
                )
                if bound_scope and await self._room_parent_current(bound_scope):
                    if await asyncio.to_thread(self._scope_approval_paused, bound_scope):
                        raise self._error("coordination_source_busy", user_id=user_id, status=409)
                    if (
                        body.coding
                        and body.coding.publish_pr
                        and not bound_scope.get("allow_publish")
                    ):
                        raise self._error("coordination_publish", user_id=user_id, status=403)
                    room_thread_id = body.origin_thread_id
                    room_thread = await asyncio.to_thread(
                        self._origin_thread, user_id, room_thread_id
                    )
                    if (room_thread.agent_id, user_id, room_thread_id) not in self._bindings:
                        await self._rooms.record_input(
                            user_id,
                            room_thread_id,
                            str(coordination.get("source_message_id") or ""),
                            str(coordination.get("goal_text") or ""),
                            explicit_dispatch=True,
                        )
                        body = body.model_copy(
                            update={"origin_thread_id": bound_scope["origin_thread_id"]}
                        )
                    coordination = None
                else:
                    bound_scope = None
            else:
                bound_scope = None
        else:
            bound_scope = None
        if body.thread_id:
            previous = await asyncio.to_thread(
                self._repo.latest_in_thread, body.agent_id, user_id, body.thread_id
            )
            if (
                previous
                and previous.attempt > 0
                and previous.state in {"failed", "cancelled", "interrupted"}
            ):
                raise self._error("recovery_requires_retry", user_id=user_id, status=409)
        options = body.options.model_copy(deep=True)
        options.attachments = await self._prepare_attachments(
            user_id, body.agent_id, [*body.attachments, *options.attachments]
        )
        task_id = new_ulid()
        origin = await asyncio.to_thread(self._origin_thread, user_id, body.origin_thread_id)
        parent = await asyncio.to_thread(self._dispatch_parent, user_id, origin, body.agent_id)
        if parent is not None and request_key:
            from octop.infra.tasks.scope import current_coordinator_scope

            if current_coordinator_scope() is None:
                parent_context = await asyncio.to_thread(
                    self._repos.task_dispatch_repo.get, parent.task_id
                )
                inherited = (
                    await asyncio.to_thread(
                        self._repos.task_coordination_repo.get, parent_context["scope_id"]
                    )
                    if parent_context and parent_context.get("scope_id")
                    else None
                )
                if inherited is not None:
                    if inherited["user_id"] != user_id or inherited["state"] == "stopped":
                        raise self._error("dispatch_context", user_id=user_id, status=409)
                    if (
                        body.coding
                        and body.coding.publish_pr
                        and not inherited.get("allow_publish")
                    ):
                        raise self._error("coordination_publish", user_id=user_id, status=403)
                    bound_scope, coordination = inherited, None
        if request_key and parent:
            request_key = hashlib.sha256(
                json.dumps([request_key, parent.task_id, parent.attempt]).encode()
            ).hexdigest()
        dispatch = None
        if origin is not None or body.coding is not None:
            dispatch = {
                "origin_agent_id": origin.agent_id if origin else None,
                "origin_thread_id": origin.thread_id if origin else None,
                "request_key": request_key,
                "coding_spec": body.coding.model_dump() if body.coding else None,
                "parent_task_id": parent.task_id if parent else None,
                "parent_attempt": parent.attempt if parent else None,
            }
        if coordination is not None:
            if origin is None or dispatch is None:
                raise self._error("dispatch_context", user_id=user_id)
            from octop.infra.tasks.scope import current_coordinator_scope

            active_scope = current_coordinator_scope()
            if active_scope is not None:
                scope = await asyncio.to_thread(
                    self._repos.task_coordination_repo.get, active_scope.scope_id
                )
                if (
                    scope is None
                    or scope["state"] != "running"
                    or scope["user_id"] != user_id
                    or scope["origin_thread_id"] != origin.thread_id
                    or scope.get("active_signature") != active_scope.active_signature
                ):
                    raise self._error("dispatch_context", user_id=user_id, status=409)
                if body.coding and body.coding.publish_pr and not scope.get("allow_publish"):
                    raise self._error("coordination_publish", user_id=user_id, status=403)
            else:
                if parent:
                    coordination = {
                        **coordination,
                        "scope_id": hashlib.sha256(
                            json.dumps(
                                [coordination["scope_id"], parent.task_id, parent.attempt]
                            ).encode()
                        ).hexdigest(),
                    }
                scope = await asyncio.to_thread(
                    self._repos.task_coordination_repo.ensure,
                    {
                        **coordination,
                        "user_id": user_id,
                        "origin_agent_id": origin.agent_id,
                        "origin_thread_id": origin.thread_id,
                        "parent_task_id": parent.task_id if parent else None,
                        "parent_attempt": parent.attempt if parent else None,
                        "allow_publish": bool(body.coding and body.coding.publish_pr),
                    },
                )
            dispatch["scope_id"] = scope["scope_id"]
        elif bound_scope is not None and dispatch is not None:
            dispatch["scope_id"] = bound_scope["scope_id"]
            dispatch["origin_agent_id"] = bound_scope["origin_agent_id"]
            dispatch["origin_thread_id"] = bound_scope["origin_thread_id"]
        from octop.infra.tasks.admission import enqueue_dispatch

        existing = await enqueue_dispatch(
            self,
            {
                "task_id": task_id,
                "user_id": user_id,
                "agent_id": body.agent_id,
                "thread_id": body.thread_id,
                "title": body.title,
                "prompt": body.prompt,
                "options": options.model_dump(exclude_none=True),
                "dispatch": dispatch,
            },
            parent,
        )
        task_id = existing or task_id
        self._wake.set()
        row = await asyncio.to_thread(self._owned_task, task_id, user_id)
        if dispatch and dispatch.get("scope_id"):
            try:
                await self._rooms.ensure(str(dispatch["scope_id"]))
            except (OctopError, PermissionError, ValueError, RuntimeError, OSError):
                logger.warning("Task group creation deferred task=%s", task_id, exc_info=True)
        await self._publish(row, notify=False)
        return row

    async def _room_parent_current(self, scope: dict[str, Any]) -> bool:
        if not scope.get("parent_task_id"):
            return True
        parent = await asyncio.to_thread(self._repo.get, scope["parent_task_id"])
        return bool(
            parent
            and parent.attempt == scope.get("parent_attempt")
            and parent.state in {"running", "waiting"}
        )

    def _scope_approval_paused(self, scope: dict[str, Any]) -> bool:
        thread_id = scope["origin_thread_id"]
        if self._gateway.steer.is_hitl_paused(thread_id):
            return True
        pending = getattr(getattr(self._gateway.processor, "hitl_coordinator", None), "store", None)
        if pending is None:
            return False
        for agent_id in {
            scope["origin_agent_id"],
            self._agents.principal_agent_id(scope["origin_agent_id"]),
        }:
            if thread_id in pending.pending_thread_ids(agent_id=agent_id, user_id=scope["user_id"]):
                return True
        return False

    async def record_room_input(
        self, message: InboundMessage, *, user_id: int, thread_id: str
    ) -> None:
        from octop.infra.tasks.scope import current_coordinator_scope

        meta = message.metadata or {}
        if (
            current_coordinator_scope() is not None
            or meta.get("task_id")
            or meta.get("conversation_mode") in {"ask", "plan"}
        ):
            return
        if message.channel_type != "dashboard" or not message.text.strip():
            return
        identifier = str(meta.get("client_message_id") or "")
        if identifier:
            thread = await asyncio.to_thread(self._repos.thread_repo.get, thread_id)
            if thread is None or thread.user_id != user_id or thread.agent_id != message.tenant_id:
                return
            await self._rooms.record_input(user_id, thread_id, identifier, message.text)

    def _validate_task(self, user_id: int, body: TaskCreate) -> None:
        self._validate_task_policy(user_id, body.agent_id, body.thread_id, body.options)
        self._origin_thread(user_id, body.origin_thread_id)
        if body.coding is not None:
            self._validate_coding(user_id, body.coding)

    def _origin_thread(self, user_id: int, thread_id: str | None) -> Any:
        if not thread_id:
            return None
        thread = self._repos.thread_repo.get(thread_id)
        if thread is None or thread.user_id != user_id:
            raise self._error("thread_not_owned", user_id=user_id, status=404)
        self._owned_agent(thread.agent_id, user_id)
        return thread

    def _dispatch_parent(self, user_id: int, origin: Any, target_id: str) -> TaskRow | None:
        if origin is None:
            return None
        binding = self._bindings.get((origin.agent_id, user_id, origin.thread_id))
        if binding is None:
            return None
        parent = self._owned_task(binding[0], user_id)
        if parent.attempt != binding[1] or parent.state not in {"running", "waiting"}:
            raise self._error("invalid_transition", user_id=user_id, status=409)
        self._assert_dispatch_target(user_id, parent, target_id)
        return parent

    def _assert_dispatch_target(self, user_id: int, parent: TaskRow, target_id: str) -> None:
        ancestor: TaskRow | None = parent
        visited: set[str] = set()
        while ancestor is not None:
            if ancestor.agent_id == target_id or ancestor.task_id in visited:
                raise self._error("dispatch_cycle", user_id=user_id, status=409)
            visited.add(ancestor.task_id)
            context = self._repos.task_dispatch_repo.get(ancestor.task_id)
            previous = (context or {}).get("parent_task_id")
            ancestor = self._owned_task(previous, user_id) if previous else None

    def _validate_coding(self, user_id: int, spec: Any) -> None:
        from octop.infra.agents.threads.project_runtime import normalize_project_path
        from octop.infra.users.resource_policy import (
            POLICY_WORKSPACE_ROOT_DIR,
            effective_workspace_root_dir,
        )

        user = self._repos.user_repo.get(user_id)
        if user is None or user.disabled or not _identity(user).is_admin:
            raise self._error("coding_host_permission", user_id=user_id, status=403)
        allowed = effective_workspace_root_dir(
            self._repos.user_policy_repo.get(user_id, POLICY_WORKSPACE_ROOT_DIR)
        )
        try:
            path = normalize_project_path(spec.project_path, allowed_root=allowed)
        except (ValueError, OSError) as exc:
            raise self._error("coding_invalid_path", user_id=user_id) from exc
        registered = {
            str(project["project_path"])
            for agent in self._repos.agent_repo.list_by_user(user_id)
            for project in self._repos.thread_repo.list_projects(
                agent_id=agent.agent_id, user_id=user_id
            )
        }
        if path not in registered:
            raise self._error("coding_registered_project", user_id=user_id)

    async def validate_dispatch_actor(self, user_id: int, agent_id: str) -> None:
        await asyncio.to_thread(self._validate_task_policy, user_id, agent_id, None, TaskOptions())

    async def available_experts(self, user_id: int) -> builtins.list[dict[str, Any]]:
        from octop.infra.agents.teams.service import is_team_agent

        rows = await asyncio.to_thread(self._repos.agent_repo.list_by_user, user_id)
        return [
            {
                "agent_id": row.agent_id,
                "name": row.name,
                "description": str(getattr(row, "description", "") or "")[:1000],
                "enabled": bool(row.enabled),
            }
            for row in rows
            if row.enabled and not is_team_agent(row)
        ]

    async def public_task(self, row: TaskRow, *, detail: bool) -> dict[str, Any]:
        result = row.to_public(detail=detail)
        result["dispatch"] = await asyncio.to_thread(
            self._repos.task_dispatch_repo.get, row.task_id
        )
        await self._enrich_coordination(row, result)
        return result

    async def _enrich_coordination(self, row: TaskRow, result: dict[str, Any]) -> None:
        context = result.get("dispatch")
        scope_id = (context or {}).get("scope_id")
        if not scope_id:
            scopes = await asyncio.to_thread(
                self._repos.task_coordination_repo.for_parent, row.task_id, row.attempt
            )
            scope_id = scopes[-1]["scope_id"] if scopes else None
        if scope_id:
            context = context or {"task_id": row.task_id}
            context["coordination"] = await self._coordinator.public(scope_id)
            result["dispatch"] = context

    def bound_task(self, agent_id: str, user_id: int, thread_id: str) -> TaskRow | None:
        binding = self._bindings.get((agent_id, user_id, thread_id))
        row = self._repo.get(binding[0]) if binding else None
        return (
            row
            if row is not None
            and binding is not None
            and row.user_id == user_id
            and row.agent_id == agent_id
            and row.attempt == binding[1]
            and row.state in {"running", "waiting"}
            else None
        )

    def _validate_task_policy(
        self, user_id: int, agent_id: str, thread_id: str | None, options: TaskOptions
    ) -> None:
        user = self._repos.user_repo.get(user_id)
        if user is not None:
            self._locales[user.id] = user.locale
        if user is None or user.disabled or not user_has_permission(_identity(user), "tasks"):
            raise self._error("permission_removed", user_id=user_id, status=403)
        agent = self._owned_agent(agent_id, user_id)
        if not agent.enabled:
            raise self._error("agent_disabled", user_id=user_id, status=409)
        if thread_id:
            thread = self._repos.thread_repo.get(thread_id)
            if thread is None or thread.user_id != user_id or thread.agent_id != agent_id:
                raise self._error("thread_not_owned", user_id=user_id, status=404)
        # Store names and selection only; tokens are resolved by the normal processor at execution.
        if options.mcp_servers is not None:
            self._agents.validate_mcp_servers(user_id, options.mcp_servers)
        if options.knowledge_base_ids is not None:
            self._agents.validate_knowledge_base_ids(user_id, options.knowledge_base_ids)
        if options.model and not self._agents.providers.is_model_ref_usable(options.model):
            raise self._error("model_unavailable", user_id=user_id)

    async def list(
        self, user_id: int, *, archived: bool = False, agent_id: str | None = None
    ) -> builtins.list[dict[str, Any]]:
        rows = await asyncio.to_thread(
            self._repo.list, user_id, archived=archived, agent_id=agent_id
        )
        contexts = await asyncio.to_thread(
            self._repos.task_dispatch_repo.get_many, [row.task_id for row in rows]
        )
        result = []
        for row in rows:
            item = {**row.to_public(detail=False), "dispatch": contexts.get(row.task_id)}
            await self._enrich_coordination(row, item)
            result.append(item)
        return result

    async def detail(self, user_id: int, task_id: str) -> dict[str, Any]:
        row = await asyncio.to_thread(self._owned_task, task_id, user_id)
        result = await self.public_task(row, detail=True)
        result["events"] = await asyncio.to_thread(self._repo.events, task_id)
        return result

    async def decide_coordination(
        self, user_id: int, scope_id: str, *, decision: str, summary: str, question: str
    ) -> dict[str, Any]:
        from octop.infra.tasks.scope import current_coordinator_scope

        context = current_coordinator_scope()
        scope = await asyncio.to_thread(self._repos.task_coordination_repo.get, scope_id)
        if (
            context is None
            or context.scope_id != scope_id
            or context.user_id != user_id
            or scope is None
            or scope["user_id"] != user_id
            or scope["state"] != "running"
            or scope["active_signature"] != context.active_signature
        ):
            raise self._error("dispatch_context", user_id=user_id, status=403)
        if decision == "needs_user" and not question.strip():
            raise self._error("coordination_question", user_id=user_id)
        if decision == "ready":
            members = await asyncio.to_thread(self._repos.task_coordination_repo.members, scope_id)
            if any(
                member["state"] not in TERMINAL_STATES for member in members
            ) or self._rooms.has_pending_peers(scope_id):
                raise self._error("coordination_running", user_id=user_id, status=409)
        changed = await asyncio.to_thread(
            self._repos.task_coordination_repo.decide,
            scope_id,
            decision,
            summary[:6000],
            question[:6000],
        )
        if not changed:
            raise self._error("invalid_transition", user_id=user_id, status=409)
        return {"scope_id": scope_id, "decision": decision, "recorded": True}

    async def validate_scoped_action(
        self,
        user_id: int,
        scope_id: str,
        task_id: str,
        action: str,
        *,
        direct_user: bool = False,
    ) -> None:
        row = await asyncio.to_thread(self._owned_task, task_id, user_id)
        context = await asyncio.to_thread(self._repos.task_dispatch_repo.get, task_id)
        scope = await asyncio.to_thread(self._repos.task_coordination_repo.get, scope_id)
        if (
            not context
            or context.get("scope_id") != scope_id
            or not scope
            or (scope["state"] != "running" and not direct_user)
            or scope["state"] == "stopped"
        ):
            raise self._error("dispatch_context", user_id=user_id, status=403)
        if action == "retry" and await asyncio.to_thread(self._scope_approval_paused, scope):
            raise self._error("coordination_source_busy", user_id=user_id, status=409)
        if action == "retry" and row.state == "cancelled" and not direct_user:
            raise self._error("coordination_cancelled", user_id=user_id, status=409)
        spec = context.get("coding_spec")
        if action == "retry" and spec and spec.get("publish_pr") and not scope.get("allow_publish"):
            raise self._error("coordination_publish", user_id=user_id, status=403)

    async def continue_coordination(
        self, user_id: int, task_id: str, *, prompt: str, allow_publish: bool | None = None
    ) -> dict[str, Any]:
        row = await asyncio.to_thread(self._owned_task, task_id, user_id)
        view = await self.public_task(row, detail=False)
        scope_view = (view.get("dispatch") or {}).get("coordination")
        if not scope_view or not prompt.strip():
            raise self._error("dispatch_context", user_id=user_id)
        scope = await asyncio.to_thread(
            self._repos.task_coordination_repo.get, scope_view["scope_id"]
        )
        if scope is None or scope["user_id"] != user_id:
            raise self._error("not_found", user_id=user_id, status=404)
        await self.validate_dispatch_actor(
            user_id, self._agents.principal_agent_id(scope["origin_agent_id"])
        )
        await asyncio.to_thread(self._origin_thread, user_id, scope["origin_thread_id"])
        if self._gateway.steer.is_hitl_paused(scope["origin_thread_id"]):
            raise self._error("coordination_source_busy", user_id=user_id, status=409)
        if scope.get("parent_task_id"):
            parent = await asyncio.to_thread(self._repo.get, scope["parent_task_id"])
            if (
                parent is None
                or parent.attempt != scope["parent_attempt"]
                or parent.state not in {"running", "waiting"}
            ):
                raise self._error("recovery_requires_retry", user_id=user_id, status=409)
        if allow_publish:
            user = await asyncio.to_thread(self._repos.user_repo.get, user_id)
            if user is None or not _identity(user).is_admin:
                raise self._error("coding_host_permission", user_id=user_id, status=403)
        changed = await asyncio.to_thread(
            self._repos.task_coordination_repo.resume,
            scope["scope_id"],
            user_id,
            prompt.strip(),
            allow_publish,
        )
        if not changed:
            raise self._error("invalid_transition", user_id=user_id, status=409)
        if scope.get("parent_task_id"):
            await asyncio.to_thread(
                self._repo.transition,
                scope["parent_task_id"],
                expected={"waiting"},
                expected_attempt=scope["parent_attempt"],
                state="running",
                action="coordination_resumed",
            )
        self._wake.set()
        return {"scope_id": scope["scope_id"], "accepted": True}

    async def stop_coordination(self, user_id: int, task_id: str) -> dict[str, Any]:
        row = await asyncio.to_thread(self._owned_task, task_id, user_id)
        view = await self.public_task(row, detail=False)
        scope_view = (view.get("dispatch") or {}).get("coordination")
        if not scope_view or scope_view.get("user_id") != user_id:
            raise self._error("not_found", user_id=user_id, status=404)
        scope = await asyncio.to_thread(
            self._repos.task_coordination_repo.get, scope_view["scope_id"]
        )
        if scope is None or scope["user_id"] != user_id:
            raise self._error("not_found", user_id=user_id, status=404)
        await self._coordinator.stop_scope(scope)
        self._wake.set()
        return {"scope_id": scope["scope_id"], "accepted": True}

    async def action(
        self,
        user_id: int,
        task_id: str,
        action: str,
        *,
        agent_id: str | None = None,
        expected_attempt: int | None = None,
    ) -> TaskRow:
        async with self._mutation_locks.setdefault(task_id, asyncio.Lock()):
            if expected_attempt is not None:
                row = await asyncio.to_thread(self._owned_task, task_id, user_id)
                if row.attempt != expected_attempt:
                    raise self._error("invalid_transition", user_id=user_id, status=409)
            return await self._action_locked(user_id, task_id, action, agent_id=agent_id)

    async def _action_locked(
        self, user_id: int, task_id: str, action: str, *, agent_id: str | None = None
    ) -> TaskRow:
        row = await asyncio.to_thread(self._owned_task, task_id, user_id)
        if action == "retry":
            if row.archived or row.state not in {"failed", "cancelled", "interrupted"}:
                raise self._error("invalid_transition", user_id=user_id, status=409)
            await asyncio.to_thread(
                self._validate_task_policy,
                row.user_id,
                row.agent_id,
                row.thread_id,
                TaskOptions.model_validate_json(row.options_json),
            )
            streams = [
                lease.stream_task
                for lease in self._resume_leases.get(task_id, set())
                if lease.attempt == row.attempt
                and lease.stream_task is not None
                and lease.stream_task is not asyncio.current_task()
                and not lease.stream_task.done()
            ]
            if streams:
                await asyncio.gather(*streams, return_exceptions=True)
            worker = self._running.get(task_id)
            if worker is not None and not worker.done():
                try:
                    await asyncio.shield(worker)
                except asyncio.CancelledError:
                    if not worker.cancelled():
                        raise
                except Exception:
                    pass
                row = await asyncio.to_thread(self._owned_task, task_id, user_id)
        if action == "retry":
            from octop.infra.tasks.children import cancel_children

            verifier = self._verification_tasks.get((task_id, row.attempt))
            if verifier is not None and verifier is not asyncio.current_task():
                await asyncio.gather(verifier, return_exceptions=True)
            await cancel_children(self, row)
            await reset_for_retry(
                self._agents, self._repos, row, locale=self._locales.get(user_id, DEFAULT_LOCALE)
            )
            if row.thread_id:
                self._gateway.processor.hitl_coordinator.expire_pending_for_thread(
                    row.thread_id, agent_id=row.agent_id, user_id=user_id
                )
        if row.archived and action != "restore":
            raise self._error("invalid_transition", user_id=user_id, status=409)
        fields: dict[str, Any] = {}
        state = row.state
        if action == "pause" and state == "queued":
            state = "paused"
        elif action == "resume" and state == "paused":
            state = "queued"
        elif action == "retry" and state in {"failed", "cancelled", "interrupted"}:
            state = "queued"
            fields = {"error_code": None, "result": "", "finished_at": None}
        elif action == "cancel" and state not in TERMINAL_STATES:
            state = "cancelled"
            fields = {"finished_at": now_ts()}
        elif action == "archive" and state in TERMINAL_STATES:
            fields = {"archived": 1}
        elif action == "restore" and row.archived:
            fields = {"archived": 0}
        elif (
            action == "reassign"
            and state in {"queued", "paused", "failed", "cancelled", "interrupted"}
            and agent_id
        ):
            await asyncio.to_thread(self._owned_agent, agent_id, user_id)
            context = await asyncio.to_thread(self._repos.task_dispatch_repo.get, row.task_id)
            if context and context.get("parent_task_id"):
                parent = await asyncio.to_thread(
                    self._owned_task, context["parent_task_id"], user_id
                )
                if parent.attempt != context["parent_attempt"] or parent.state not in {
                    "running",
                    "waiting",
                }:
                    raise self._error("invalid_transition", user_id=user_id, status=409)
                await asyncio.to_thread(self._assert_dispatch_target, user_id, parent, agent_id)
            fields = {"agent_id": agent_id, "thread_id": None}
        else:
            raise self._error("invalid_transition", user_id=user_id, status=409)
        changed = await asyncio.to_thread(
            self._repo.transition,
            task_id,
            expected={row.state},
            expected_attempt=row.attempt,
            state=state,
            action=action,
            actor_user_id=user_id,
            fields=fields,
        )
        if not changed:
            raise self._error("invalid_transition", user_id=user_id, status=409)
        if action == "cancel":
            from octop.infra.tasks.children import cancel_children

            await self._coordinator.stop_parent(row)
            await cancel_children(self, row)
            verifier = self._verification_tasks.get((task_id, row.attempt))
            if verifier is not None and verifier is not asyncio.current_task():
                verifier.cancel()
            for lease in list(self._resume_leases.get(task_id, set())):
                if lease.attempt == row.attempt:
                    lease.cancel()
                    if lease.stream_task is None:
                        self._release_resume(lease)
            if row.thread_id and row.attempt > 0:
                self._bindings[(row.agent_id, row.user_id, row.thread_id)] = (
                    row.task_id,
                    row.attempt,
                )
            cancel_scoped_jobs(self._agents, row)
            if row.thread_id:
                self._agents.cancel_stream(row.agent_id, row.thread_id)
            completion = self._continuations.get(task_id)
            if completion is not None:
                completion.cancel()
            if row.thread_id:
                processor = self._gateway.processor
                processor.hitl_coordinator.expire_pending_for_thread(
                    row.thread_id, agent_id=row.agent_id, user_id=user_id
                )
                processor.teams.cancel_member_hitl(row.thread_id)
                self._gateway.steer.mark_cancelling(row.thread_id)
                discarded = self._gateway.steer.discard(row.thread_id, reason="turn_cancelled")
                if discarded is not None:
                    await self._gateway.ws_hub.push_to_thread(
                        row.thread_id,
                        {
                            "type": "steer.discarded",
                            "seq": discarded.seq,
                            "client_pending_ids": discarded.client_pending_ids,
                            "pending_ids": discarded.pending_ids,
                            "turn_id": discarded.turn_id,
                            "reason": discarded.reason,
                            "thread_id": row.thread_id,
                        },
                    )
            running = self._running.get(task_id)
            if running:
                running.cancel()
        self._wake.set()
        updated = await asyncio.to_thread(self._owned_task, task_id, user_id)
        await self._publish(updated, notify=False)
        return updated

    async def pause_queue(self, user_id: int, agent_id: str, paused: bool) -> None:
        await asyncio.to_thread(self._owned_agent, agent_id, user_id)
        await asyncio.to_thread(self._repo.set_queue_paused, agent_id, user_id, paused)
        self._wake.set()

    async def controls(self, user_id: int) -> dict[str, bool]:
        return await asyncio.to_thread(self._repo.queue_controls, user_id)

    async def _serve(self) -> None:
        while True:
            self._wake.clear()
            try:
                await self.process_schedules()
                await self.process_once()
            except Exception as exc:
                # Persistence/network failures must not permanently kill admission.
                logger.error("Task dispatcher unavailable (%s)", type(exc).__name__)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=2)

    async def process_once(self) -> None:
        """Bounded dispatcher seam used by the worker and deterministic tests."""
        await self._retry_returns()
        await self._rooms.process()
        await self._coordinator.schedule()
        for task_id, task in list(self._running.items()):
            if task.done() and not task.cancelled() and task.exception() is not None:
                await asyncio.to_thread(
                    self._repo.transition,
                    task_id,
                    expected={"running"},
                    state="interrupted",
                    action="interrupted",
                    fields={"error_code": "interrupted", "finished_at": now_ts()},
                )
        self._running = {key: task for key, task in self._running.items() if not task.done()}
        for row in await asyncio.to_thread(self._repo.queue_heads):
            if len(set(self._running) - self._delegated_waiters) >= 2:
                break
            if row.state != "queued" or self._agents.is_agent_active(row.agent_id):
                continue
            if not await self._parent_current(row):
                await asyncio.to_thread(
                    self._repo.transition,
                    row.task_id,
                    expected={"queued"},
                    expected_attempt=row.attempt,
                    state="cancelled",
                    action="cancel",
                    fields={"finished_at": now_ts()},
                )
                changed = await asyncio.to_thread(self._repo.get, row.task_id)
                if changed is not None:
                    await self._notify_result(changed)
                continue
            user = await asyncio.to_thread(self._repos.user_repo.get, row.user_id)
            agent = await asyncio.to_thread(self._repos.agent_repo.get, row.agent_id)
            if user is None or user.disabled or agent is None or not agent.enabled:
                continue
            self._locales[user.id] = user.locale
            if agent.user_id != row.user_id or not user_has_permission(_identity(user), "tasks"):
                await asyncio.to_thread(
                    self._repo.transition,
                    row.task_id,
                    expected={"queued"},
                    state="failed",
                    action="permission_removed",
                    fields={"error_code": "permission_removed", "finished_at": now_ts()},
                )
                continue
            dependencies = await asyncio.to_thread(self._repo.dependencies, row)
            if any(dep.state in {"failed", "cancelled", "interrupted"} for dep in dependencies):
                await asyncio.to_thread(
                    self._repo.transition,
                    row.task_id,
                    expected={"queued"},
                    state="failed",
                    action="dependency_failed",
                    fields={"error_code": "dependency_failed", "finished_at": now_ts()},
                )
                continue
            if any(dep.state != "completed" for dep in dependencies):
                continue
            if not await asyncio.to_thread(self._repo.claim, row.task_id):
                continue
            claimed = await asyncio.to_thread(self._repo.get, row.task_id)
            if claimed is None or claimed.state != "running":
                continue
            await self._publish(claimed, notify=False)
            self._running[row.task_id] = asyncio.create_task(
                self._execute(row.task_id), name=f"task-{row.task_id}"
            )

    async def _execute(self, task_id: str) -> None:
        row = await asyncio.to_thread(self._repo.get, task_id)
        if row is None or row.state != "running":
            return
        if not await self._parent_current(row):
            await asyncio.to_thread(
                self._repo.transition,
                row.task_id,
                expected={"running"},
                expected_attempt=row.attempt,
                state="cancelled",
                action="cancel",
                fields={"finished_at": now_ts()},
            )
            return
        result_parts: builtins.list[str] = []
        failed = False
        waiting = False
        delegated: asyncio.Future[dict[str, Any]] | None = None
        try:
            await asyncio.to_thread(
                self._validate_task_policy,
                row.user_id,
                row.agent_id,
                row.thread_id,
                TaskOptions.model_validate_json(row.options_json),
            )
            await self._agents.start(row.agent_id)
            if not row.thread_id:
                thread_id = await self._gateway.thread_registry.get_or_create(
                    agent_id=row.agent_id,
                    user_id=row.user_id,
                    channel_type="dashboard",
                    channel_subject_id=f"task-{task_id}",
                    channel_metadata={"task_id": task_id},
                )
                await asyncio.to_thread(
                    self._gateway.thread_registry.set_title_if_null, thread_id, row.title
                )
                dispatch = await asyncio.to_thread(self._repos.task_dispatch_repo.get, task_id)
                if dispatch and dispatch.get("origin_thread_id"):
                    from octop.infra.agents.threads.project_runtime import inherit_task_project

                    await asyncio.to_thread(
                        inherit_task_project,
                        self._repos.thread_repo,
                        source_id=dispatch["origin_thread_id"],
                        target_id=thread_id,
                        user_id=row.user_id,
                        agent_id=row.agent_id,
                    )
                await asyncio.to_thread(
                    self._repo.transition,
                    task_id,
                    expected={"running"},
                    state="running",
                    action="thread_created",
                    fields={"thread_id": thread_id},
                )
                row = await asyncio.to_thread(self._repo.get, task_id)
                if row is None:
                    return
            thread_id = row.thread_id
            assert thread_id is not None
            thread = await asyncio.to_thread(self._gateway.thread_registry.get_thread, thread_id)
            if thread is None:
                raise RuntimeError("task conversation was deleted")
            self._bindings[(row.agent_id, row.user_id, thread_id)] = (row.task_id, row.attempt)
            await self._publish(row, notify=False)
            prompt = row.prompt
            dependencies = await asyncio.to_thread(self._repo.dependencies, row)
            if dependencies:
                # Results are quoted data, never new tool privileges or secret configuration.
                prompt += "\n\n" + json.dumps(
                    {
                        "dependency_results": [
                            {
                                "step": dep.step_key,
                                "task_id": dep.task_id,
                                "agent_id": dep.agent_id,
                                "thread_id": dep.thread_id,
                                "result": dep.result,
                            }
                            for dep in dependencies
                        ]
                    },
                    ensure_ascii=False,
                )
            options = TaskOptions.model_validate_json(row.options_json)
            await asyncio.to_thread(
                self._validate_task_policy, row.user_id, row.agent_id, row.thread_id, options
            )
            code_context = await self._prepare_coding(row)
            if code_context:
                prompt += "\n\n" + code_context
            if options.skills is not None:
                available = await self._agents.list_skill_summaries(row.agent_id)
                allowed = {
                    str(item[key])
                    for item in available
                    if item.get("enabled")
                    for key in ("name", "slug")
                    if item.get(key)
                }
                if any(name not in allowed for name in options.skills):
                    raise self._error("selection_unavailable", user_id=row.user_id)
            user = await asyncio.to_thread(self._repos.user_repo.get, row.user_id)
            metadata: dict[str, Any] = {
                "thread_id": thread_id,
                "session_key": thread.session_key,
                "task_id": task_id,
                "task_attempt": row.attempt,
                "conversation_mode": options.conversation_mode,
                "ws_connection_id": f"task:{task_id}",
                "user_is_admin": bool(user and _identity(user).is_admin),
            }
            for key in ("model", "mcp_servers", "skills", "knowledge_base_ids"):
                value = getattr(options, key)
                if value is not None:
                    metadata[key] = value
            references = await self._prepare_attachments(
                row.user_id, row.agent_id, options.attachments, check_expiry=False
            )
            parts = [TextContent(text=prompt), *content_parts(references)]
            if references:
                metadata[INBOUND_ATTACHMENTS_KEY] = inbound_attachments_from_parts(parts)
            message = InboundMessage(
                channel_id=self._gateway.dashboard_channel_id,
                channel_type="dashboard",
                tenant_id=row.agent_id,
                channel_subject=ChannelSubject(subject_id=str(row.user_id), chat_type="dm"),
                content=parts,
                metadata=metadata,
            )
            manager = self._gateway.channel_manager
            if manager is None:
                raise RuntimeError("gateway not ready")

            async def observe(chunk: dict[str, Any]) -> None:
                nonlocal failed, waiting
                await self._rooms.relay(row, chunk)
                kind = chunk.get("type")
                if kind == "token":
                    result_parts.append(str(chunk.get("content") or ""))
                if kind == "error":
                    failed = True
                if kind == "hitl_required":
                    waiting = True
                if kind == "turn.ended":
                    waiting = bool(chunk.get("hitl_paused"))

            channel = manager.get_channel(self._gateway.dashboard_channel_id)
            if channel is None:
                raise RuntimeError("dashboard channel not ready")
            connection_id = f"task:{task_id}"
            self._gateway.ws_hub.register(connection_id, observe)
            try:
                await manager.run_in_session(
                    self._gateway.dashboard_channel_id,
                    f"thread:{thread_id}",
                    lambda: channel.handle_inbound(message),
                )
            finally:
                self._gateway.ws_hub.unregister(connection_id)
            waiting = self._gateway.steer.is_hitl_paused(thread_id)
            if not waiting:
                delegated = self._background_completion(row)
                if delegated is not None:
                    self._continuations[task_id] = delegated
                    outcome = await asyncio.shield(delegated)
                    failed = failed or bool(outcome.get("failed"))
                    result_parts.append(str(outcome.get("output") or ""))
                    if self._continuations.get(task_id) is delegated:
                        self._continuations.pop(task_id, None)
                from octop.infra.tasks.children import background_children

                delegated = await background_children(self, row)
                if delegated is not None:
                    self._continuations[task_id] = delegated
                    outcome = await asyncio.shield(delegated)
                    failed = failed or bool(outcome.get("failed"))
                    result_parts.append(str(outcome.get("output") or ""))
                    if self._continuations.get(task_id) is delegated:
                        self._continuations.pop(task_id, None)
            if not waiting and not failed:
                code_failed, code_summary = await self._finish_coding(row)
                failed = failed or code_failed
                if code_summary:
                    result_parts.append("\n\n" + code_summary)
            state = "failed" if failed else "waiting" if waiting else "completed"
            from octop.infra.tasks.admission import finish_task

            await finish_task(
                self,
                row,
                state=state,
                fields={
                    "result": "".join(result_parts)[-128000:],
                    "error_code": "execution_failed" if failed else None,
                    "finished_at": None if waiting else now_ts(),
                },
            )
        except asyncio.CancelledError:
            await close_background(delegated)
            if row is not None and row.thread_id:
                self._agents.cancel_stream(row.agent_id, row.thread_id)
            await asyncio.to_thread(
                self._repo.transition,
                task_id,
                expected={"running", "waiting"},
                state="interrupted",
                action="interrupted",
                fields={"error_code": "interrupted", "finished_at": now_ts()},
            )
            raise
        except Exception as exc:
            # Do not persist raw network exceptions, tool arguments or credentials.
            from octop.infra.tasks.coding import CodingTaskError

            code = exc.code if isinstance(exc, CodingTaskError) else "execution_failed"
            if isinstance(exc, OctopError):
                reason = exc.details.get("task_reason") if exc.details else None
                if isinstance(reason, str) and reason.startswith("coding_"):
                    code = reason
            await asyncio.to_thread(
                self._repo.transition,
                task_id,
                expected={"running", "waiting"},
                expected_attempt=row.attempt if row is not None else None,
                state="failed",
                action="failed",
                fields={"error_code": code, "finished_at": now_ts()},
            )
        finally:
            latest = await asyncio.to_thread(self._repo.get, task_id)
            if latest and latest.state in {"failed", "interrupted"} and latest.run_id:
                await self._apply_failure_policy(latest.run_id)
            if latest:
                await self._notify_result(latest)
            self._wake.set()

    def _code_service(self) -> Any:
        if self._coding_service is None:
            from octop.infra.tasks.coding import CodingTaskService

            self._coding_service = CodingTaskService()
        return self._coding_service

    async def _parent_current(self, row: TaskRow) -> bool:
        context = await asyncio.to_thread(self._repos.task_dispatch_repo.get, row.task_id)
        if context and context.get("scope_id"):
            scope = await asyncio.to_thread(
                self._repos.task_coordination_repo.get, context["scope_id"]
            )
            if scope is None or scope["state"] == "stopped":
                return False
        parent_id = (context or {}).get("parent_task_id")
        if not parent_id:
            return True
        parent = await asyncio.to_thread(self._repo.get, parent_id)
        return bool(
            context is not None
            and parent is not None
            and parent.user_id == row.user_id
            and parent.attempt == context["parent_attempt"]
            and parent.state in {"running", "waiting"}
        )

    async def _prepare_coding(self, row: TaskRow) -> str:
        from octop.infra.tasks.models import CodingTaskSpec

        context = await asyncio.to_thread(self._repos.task_dispatch_repo.get, row.task_id)
        if not context or not context.get("coding_spec"):
            return ""
        spec = CodingTaskSpec.model_validate(context["coding_spec"])
        await asyncio.to_thread(self._validate_coding, row.user_id, spec)
        run = await self._code_service().prepare(
            row.task_id, row.user_id, spec, previous=context.get("coding_run") or None
        )
        if not await asyncio.to_thread(
            self._repos.task_dispatch_repo.update_coding,
            row.task_id,
            run,
            expected_attempt=row.attempt,
            expected_states={"running", "waiting"},
        ):
            raise self._error("invalid_transition", user_id=row.user_id, status=409)
        return str(self._code_service().prompt_context(run))

    async def _finish_coding(self, row: TaskRow) -> tuple[bool, str]:
        current = asyncio.current_task()
        key = (row.task_id, row.attempt)
        if current is not None:
            self._verification_tasks[key] = current
        try:
            return await self._verify_coding(row)
        finally:
            if self._verification_tasks.get(key) is current:
                self._verification_tasks.pop(key, None)

    async def _coding_active(self, row: TaskRow) -> None:
        current = await asyncio.to_thread(self._repo.get, row.task_id)
        if (
            current is None
            or current.attempt != row.attempt
            or current.state not in {"running", "waiting"}
            or current.archived
        ):
            raise asyncio.CancelledError
        if not await self._parent_current(row):
            raise asyncio.CancelledError
        context = await asyncio.to_thread(self._repos.task_dispatch_repo.get, row.task_id)
        if (
            context
            and context.get("scope_id")
            and (context.get("coding_spec") or {}).get("publish_pr")
        ):
            scope = await asyncio.to_thread(
                self._repos.task_coordination_repo.get, context["scope_id"]
            )
            if not scope or not scope.get("allow_publish"):
                raise self._error("coordination_publish", user_id=row.user_id, status=403)
        await asyncio.to_thread(
            self._validate_task_policy,
            row.user_id,
            row.agent_id,
            row.thread_id,
            TaskOptions(),
        )

    async def _verify_coding(self, row: TaskRow) -> tuple[bool, str]:
        from octop.infra.tasks.models import CodingTaskSpec

        context = await asyncio.to_thread(self._repos.task_dispatch_repo.get, row.task_id)
        if not context or not context.get("coding_spec"):
            return False, ""
        await self._coding_active(row)
        spec = CodingTaskSpec.model_validate(context["coding_spec"])
        await asyncio.to_thread(self._validate_coding, row.user_id, spec)
        run = {**context.get("coding_run", {}), "phase": "verifying"}
        if not await asyncio.to_thread(
            self._repos.task_dispatch_repo.update_coding,
            row.task_id,
            run,
            expected_attempt=row.attempt,
            expected_states={"running", "waiting"},
        ):
            raise self._error("invalid_transition", user_id=row.user_id, status=409)
        await self._publish(row, notify=False)
        locale = self._locales.get(row.user_id, DEFAULT_LOCALE)

        async def check_active() -> None:
            await self._coding_active(row)
            await asyncio.to_thread(self._validate_coding, row.user_id, spec)

        async def verify_locked() -> None:
            nonlocal run
            await check_active()
            run = await self._code_service().finalize(
                row.task_id, row.title, spec, run, locale=locale, check_active=check_active
            )

        channel_manager = self._gateway.channel_manager
        if channel_manager is None or not row.thread_id:
            raise self._error("invalid_transition", user_id=row.user_id, status=409)
        # Admission sees the persisted verifying phase; turns admitted earlier
        # finish under this same transport lock before the exact-tree check.
        await channel_manager.run_in_session(
            self._gateway.dashboard_channel_id, f"thread:{row.thread_id}", verify_locked
        )
        await check_active()
        changed = await asyncio.to_thread(
            self._repos.task_dispatch_repo.update_coding,
            row.task_id,
            run,
            expected_attempt=row.attempt,
            expected_states={"running", "waiting"},
        )
        if not changed:
            raise self._error("invalid_transition", user_id=row.user_id, status=409)
        failed = run.get("phase") in {"verification_failed", "delivery_failed"}
        if failed:
            summary = tr(
                f"tasks.errors.{run.get('error_code') or 'coding_verification_failed'}", locale
            )
        else:
            summary = tr("tasks.coding.verified", locale, count=len(run.get("verification", [])))
            if run.get("pr_url"):
                summary += "\n" + str(run["pr_url"])
            elif run.get("phase") == "unchanged":
                summary += "\n" + tr("tasks.coding.unchanged", locale)
        return failed, summary

    async def _return_result(self, row: TaskRow) -> None:
        from octop.infra.tasks.returns import TaskReturnService

        async with self._return_locks.setdefault(row.task_id, asyncio.Lock()):
            service = getattr(self, "_return_service", None)
            if service is None:
                service = TaskReturnService(
                    repos=self._repos, gateway=self._gateway, agents=self._agents
                )
                self._return_service = service
            await service.deliver(row)

    async def _retry_returns(self) -> None:
        pending = await asyncio.to_thread(
            self._repos.task_dispatch_repo.pending_returns, limit=20, offset=self._return_offset
        )
        self._return_offset = self._return_offset + len(pending) if len(pending) == 20 else 0
        for context in pending:
            row = await asyncio.to_thread(self._repo.get, context["task_id"])
            if row is not None:
                with contextlib.suppress(Exception):
                    await self._return_result(row)

    async def complete_waiting_turn(
        self,
        *,
        agent_id: str,
        user_id: int,
        thread_id: str,
        failed: bool,
        paused: bool,
        output: str = "",
        continuation: asyncio.Future[dict[str, Any]] | None = None,
        attempts: dict[str, int] | None = None,
    ) -> None:
        """Finalize an approval segment after its exact queued WS continuation.

        The HTTP resume yields its own output before a parked steer is queued.
        A non-null continuation is the private Future carried by that inbound
        message, never a socket-idle guess or a lock acquired ahead of its worker.
        """
        job = asyncio.create_task(
            self._finish_waiting_turn(
                agent_id=agent_id,
                user_id=user_id,
                thread_id=thread_id,
                failed=failed,
                paused=paused,
                output=output,
                continuation=continuation,
                attempts=attempts,
                origin=asyncio.current_task(),
            ),
            name=f"task-resume-finalize-{thread_id}",
        )
        self._finalizers.add(job)

        def finished(task: asyncio.Task[None]) -> None:
            self._finalizers.discard(task)
            if not task.cancelled() and task.exception() is not None:
                logger.error("Task resume finalization failed")

        job.add_done_callback(finished)
        # HTTP disconnects do not abandon committed approval/continuation work.
        await asyncio.shield(job)

    async def _finish_waiting_turn(
        self,
        *,
        agent_id: str,
        user_id: int,
        thread_id: str,
        failed: bool,
        paused: bool,
        output: str,
        continuation: asyncio.Future[dict[str, Any]] | None,
        attempts: dict[str, int] | None,
        origin: asyncio.Task[Any] | None,
    ) -> None:
        rows = await asyncio.to_thread(self._repo.active_in_thread, agent_id, user_id, thread_id)
        for original in rows:
            if attempts is not None and attempts.get(original.task_id) != original.attempt:
                continue
            worker = self._running.get(original.task_id)
            if worker is not None and worker is not origin and not worker.done():
                # The first pause can reach HTTP before the original WS task has
                # finished persisting its result. Do not overwrite that segment.
                try:
                    await asyncio.shield(worker)
                except asyncio.CancelledError:
                    if worker.cancelled():
                        continue
                    raise
                except Exception:
                    continue
            row = await asyncio.to_thread(self._repo.get, original.task_id)
            if (
                row is None
                or row.attempt != original.attempt
                or row.state not in {"running", "waiting"}
            ):
                if (
                    continuation is not None
                    and row is not None
                    and row.state in {"cancelled", "interrupted"}
                ):
                    continuation.cancel()
                continue
            if continuation is None and not paused and not failed:
                continuation = self._background_completion(row)
                if continuation is None:
                    from octop.infra.tasks.children import background_children

                    continuation = await background_children(self, row)
            task_failed = failed
            task_output = output
            if continuation is None and not paused and not task_failed:
                try:
                    code_failed, code_summary = await self._finish_coding(row)
                    task_failed = task_failed or code_failed
                    if code_summary:
                        task_output += "\n\n" + code_summary
                except Exception:
                    task_failed = True
            state = (
                "running"
                if continuation is not None
                else "failed"
                if task_failed
                else "waiting"
                if paused
                else "completed"
            )
            from octop.infra.tasks.admission import finish_task

            changed = await finish_task(
                self,
                row,
                state=state,
                action="approval_resumed",
                fields={
                    "finished_at": None if state in {"running", "waiting"} else now_ts(),
                    "error_code": "execution_failed" if task_failed and state == "failed" else None,
                },
                append_result=task_output,
            )
            if not changed:
                continue
            if continuation is not None:
                self._continuations[row.task_id] = continuation
                self._running[row.task_id] = asyncio.create_task(
                    self._wait_continuation(row, continuation, failed=failed),
                    name=f"task-continuation-{row.task_id}",
                )
            else:
                updated = await asyncio.to_thread(self._repo.get, row.task_id)
                if updated:
                    if updated.state == "failed" and updated.run_id:
                        await self._apply_failure_policy(updated.run_id)
                    await self._notify_result(updated)
        self._wake.set()

    async def _wait_continuation(
        self, row: TaskRow, completion: asyncio.Future[dict[str, Any]], *, failed: bool
    ) -> None:
        try:
            outcome = await asyncio.shield(completion)
            await self.complete_waiting_turn(
                agent_id=row.agent_id,
                user_id=row.user_id,
                thread_id=row.thread_id or "",
                failed=failed or bool(outcome.get("failed")),
                paused=bool(outcome.get("paused")),
                output=str(outcome.get("output") or ""),
                attempts={row.task_id: row.attempt},
            )
        except asyncio.CancelledError:
            await close_background(completion)
            if row.thread_id:
                self._agents.cancel_stream(row.agent_id, row.thread_id)
            await asyncio.to_thread(
                self._repo.transition,
                row.task_id,
                expected={"running", "waiting"},
                expected_attempt=row.attempt,
                state="interrupted",
                action="interrupted",
                fields={"error_code": "interrupted", "finished_at": now_ts()},
            )
            raise
        except Exception:
            await asyncio.to_thread(
                self._repo.transition,
                row.task_id,
                expected={"running", "waiting"},
                expected_attempt=row.attempt,
                state="failed",
                action="continuation_failed",
                fields={"error_code": "execution_failed", "finished_at": now_ts()},
            )
        finally:
            if self._continuations.get(row.task_id) is completion:
                self._continuations.pop(row.task_id, None)
            self._wake.set()

    async def create_workflow(
        self, user_id: int, *, name: str, definition: WorkflowDefinition, enabled: bool = True
    ) -> WorkflowRow:
        if not name.strip():
            raise self._error("invalid_name", user_id=user_id)
        await asyncio.to_thread(self._validate_workflow, user_id, definition)
        workflow_id = new_ulid()
        await asyncio.to_thread(
            self._repo.create_workflow,
            workflow_id=workflow_id,
            user_id=user_id,
            name=name.strip(),
            definition=definition.model_dump(),
            enabled=enabled,
            next_run_at=self._next_schedule(definition),
        )
        return await asyncio.to_thread(self._owned_workflow, workflow_id, user_id)

    def _next_schedule(self, definition: WorkflowDefinition) -> int | None:
        return (
            next_occurrence(definition.schedule, timezone=self._timezone, after=now_ts())
            if definition.schedule
            else None
        )

    def _validate_workflow(self, user_id: int, definition: WorkflowDefinition) -> None:
        if definition.schedule:
            try:
                self._next_schedule(definition)
            except (ValueError, OctopError):
                raise self._error("invalid_schedule", user_id=user_id) from None
        for step in definition.steps:
            self._validate_task(
                user_id,
                TaskCreate(
                    agent_id=step.agent_id,
                    title=step.title,
                    prompt=step.prompt,
                    options=step.options,
                ),
            )

    async def update_workflow(
        self,
        user_id: int,
        workflow_id: str,
        *,
        name: str,
        definition: WorkflowDefinition,
        enabled: bool,
    ) -> WorkflowRow:
        previous = await asyncio.to_thread(self._owned_workflow, workflow_id, user_id)
        if not name.strip():
            raise self._error("invalid_name", user_id=user_id)
        await asyncio.to_thread(self._validate_workflow, user_id, definition)
        await asyncio.to_thread(
            self._repo.update_workflow,
            workflow_id,
            name=name.strip(),
            definition=definition.model_dump(),
            enabled=enabled,
            next_run_at=previous.next_run_at
            if WorkflowDefinition.model_validate_json(previous.definition_json).schedule
            == definition.schedule
            else self._next_schedule(definition),
        )
        return await asyncio.to_thread(self._owned_workflow, workflow_id, user_id)

    async def workflows(self, user_id: int) -> builtins.list[dict[str, Any]]:
        return [row.to_public() for row in await asyncio.to_thread(self._repo.workflows, user_id)]

    async def rotate_webhook(self, user_id: int, workflow_id: str, *, enabled: bool) -> str | None:
        await asyncio.to_thread(self._owned_workflow, workflow_id, user_id)
        token = secrets.token_urlsafe(32) if enabled else None
        digest = hashlib.sha256(token.encode()).hexdigest() if token else None
        await asyncio.to_thread(self._repo.set_webhook_hash, workflow_id, digest)
        return token

    async def trigger_webhook(
        self,
        workflow_id: str,
        token: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str | None = None,
    ) -> str:
        row = await asyncio.to_thread(self._repo.workflow, workflow_id)
        digest = hashlib.sha256(token.encode()).hexdigest()
        if row is None or not row.webhook_hash or not hmac.compare_digest(digest, row.webhook_hash):
            raise self._error("webhook_auth", status=401)
        calls = self._hook_calls[workflow_id]
        now = time.monotonic()
        while calls and calls[0] < now - 60:
            calls.popleft()
        if len(calls) >= 30:
            raise self._error("webhook_rate", user_id=row.user_id, status=429)
        calls.append(now)
        return await self.run_workflow(
            row.user_id,
            workflow_id,
            payload=payload,
            source="webhook",
            idempotency_key=idempotency_key,
        )

    async def run_workflow(
        self,
        user_id: int,
        workflow_id: str,
        *,
        payload: dict[str, Any] | None = None,
        source: str = "manual",
        idempotency_key: str | None = None,
    ) -> str:
        row = await asyncio.to_thread(self._owned_workflow, workflow_id, user_id)
        if not row.enabled and source != "manual":
            raise self._error("workflow_disabled", user_id=user_id, status=409)
        definition = WorkflowDefinition.model_validate_json(row.definition_json)
        await asyncio.to_thread(self._validate_workflow, user_id, definition)
        encoded = json.dumps(payload or {}, ensure_ascii=False)
        if len(encoded.encode()) > 32768:
            raise self._error("payload_large", user_id=user_id, status=413)
        if idempotency_key and (len(idempotency_key) > 200 or "\n" in idempotency_key):
            raise self._error("bad_idempotency_key", user_id=user_id)
        run_id = new_ulid()
        ids = {step.key: new_ulid() for step in definition.steps}
        tasks = []
        for step in definition.ordered_steps():
            prompt = step.prompt
            if payload and not step.depends_on:
                prompt += "\n\n" + json.dumps({"trigger_payload": payload}, ensure_ascii=False)
            step_options = step.options.model_dump(exclude_none=True)
            references = await self._prepare_attachments(
                user_id, step.agent_id, step.options.attachments
            )
            step_options["attachments"] = [
                item.model_dump(exclude_none=True) for item in references
            ]
            step_options["quiet"] = definition.quiet or step.options.quiet
            tasks.append(
                {
                    "task_id": ids[step.key],
                    "user_id": user_id,
                    "agent_id": step.agent_id,
                    "title": step.title,
                    "prompt": prompt,
                    "options": step_options,
                    "run_id": run_id,
                    "step_key": step.key,
                    "dependencies": [ids[key] for key in step.depends_on],
                }
            )
        existing = await asyncio.to_thread(
            self._repo.enqueue,
            tasks,
            run={
                "run_id": run_id,
                "workflow_id": workflow_id,
                "user_id": user_id,
                "name": row.name,
                "source": source,
                "definition": definition.model_dump(),
                "trigger_key": idempotency_key,
            },
        )
        self._wake.set()
        return existing or run_id

    async def runs(self, user_id: int) -> builtins.list[dict[str, Any]]:
        rows = await asyncio.to_thread(self._repo.runs, user_id)
        for row in rows:
            tasks = await asyncio.to_thread(self._repo.run_tasks, row["run_id"], user_id)
            row["tasks"] = [task.to_public(detail=False) for task in tasks]
            states = {task.state for task in tasks}
            row["state"] = (
                "completed"
                if states == {"completed"}
                else "failed"
                if states & {"failed", "cancelled", "interrupted"}
                else "running"
                if states & {"running", "waiting"}
                else "queued"
            )
        return rows

    async def _apply_failure_policy(self, run_id: str) -> None:
        workflow_id = await asyncio.to_thread(self._repo.run_workflow_id, run_id)
        row = await asyncio.to_thread(self._repo.workflow, workflow_id) if workflow_id else None
        if row:
            snapshot = await asyncio.to_thread(self._repo.run_definition, run_id)
            definition = (
                WorkflowDefinition.model_validate(snapshot)
                if snapshot.get("steps")
                else WorkflowDefinition.model_validate_json(row.definition_json)
            )
            if definition.schedule and definition.failure_policy == "pause":
                await asyncio.to_thread(
                    self._repo.pause_schedule, row.workflow_id, True, row.next_run_at
                )

    async def set_schedule_paused(self, user_id: int, workflow_id: str, paused: bool) -> None:
        row = await asyncio.to_thread(self._owned_workflow, workflow_id, user_id)
        definition = WorkflowDefinition.model_validate_json(row.definition_json)
        await asyncio.to_thread(
            self._repo.pause_schedule,
            workflow_id,
            paused,
            row.next_run_at if paused else self._next_schedule(definition),
        )
        self._wake.set()

    async def process_schedules(self, *, now: int | None = None) -> None:
        clock = now if now is not None else now_ts()
        for row in await asyncio.to_thread(self._repo.due_workflows, clock):
            definition = WorkflowDefinition.model_validate_json(row.definition_json)
            if row.next_run_at is None or not definition.schedule:
                continue
            due = row.next_run_at
            try:
                await self.run_workflow(
                    row.user_id,
                    row.workflow_id,
                    source="schedule",
                    idempotency_key=f"schedule:{due}",
                )
            except OctopError:
                await asyncio.to_thread(self._repo.pause_schedule, row.workflow_id, True, due)
                continue
            following = next_occurrence(
                definition.schedule, timezone=self._timezone, after=max(clock, due) + 1
            )
            await asyncio.to_thread(self._repo.advance_schedule, row.workflow_id, due, following)

    async def calendar(self, user_id: int) -> str:
        now = now_ts()
        end = now + 7 * 86400
        events: builtins.list[tuple[str, str, int]] = []
        for row in await asyncio.to_thread(self._repo.workflows, user_id):
            definition = WorkflowDefinition.model_validate_json(row.definition_json)
            if not row.enabled or row.schedule_paused or not definition.schedule:
                continue
            upcoming = next_occurrence(definition.schedule, timezone=self._timezone, after=now)
            while upcoming is not None and upcoming <= end and len(events) < 2000:
                events.append((row.workflow_id, row.name, upcoming))
                following = next_occurrence(
                    definition.schedule, timezone=self._timezone, after=upcoming + 1
                )
                if following is not None and following <= upcoming:
                    break
                upcoming = following
        return calendar_document(events, now=now)

    async def rotate_calendar(self, user_id: int, *, enabled: bool) -> str | None:
        key = f"task.calendar.owner.{user_id}"
        old = await asyncio.to_thread(self._repos.settings_repo.get, key)
        token = secrets.token_urlsafe(32) if enabled else None
        digest = hashlib.sha256(token.encode()).hexdigest() if token else ""
        await asyncio.to_thread(self._repos.settings_repo.set, key, digest)
        if old:
            await asyncio.to_thread(self._repos.settings_repo.delete, f"task.calendar.token.{old}")
        if digest:
            await asyncio.to_thread(
                self._repos.settings_repo.set, f"task.calendar.token.{digest}", str(user_id)
            )
        return token

    async def calendar_for_token(self, token: str) -> str:
        digest = hashlib.sha256(token.encode()).hexdigest()
        owner = await asyncio.to_thread(
            self._repos.settings_repo.get, f"task.calendar.token.{digest}"
        )
        if not owner or not owner.isdigit():
            raise self._error("calendar_auth", status=404)
        user_id = int(owner)
        expected = await asyncio.to_thread(
            self._repos.settings_repo.get, f"task.calendar.owner.{user_id}"
        )
        user = await asyncio.to_thread(self._repos.user_repo.get, user_id)
        if (
            not expected
            or not hmac.compare_digest(expected, digest)
            or user is None
            or user.disabled
            or not user_has_permission(_identity(user), "tasks")
        ):
            raise self._error("calendar_auth", status=404)
        return await self.calendar(user_id)

    async def _publish(self, row: TaskRow, *, notify: bool) -> None:
        with contextlib.suppress(Exception):
            await self._gateway.ws_hub.push_to_user(
                row.user_id,
                {
                    "type": "task.updated",
                    "task_id": row.task_id,
                    "task_attempt": row.attempt,
                    "agent_id": row.agent_id,
                    "thread_id": row.thread_id,
                    "status": row.state,
                    "notify": notify,
                },
            )

    async def _notify_result(self, row: TaskRow) -> None:
        if row.state in {"failed", "interrupted", "cancelled"}:
            from octop.infra.tasks.children import cancel_children

            await self._coordinator.stop_parent(row)
            await cancel_children(self, row)
        context = await asyncio.to_thread(self._repos.task_dispatch_repo.get, row.task_id)
        has_origin = bool(context and context.get("origin_thread_id"))
        if row.state in {"completed", "failed", "waiting", "cancelled", "interrupted"}:
            with contextlib.suppress(Exception):
                await self._return_result(row)
        if row.state == "completed":
            self._drop_binding(row)
        elif (
            row.state in {"failed", "cancelled", "interrupted"}
            and row.thread_id
            and row.attempt > 0
        ):
            self._bindings[(row.agent_id, row.user_id, row.thread_id)] = (row.task_id, row.attempt)
        if row.state not in {"completed", "failed", "waiting"}:
            await self._publish(row, notify=False)
            return
        announce = True
        if row.state == "completed":
            announce = not TaskOptions.model_validate_json(row.options_json).quiet
            if row.run_id:
                steps = await asyncio.to_thread(self._repo.run_tasks, row.run_id, row.user_id)
                announce = announce and all(step.state == "completed" for step in steps)
        # Origin delivery refreshes the original conversation and owns its notification.
        announce = announce and not has_origin
        if announce and row.thread_id:
            sessions = await asyncio.to_thread(
                self._gateway.thread_registry.sessions_for_thread, row.thread_id
            )
            session = next(
                (
                    item
                    for item in sessions
                    if item.user_id == row.user_id and item.agent_id == row.agent_id
                ),
                None,
            )
            if session is not None:
                locale = self._locales.get(row.user_id, DEFAULT_LOCALE)
                text = tr(f"tasks.notifications.{row.state}", locale, title=row.title)
                with contextlib.suppress(Exception):
                    await self._gateway.notify_dashboard_push(
                        session, row.agent_id, text, notify=False
                    )
        await self._publish(row, notify=announce)

    async def delete_workflow(self, user_id: int, workflow_id: str) -> None:
        await asyncio.to_thread(self._owned_workflow, workflow_id, user_id)
        await asyncio.to_thread(self._repo.delete_workflow, workflow_id)

    async def has_pending_tasks(self) -> bool:
        return await asyncio.to_thread(self._repo.pending_exists)

    async def admit_turn(self, message: InboundMessage) -> bool:
        """Authoritative last gate for a queued internal task continuation.

        The WS transport calls this before any model/tool work. Reject by
        raising, so the exact completion Future resolves as failed rather than
        allowing a zero-chunk initial task to be recorded as completed.
        """
        task_id = str((message.metadata or {}).get("task_id") or "")
        if not task_id:
            # A normal chat frame must not bypass a recovered Task's old Graph
            # checkpoint/approval by omitting internal Task metadata.
            subject = message.channel_subject.subject_id if message.channel_subject else ""
            thread_id = str((message.metadata or {}).get("thread_id") or "")
            if message.tenant_id and subject.isdecimal():
                binding = self._bindings.get((message.tenant_id, int(subject), thread_id))
                if binding is not None:
                    previous = await asyncio.to_thread(self._repo.get, binding[0])
                    if previous is not None and previous.state in {
                        "failed",
                        "cancelled",
                        "interrupted",
                    }:
                        raise self._error(
                            "recovery_requires_retry", user_id=previous.user_id, status=409
                        )
                    if previous is not None and previous.state in {"queued", "paused", "waiting"}:
                        raise self._error(
                            "invalid_transition", user_id=previous.user_id, status=409
                        )
                    if previous is not None and previous.state == "running":
                        context = await asyncio.to_thread(
                            self._repos.task_dispatch_repo.get, previous.task_id
                        )
                        phase = ((context or {}).get("coding_run") or {}).get("phase")
                        if phase in {"verifying", "pushed"}:
                            raise self._error(
                                "invalid_transition", user_id=previous.user_id, status=409
                            )
            return True
        completion = (message.metadata or {}).get("_octop_turn_completion")
        if isinstance(completion, asyncio.Future):
            self._continuations[task_id] = completion

            def remove_finished(future: asyncio.Future[dict[str, Any]]) -> None:
                if self._continuations.get(task_id) is future:
                    self._continuations.pop(task_id, None)

            completion.add_done_callback(remove_finished)
        row = await asyncio.to_thread(self._repo.get, task_id)
        subject = message.channel_subject.subject_id if message.channel_subject else ""
        thread_id = str((message.metadata or {}).get("thread_id") or "")
        if (
            row is None
            or row.state not in {"running", "waiting"}
            or row.agent_id != message.tenant_id
            or str(row.user_id) != subject
            or row.thread_id != thread_id
            or (message.metadata or {}).get("task_attempt") != row.attempt
        ):
            raise self._error("invalid_transition", status=409)
        await asyncio.to_thread(
            self._validate_task_policy,
            row.user_id,
            row.agent_id,
            row.thread_id,
            TaskOptions.model_validate_json(row.options_json),
        )

        return True

    def _background_completion(self, row: TaskRow) -> asyncio.Future[dict[str, Any]] | None:
        async def phase(state: str) -> None:
            current = await asyncio.to_thread(self._repo.get, row.task_id)
            if (
                current is None
                or current.attempt != row.attempt
                or current.state not in {"running", "waiting"}
            ):
                return
            if current.state != state:
                changed = await asyncio.to_thread(
                    self._repo.transition,
                    row.task_id,
                    expected={current.state},
                    expected_attempt=row.attempt,
                    state=state,
                    action="member_approval" if state == "waiting" else "member_resumed",
                )
                if changed:
                    updated = await asyncio.to_thread(self._repo.get, row.task_id)
                    if updated:
                        await self._notify_result(
                            updated
                        ) if state == "waiting" else await self._publish(updated, notify=False)

        return background_completion(
            row=row, agents=self._agents, gateway=self._gateway, on_phase=phase
        )

    async def resume_attempts(
        self, *, agent_id: str, user_id: int, thread_id: str
    ) -> dict[str, int]:
        rows = await asyncio.to_thread(self._repo.active_in_thread, agent_id, user_id, thread_id)
        return {row.task_id: row.attempt for row in rows}

    def task_binding(self, agent_id: str, user_id: int, thread_id: str) -> tuple[str, int] | None:
        return self._bindings.get((agent_id, user_id, thread_id))

    def _drop_binding(self, row: TaskRow) -> None:
        key = (row.agent_id, row.user_id, row.thread_id or "")
        if self._bindings.get(key) == (row.task_id, row.attempt):
            self._bindings.pop(key, None)

    async def bind_resume(
        self, *, agent_id: str, user_id: int, thread_id: str, pending: Any | None
    ) -> TaskResumeLease | None:
        if pending is None:
            if await asyncio.to_thread(self._repo.latest_in_thread, agent_id, user_id, thread_id):
                raise self._error("invalid_transition", user_id=user_id, status=409)
            return None
        if pending.status != "pending":
            raise self._error("invalid_transition", user_id=user_id, status=409)
        task_id = getattr(pending, "task_id", None)
        attempt = getattr(pending, "task_attempt", None)
        if not task_id:
            return None
        async with self._mutation_locks.setdefault(str(task_id), asyncio.Lock()):
            row = await asyncio.to_thread(self._owned_task, str(task_id), user_id)
            if (
                pending.status != "pending"
                or row.agent_id != agent_id
                or row.thread_id != thread_id
                or row.attempt != attempt
                or row.state not in {"running", "waiting"}
            ):
                raise self._error("invalid_transition", user_id=user_id, status=409)
            lease = TaskResumeLease(
                self, row.task_id, row.attempt, agent_id, user_id, thread_id, pending
            )
            self._resume_leases.setdefault(row.task_id, set()).add(lease)
            return lease

    async def _enter_resume(self, lease: TaskResumeLease) -> None:
        async with self._mutation_locks.setdefault(lease.task_id, asyncio.Lock()):
            row = await asyncio.to_thread(self._owned_task, lease.task_id, lease.user_id)
            if (
                lease.cancelled
                or lease.pending.status != "pending"
                or row.attempt != lease.attempt
                or row.agent_id != lease.agent_id
                or row.thread_id != lease.thread_id
                or row.state not in {"running", "waiting"}
            ):
                raise self._error("invalid_transition", user_id=lease.user_id, status=409)
            await asyncio.to_thread(
                self._validate_task_policy,
                row.user_id,
                row.agent_id,
                row.thread_id,
                TaskOptions.model_validate_json(row.options_json),
            )

    def _release_resume(self, lease: TaskResumeLease) -> None:
        leases = self._resume_leases.get(lease.task_id)
        if leases is not None:
            leases.discard(lease)
            if not leases:
                self._resume_leases.pop(lease.task_id, None)

    async def _prepare_attachments(
        self,
        user_id: int,
        agent_id: str,
        references: builtins.list[TaskAttachment],
        *,
        check_expiry: bool = True,
    ) -> builtins.list[TaskAttachment]:
        await asyncio.to_thread(self._owned_agent, agent_id, user_id)
        try:
            checked = await authorize_uploads(
                self._repos,
                user_id=user_id,
                agent_id=agent_id,
                references=references,
                check_expiry=check_expiry,
            )
            workspace = (
                await asyncio.to_thread(self._agents.workspace_for_agent, agent_id)
                if checked
                else None
            )
            return await validate_references(workspace, checked)
        except TaskAttachmentError as exc:
            raise self._error(exc.reason, user_id=user_id) from None
