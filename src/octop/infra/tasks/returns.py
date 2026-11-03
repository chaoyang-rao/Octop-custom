"""Return persisted expert results to an idle, owned originating conversation."""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any
from urllib.parse import quote, urlsplit

from langchain_core.messages import AIMessage

from octop.i18n import tr
from octop.infra.agents.teams.service import is_team_agent
from octop.infra.db.repos.tasks import TaskRow
from octop.infra.db.services import RepoBundle
from octop.infra.gateway.process.message_keys import CHECKPOINT_TS_KEY
from octop.infra.gateway.threads import ThreadRegistry
from octop.infra.history.external import ExternalHistoryBusy, append_external_message
from octop.infra.tasks.models import TaskOptions
from octop.infra.users.identity import User
from octop.infra.users.permissions import user_has_permission
from octop.infra.utils.locale import DEFAULT_LOCALE

_RETURN_STATES = {"completed", "failed", "interrupted", "cancelled", "waiting"}
_PR_PATH = re.compile(r"/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/pull/[1-9][0-9]*/?")


def _pull_request(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) > 500:
        return None
    try:
        url = urlsplit(value)
    except ValueError:
        return None
    return (
        value
        if url.scheme == "https"
        and url.netloc.lower() == "github.com"
        and not url.query
        and not url.fragment
        and _PR_PATH.fullmatch(url.path)
        else None
    )


class TaskReturnService:
    def __init__(self, repos: RepoBundle, gateway: Any, agents: Any) -> None:
        self.repos = repos
        self.gateway = gateway
        self.agents = agents

    def _speaker(self, row: TaskRow) -> Any:
        principal = self.agents.principal_agent_id(row.agent_id)
        speaker = self.agents.get_row(principal)
        return (
            speaker
            if speaker is not None and speaker.user_id == row.user_id and not is_team_agent(speaker)
            else None
        )

    def _owned_origin(self, row: TaskRow, context: dict[str, Any]) -> tuple[Any, Any] | None:
        user = self.repos.user_repo.get(row.user_id)
        origin = self.repos.thread_repo.get(context.get("origin_thread_id") or "")
        agent = self.repos.agent_repo.get(context.get("origin_agent_id") or "")
        worker = self.repos.agent_repo.get(row.agent_id)
        if (
            user is None
            or user.disabled
            or origin is None
            or agent is None
            or worker is None
            or origin.user_id != row.user_id
            or origin.agent_id != agent.agent_id
            or agent.user_id != row.user_id
            or worker.user_id != row.user_id
            or self._speaker(row) is None
        ):
            return None
        identity = User(
            id=user.id,
            username=user.username,
            role=user.role,
            display_name=user.display_name,
            locale=user.locale,
            permissions=list(user.permissions),
        )
        return (origin, user) if user_has_permission(identity, "tasks") else None

    def _text(self, row: TaskRow, context: dict[str, Any], locale: str) -> tuple[str, str, str]:
        speaker = self._speaker(row)
        if speaker is None:
            raise PermissionError("The executing expert is no longer authorized")
        heading = tr(f"tasks.returns.{row.state}", locale, name=speaker.name, title=row.title)
        links = [tr("tasks.returns.task_link", locale, url="/task-queue")]
        if context.get("scope_id"):
            room = self.repos.task_coordination_repo.room(context["scope_id"])
            if room and room.get("agent_id") and room.get("thread_id"):
                destination = self.repos.thread_repo.get(room["thread_id"])
                if (
                    destination is not None
                    and destination.user_id == row.user_id
                    and destination.agent_id == room["agent_id"]
                ):
                    from octop.infra.tasks.rooms import room_path

                    links.insert(0, tr("tasks.rooms.link", locale, url=room_path(room)))
        if row.thread_id:
            path = f"/chat/{quote(row.agent_id, safe='')}/{quote(row.thread_id, safe='')}"
            links.insert(0, tr("tasks.returns.execution_link", locale, url=path))
        pr = _pull_request((context.get("coding_run") or {}).get("pr_url"))
        if pr is not None:
            links.append(tr("tasks.returns.pull_request_link", locale, url=pr))
        footer = "\n".join(links)
        allowance = max(0, 6000 - len(heading) - len(footer) - 4)
        # Team output may concatenate several members' replies. Return the
        # coordinator's status and links, never re-author their text as its own.
        result = row.result.strip() if speaker.agent_id == row.agent_id else ""
        if len(result) > allowance:
            notice = tr("tasks.returns.truncated", locale)
            result = result[: max(0, allowance - len(notice) - 1)] + "\n" + notice
        return (
            "\n\n".join(part for part in (heading, result, footer) if part),
            heading,
            speaker.agent_id,
        )

    async def _ack(self, row: TaskRow, context: dict[str, Any]) -> bool:
        return await asyncio.to_thread(
            self.repos.task_dispatch_repo.mark_returned,
            row.task_id,
            row.attempt,
            state=row.state,
            event_id=int(context["current_event_id"]),
            expected_attempt=row.attempt,
        )

    async def deliver(self, row: TaskRow) -> bool:
        """Acquire only an immediately available source transport, then write safely."""
        current = await asyncio.to_thread(self.repos.task_repo.get, row.task_id)
        context = await asyncio.to_thread(self.repos.task_dispatch_repo.get, row.task_id)
        if current is None:
            return True
        if context is None:
            return False
        if current.archived or current.state not in _RETURN_STATES:
            return True
        if int(context["returned_event_id"]) >= int(context["current_event_id"]):
            return True
        owned = await asyncio.to_thread(self._owned_origin, current, context)
        if owned is None:
            return await self._ack(current, context)
        origin, _user = owned
        sessions = await asyncio.to_thread(
            self.gateway.thread_registry.sessions_for_thread, origin.thread_id
        )
        session = next(
            (
                item
                for item in sessions
                if item.user_id == current.user_id and item.agent_id == origin.agent_id
            ),
            None,
        )
        if session is None:
            return False
        if self.gateway.ws_hub.is_turn_active(
            origin.thread_id
        ) or self.gateway.steer.is_hitl_paused(origin.thread_id):
            return False
        started = asyncio.Event()
        admission_open = True
        outcome = False

        async def operation() -> None:
            nonlocal outcome
            if not admission_open:
                return
            started.set()
            outcome = await self._deliver_locked(current, origin.thread_id)

        async def routed() -> bool:
            if session.channel_type == ThreadRegistry.CHANNEL_DASHBOARD:
                manager = self.gateway.channel_manager
                if manager is None:
                    return False
                await manager.run_in_session(
                    self.gateway.dashboard_channel_id, f"thread:{origin.thread_id}", operation
                )
            else:
                await self.gateway.run_in_session(origin.agent_id, session.session_key, operation)
            return outcome

        job = asyncio.create_task(routed())
        waiting = asyncio.create_task(started.wait())
        try:
            await asyncio.wait({job, waiting}, timeout=0.1, return_when=asyncio.FIRST_COMPLETED)
            if job.done():
                return job.result()
            if started.is_set():
                return await asyncio.shield(job)
            # These two synchronous operations close the admission race before
            # yielding. A late lock grant cannot start any history I/O.
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
        except (ValueError, RuntimeError, OSError):
            return False
        finally:
            waiting.cancel()
            await asyncio.gather(waiting, return_exceptions=True)

    async def _deliver_locked(self, row: TaskRow, expected_origin: str) -> bool:
        """True means delivered/dropped/already handled; False means retry later."""
        current = await asyncio.to_thread(self.repos.task_repo.get, row.task_id)
        if current is None:
            return True
        row = current
        context = await asyncio.to_thread(self.repos.task_dispatch_repo.get, row.task_id)
        if context is None:
            return False
        if row.archived:
            return True
        if row.state not in _RETURN_STATES:
            return True
        if int(context["returned_event_id"]) >= int(context["current_event_id"]):
            return True
        owned = await asyncio.to_thread(self._owned_origin, row, context)
        if owned is None:
            return await self._ack(row, context)
        origin, user = owned
        if origin.thread_id != expected_origin:
            return False
        sessions = await asyncio.to_thread(
            self.gateway.thread_registry.sessions_for_thread, origin.thread_id
        )
        session = next(
            (
                item
                for item in sessions
                if item.user_id == row.user_id and item.agent_id == origin.agent_id
            ),
            None,
        )
        if session is None:
            return False
        principal = await asyncio.to_thread(self.agents.principal_agent_id, origin.agent_id)
        actual = await asyncio.to_thread(self.repos.agent_repo.get, principal)
        if actual is None or actual.user_id != row.user_id:
            return await self._ack(row, context)
        if self.gateway.ws_hub.is_turn_active(
            origin.thread_id
        ) or self.gateway.steer.is_hitl_paused(origin.thread_id):
            return False
        if not self.agents.try_begin_history_backfill(principal):
            return False
        try:
            expected_speaker: str | None = None

            async def authorize() -> None:
                if await asyncio.to_thread(self._owned_origin, row, context) is None:
                    raise PermissionError("The originating conversation is no longer authorized")
                if self.gateway.ws_hub.is_turn_active(
                    origin.thread_id
                ) or self.gateway.steer.is_hitl_paused(origin.thread_id):
                    raise ExternalHistoryBusy("The originating conversation is busy")
                latest = await asyncio.to_thread(self.repos.task_repo.get, row.task_id)
                dispatch = await asyncio.to_thread(self.repos.task_dispatch_repo.get, row.task_id)
                if (
                    latest is None
                    or latest.archived
                    or latest.attempt != row.attempt
                    or latest.state != row.state
                    or dispatch is None
                    or dispatch["current_event_id"] != context["current_event_id"]
                ):
                    raise ExternalHistoryBusy("The task changed before its result was persisted")
                if (
                    await asyncio.to_thread(self.agents.principal_agent_id, origin.agent_id)
                    != principal
                ):
                    raise ExternalHistoryBusy("The originating principal changed")
                speaker = await asyncio.to_thread(self._speaker, row)
                if speaker is None:
                    raise PermissionError("The executing expert is no longer authorized")
                if expected_speaker is not None and speaker.agent_id != expected_speaker:
                    raise ExternalHistoryBusy("The executing principal changed")

            await authorize()
            text, heading, expected_speaker = await asyncio.to_thread(
                self._text, row, context, user.locale or DEFAULT_LOCALE
            )
            event_id = int(context["current_event_id"])
            message = AIMessage(
                id=f"task-return:{row.task_id}:{event_id}",
                content=text,
                additional_kwargs={
                    CHECKPOINT_TS_KEY: int(time.time() * 1000),
                    "speaker_agent_id": expected_speaker,
                    "octop_task_return": {
                        "task_id": row.task_id,
                        "event_id": event_id,
                        "executor_agent_id": row.agent_id,
                        "data_only": True,
                    },
                },
            )
            archive = getattr(
                self.agents, "history_archive", getattr(self.agents, "_history_archive", None)
            )
            await append_external_message(
                archive=archive,
                harness=self.agents.get_agent(principal),
                agent_id=origin.agent_id,
                thread_id=origin.thread_id,
                message=message,
                projection=self.repos.thread_message_repo,
                before_write=authorize,
            )
            quiet_success = (
                row.state == "completed" and TaskOptions.model_validate_json(row.options_json).quiet
            )
            await self.gateway.notify_dashboard_push(
                session,
                origin.agent_id,
                heading[:300],
                notify=not quiet_success,
                toast=not quiet_success,
            )
            return await self._ack(row, context)
        except PermissionError:
            return await self._ack(row, context)
        except (ExternalHistoryBusy, ValueError, RuntimeError, OSError):
            return False
        finally:
            self.agents.end_history_backfill(principal)
