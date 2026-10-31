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

    def replace_repos(self, repos: RepoBundle) -> None:
        if self._running:
            raise RuntimeError("stop task manager before rebinding persistence")
        self._repos = repos
        self._repo = repos.task_repo

    async def enqueue(self, user_id: int, body: TaskCreate) -> TaskRow:
        await asyncio.to_thread(self._validate_task, user_id, body)
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
        await asyncio.to_thread(
            self._repo.enqueue,
            [
                {
                    "task_id": task_id,
                    "user_id": user_id,
                    "agent_id": body.agent_id,
                    "thread_id": body.thread_id,
                    "title": body.title,
                    "prompt": body.prompt,
                    "options": options.model_dump(exclude_none=True),
                }
            ],
        )
        self._wake.set()
        row = await asyncio.to_thread(self._owned_task, task_id, user_id)
        await self._publish(row, notify=False)
        return row

    def _validate_task(self, user_id: int, body: TaskCreate) -> None:
        self._validate_task_policy(user_id, body.agent_id, body.thread_id, body.options)

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
        return [row.to_public(detail=False) for row in rows]

    async def detail(self, user_id: int, task_id: str) -> dict[str, Any]:
        row = await asyncio.to_thread(self._owned_task, task_id, user_id)
        result = row.to_public()
        result["events"] = await asyncio.to_thread(self._repo.events, task_id)
        return result

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
            if len(self._running) >= 2:
                break
            if row.state != "queued" or self._agents.is_agent_active(row.agent_id):
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
            if claimed:
                await self._publish(claimed, notify=False)
            self._running[row.task_id] = asyncio.create_task(
                self._execute(row.task_id), name=f"task-{row.task_id}"
            )

    async def _execute(self, task_id: str) -> None:
        row = await asyncio.to_thread(self._repo.get, task_id)
        if row is None:
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
            state = "failed" if failed else "waiting" if waiting else "completed"
            await asyncio.to_thread(
                self._repo.transition,
                task_id,
                expected={"running", "waiting"},
                state=state,
                action=state,
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
        except Exception:
            # Do not persist raw network exceptions, tool arguments or credentials.
            await asyncio.to_thread(
                self._repo.transition,
                task_id,
                expected={"running"},
                state="failed",
                action="failed",
                fields={"error_code": "execution_failed", "finished_at": now_ts()},
            )
        finally:
            latest = await asyncio.to_thread(self._repo.get, task_id)
            if latest and latest.state in {"failed", "interrupted"} and latest.run_id:
                await self._apply_failure_policy(latest.run_id)
            if latest:
                await self._notify_result(latest)
            self._wake.set()

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
            state = (
                "running"
                if continuation is not None
                else "failed"
                if failed
                else "waiting"
                if paused
                else "completed"
            )
            changed = await asyncio.to_thread(
                self._repo.transition,
                row.task_id,
                expected={row.state},
                expected_attempt=row.attempt,
                state=state,
                action="approval_resumed",
                fields={
                    "finished_at": None if state in {"running", "waiting"} else now_ts(),
                    "error_code": "execution_failed" if failed and state == "failed" else None,
                },
                append_result=output,
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
                if failed and row.run_id:
                    await self._apply_failure_policy(row.run_id)
                updated = await asyncio.to_thread(self._repo.get, row.task_id)
                if updated:
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
                expected={"running"},
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
