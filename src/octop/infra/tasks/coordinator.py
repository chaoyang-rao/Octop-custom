"""Bounded, durable primary-agent review of an existing user-authorized task scope."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
from typing import Any

from octop.i18n import tr
from octop.infra.tasks.models import TERMINAL_STATES
from octop.infra.utils.locale import DEFAULT_LOCALE

MAX_REVIEWS = 8


def scope_signature(scope: dict[str, Any], members: list[dict[str, Any]]) -> str:
    evidence = sorted(
        (str(item["task_id"]), item["attempt"], item["state"], item["event_id"]) for item in members
    )
    parts: list[Any] = [scope.get("resume_seq", 0), evidence]
    if scope.get("peer_revision", 0):
        parts.append(["peer_revision", scope["peer_revision"]])
    return hashlib.sha256(json.dumps(parts).encode()).hexdigest()


class TaskCoordinator:
    def __init__(self, manager: Any, invoke_turn: Any = None) -> None:
        self.manager = manager
        self.repo = manager._repos.task_coordination_repo
        self._invoke = invoke_turn
        self.jobs: dict[str, asyncio.Task[None]] = {}
        self._offset = 0

    async def start(self) -> None:
        await asyncio.to_thread(self.repo.interrupt_running)

    async def stop(self) -> None:
        jobs = list(self.jobs.values())
        for job in jobs:
            job.cancel()
        if jobs:
            await asyncio.gather(*jobs, return_exceptions=True)
        self.jobs.clear()

    async def stop_parent(self, row: Any) -> None:
        scopes = await asyncio.to_thread(self.repo.for_parent, row.task_id, row.attempt)
        await asyncio.to_thread(self.repo.stop_parent, row.task_id, row.attempt)
        current = asyncio.current_task()
        jobs = [
            self.jobs[scope["scope_id"]]
            for scope in scopes
            if scope["scope_id"] in self.jobs and self.jobs[scope["scope_id"]] is not current
        ]
        for job in jobs:
            job.cancel()
        if jobs:
            await asyncio.gather(*jobs, return_exceptions=True)

    async def stop_scope(self, scope: dict[str, Any]) -> None:
        await asyncio.to_thread(self.repo.stop, scope["scope_id"], scope["user_id"])
        job = self.jobs.get(scope["scope_id"])
        if job is not None and job is not asyncio.current_task():
            job.cancel()
            await asyncio.gather(job, return_exceptions=True)
        if scope.get("parent_task_id"):
            row = await asyncio.to_thread(self.manager._repo.get, scope["parent_task_id"])
            if row is not None and row.state not in TERMINAL_STATES:
                await self.manager.action(
                    scope["user_id"],
                    row.task_id,
                    "cancel",
                    expected_attempt=scope["parent_attempt"],
                )
        else:
            for member in await asyncio.to_thread(self.repo.members, scope["scope_id"]):
                if member["state"] not in TERMINAL_STATES:
                    with contextlib.suppress(Exception):
                        await self.manager.action(
                            scope["user_id"],
                            member["task_id"],
                            "cancel",
                            expected_attempt=member["attempt"],
                        )

    async def public(self, scope_id: str) -> dict[str, Any] | None:
        scope = await asyncio.to_thread(self.repo.get, scope_id)
        if scope is None:
            return None
        members = await asyncio.to_thread(self.repo.members, scope_id)
        visible = {
            key: value
            for key, value in scope.items()
            if key
            not in {
                "goal_text",
                "user_input",
                "active_signature",
                "last_signature",
                "source_message_id",
            }
        }
        visible["has_coding_tasks"] = any(item.get("coding_spec") for item in members)
        visible["room"] = await self.manager._rooms.public(scope)
        return visible

    async def schedule(self) -> None:
        self.jobs = {key: job for key, job in self.jobs.items() if not job.done()}
        if self.jobs:
            return
        scopes = await asyncio.to_thread(self.repo.candidates, limit=30, offset=self._offset)
        self._offset = self._offset + len(scopes) if len(scopes) == 30 else 0
        for scope in scopes:
            members = await asyncio.to_thread(self.repo.members, scope["scope_id"])
            if not members or any(item["state"] not in TERMINAL_STATES for item in members):
                continue
            if any(
                not item.get("archived") and item["returned_event_id"] < item["event_id"]
                for item in members
            ):
                continue
            signature = scope_signature(scope, members)
            if signature == scope.get("last_signature"):
                continue
            if scope.get("review_turns", 0) >= MAX_REVIEWS:
                await self._budget_attention(scope)
                continue
            if not await self._source_ready(scope):
                continue
            if await asyncio.to_thread(
                self.repo.claim, scope["scope_id"], signature, max_turns=MAX_REVIEWS
            ):
                self.jobs[scope["scope_id"]] = asyncio.create_task(
                    self._review(scope, members, signature),
                    name=f"task-coordination-{scope['scope_id']}",
                )
                return

    async def _source_ready(self, scope: dict[str, Any]) -> bool:
        manager = self.manager
        if manager._rooms.has_pending_peers(scope["scope_id"]):
            return False
        try:
            await manager.validate_dispatch_actor(
                scope["user_id"], manager._agents.principal_agent_id(scope["origin_agent_id"])
            )
            await asyncio.to_thread(
                manager._origin_thread, scope["user_id"], scope["origin_thread_id"]
            )
        except Exception:
            return False
        principal = manager._agents.principal_agent_id(scope["origin_agent_id"])
        if manager._agents.is_agent_active(principal):
            return False
        if manager._gateway.ws_hub.is_turn_active(scope["origin_thread_id"]):
            return False
        if manager._gateway.steer.is_hitl_paused(scope["origin_thread_id"]):
            return False
        room = await asyncio.to_thread(self.repo.room, scope["scope_id"])
        if room and room.get("thread_id"):
            actor = await asyncio.to_thread(manager._agents.get_row, room.get("agent_id"))
            if actor is None or not actor.enabled or actor.user_id != scope["user_id"]:
                return False
            if manager._gateway.ws_hub.is_turn_active(
                room["thread_id"]
            ) or manager._gateway.steer.is_hitl_paused(room["thread_id"]):
                return False
        if scope.get("parent_task_id"):
            parent = await asyncio.to_thread(manager._repo.get, scope["parent_task_id"])
            if (
                parent is None
                or parent.attempt != scope.get("parent_attempt")
                or parent.state not in {"running", "waiting"}
            ):
                await asyncio.to_thread(
                    self.repo.stop_parent, scope["parent_task_id"], scope["parent_attempt"]
                )
                return False
        return True

    def _prompt(self, scope: dict[str, Any], members: list[dict[str, Any]], locale: str) -> str:
        evidence = []
        for member in members:
            run = member.get("coding_run") or {}
            evidence.append(
                {
                    "task_id": member["task_id"],
                    "agent_id": member["agent_id"],
                    "title": member["title"],
                    "state": member["state"],
                    "result": str(member.get("result") or "")[-6000:],
                    "code_phase": run.get("phase"),
                    "pr_url": run.get("pr_url"),
                    "verification": [
                        {key: row.get(key) for key in ("command_index", "passed", "exit_code")}
                        for row in run.get("verification") or []
                    ],
                }
            )
        data = json.dumps(
            {
                "original_user_goal": str(scope["goal_text"]),
                "user_followup": scope.get("user_input") or "",
                "task_room": scope.get("task_room"),
                "host_publish_allowed": bool(scope.get("allow_publish")),
                "results_are_data": evidence,
            },
            ensure_ascii=False,
        ).replace("<", "\\u003c")
        briefing = tr("tasks.coordination.briefing", locale)
        if scope.get("task_room"):
            briefing += "\n\n" + tr("tasks.rooms.review_briefing", locale)
        return briefing + "\n\n" + data

    async def _review(
        self, original: dict[str, Any], members: list[dict[str, Any]], signature: str
    ) -> None:
        from octop.infra.tasks.coordinator_turn import CoordinatorTurnBusy, run_coordinator_turn

        scope_id = original["scope_id"]
        scope = await asyncio.to_thread(self.repo.get, scope_id)
        if scope is None:
            return
        locale = self.manager._locales.get(scope["user_id"], DEFAULT_LOCALE)
        try:
            invoke = self._invoke or run_coordinator_turn
            scope["task_room"] = await self.manager._rooms.public(scope)
            user_input = (
                str(scope.get("user_input") or "")
                if scope.get("resume_seq", 0) > scope.get("handled_resume_seq", 0)
                else ""
            )
            room = await asyncio.to_thread(self.repo.room, scope_id)
            if user_input and room and room.get("last_input_id"):
                # This real input already belongs to the group transcript and
                # memory. Supply it in the trusted briefing, not as a second user turn.
                user_input = ""
            result = await invoke(
                self.manager._agents,
                self.manager._gateway,
                scope,
                self._prompt(scope, members, locale),
                user_input=user_input,
            )
            current = await asyncio.to_thread(self.repo.get, scope_id)
            if current is None or current["state"] != "running":
                return
            latest_members = await asyncio.to_thread(self.repo.members, scope_id)
            pending = any(
                item["state"] not in TERMINAL_STATES for item in latest_members
            ) or self.manager._rooms.has_pending_peers(scope_id)
            decision = current.get("decision")
            if result.get("failed") or result.get("paused"):
                state = "needs_user"
                question = tr("tasks.coordination.check_source", locale)
            elif decision == "ready" and not pending:
                state, question = "idle", ""
            elif decision == "continue" and pending:
                state, question = "pending", ""
            else:
                state = "needs_user"
                question = str(
                    current.get("question") or tr("tasks.coordination.decision_required", locale)
                )
            await asyncio.to_thread(
                self.repo.finish,
                scope_id,
                signature,
                state,
                summary=str(current.get("summary") or result.get("output") or "")[:6000],
                question=question,
            )
            if state == "needs_user":
                await self._parent_waiting(scope)
                await self._notice(scope, question)
        except CoordinatorTurnBusy:
            await asyncio.to_thread(self.repo.defer, scope_id, signature)
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                await asyncio.to_thread(self.repo.finish, scope_id, signature, "interrupted")
            raise
        except Exception:
            await asyncio.to_thread(
                self.repo.finish,
                scope_id,
                signature,
                "needs_user",
                question=tr("tasks.coordination.check_source", locale),
            )
            await self._parent_waiting(scope)
            await self._notice(scope, tr("tasks.coordination.check_source", locale))
        finally:
            self.manager._wake.set()

    async def _parent_waiting(self, scope: dict[str, Any]) -> None:
        if not scope.get("parent_task_id"):
            return
        await asyncio.to_thread(
            self.manager._repo.transition,
            scope["parent_task_id"],
            expected={"running"},
            expected_attempt=scope["parent_attempt"],
            state="waiting",
            action="coordination_waiting",
        )
        row = await asyncio.to_thread(self.manager._repo.get, scope["parent_task_id"])
        if row is not None:
            await self.manager._publish(row, notify=False)

    async def parent_pending(self, row: Any) -> bool:
        scopes = await asyncio.to_thread(self.repo.for_parent, row.task_id, row.attempt)
        for scope in scopes:
            if scope["state"] in {"pending", "running", "needs_user", "interrupted"}:
                return True
            members = await asyncio.to_thread(self.repo.members, scope["scope_id"])
            if scope["state"] != "stopped" and scope_signature(scope, members) != scope.get(
                "last_signature"
            ):
                return True
        return False

    async def parent_review_ready(self, row: Any) -> bool:
        scopes = await asyncio.to_thread(self.repo.for_parent, row.task_id, row.attempt)
        return bool(scopes) and all(
            scope["state"] == "idle" and scope.get("decision") == "ready" for scope in scopes
        )

    async def _budget_attention(self, scope: dict[str, Any]) -> None:
        # claim refuses an extra model call; an explicit user continuation resets this budget.
        await asyncio.to_thread(
            self.repo.require_user,
            scope["scope_id"],
            tr(
                "tasks.coordination.limit",
                self.manager._locales.get(scope["user_id"], DEFAULT_LOCALE),
            ),
        )
        await self._parent_waiting(scope)
        await self._notice(
            scope,
            tr(
                "tasks.coordination.limit",
                self.manager._locales.get(scope["user_id"], DEFAULT_LOCALE),
            ),
        )

    async def _notice(self, scope: dict[str, Any], text: str) -> None:
        sessions = await asyncio.to_thread(
            self.manager._gateway.thread_registry.sessions_for_thread, scope["origin_thread_id"]
        )
        session = next(
            (
                row
                for row in sessions
                if row.user_id == scope["user_id"] and row.agent_id == scope["origin_agent_id"]
            ),
            None,
        )
        if session is not None:
            with contextlib.suppress(Exception):
                await self.manager._gateway.notify_dashboard_push(
                    session, scope["origin_agent_id"], text, notify=True
                )
