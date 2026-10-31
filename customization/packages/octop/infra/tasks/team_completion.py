"""Wait for delegated inbox jobs, including member approvals and host wrap-up."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from octop_harness.teams.util import derive_peer_thread_id

from octop.infra.db.repos.tasks import TaskRow

_TERMINAL = {"done", "failed", "cancelled"}


class TeamCompletion(asyncio.Future[dict[str, Any]]):
    worker: asyncio.Task[None] | None = None


async def close_background(completion: asyncio.Future[dict[str, Any]] | None) -> None:
    if isinstance(completion, TeamCompletion) and completion.worker is not None:
        completion.cancel()
        completion.worker.cancel()
        await asyncio.gather(completion.worker, return_exceptions=True)


def _inbox(agents: Any) -> Any:
    return getattr(getattr(getattr(agents, "harness_manager", None), "team", None), "inbox", None)


def scoped_jobs(inbox: Any, row: TaskRow) -> list[Any]:
    if inbox is None:
        return []
    return [
        job
        for job in inbox.list(source=row.agent_id)
        if str(job.user_id) == str(row.user_id) and job.source_thread_id == row.thread_id
    ]


def cancel_scoped_jobs(agents: Any, row: TaskRow) -> None:
    inbox = _inbox(agents)
    for job in scoped_jobs(inbox, row):
        if job.status not in _TERMINAL:
            phase = job.status
            inbox.cancel(job.id)
            if row.thread_id:
                agents.cancel_stream(
                    job.target_agent_id, derive_peer_thread_id(row.thread_id, job.target_agent_id)
                )
            # The member path catches cancellation and records a terminal reply;
            # the host reply path must unwind via cancel_stream to retain cleanup.
            task = getattr(inbox, "_tasks", {}).get(job.id)
            if phase != "replying" and isinstance(task, asyncio.Task) and not task.done():
                task.cancel()


def background_completion(
    *, row: TaskRow, agents: Any, gateway: Any, on_phase: Callable[[str], Awaitable[None]]
) -> asyncio.Future[dict[str, Any]] | None:
    inbox = _inbox(agents)
    jobs = scoped_jobs(inbox, row)
    tasks = getattr(inbox, "_tasks", {}) if inbox is not None else {}
    if not any(
        job.status not in _TERMINAL or (job.id in tasks and not tasks[job.id].done())
        for job in jobs
    ):
        return None
    completion = TeamCompletion()
    tracked = {job.id: job for job in jobs}
    futures: set[asyncio.Task[Any]] = set()
    pieces: list[str] = []
    last_phase = ""
    connection_id = f"task-background:{row.task_id}"

    async def collect(frame: dict[str, Any]) -> None:
        if frame.get("type") == "token":
            pieces.append(str(frame.get("content") or ""))

    gateway.ws_hub.register(connection_id, collect)
    gateway.ws_hub.subscribe(row.thread_id or "", connection_id)

    async def wait() -> None:
        nonlocal last_phase
        try:
            while True:
                current = scoped_jobs(inbox, row)
                tracked.update({job.id: job for job in current})
                tasks = getattr(inbox, "_tasks", {})
                futures.update(
                    task
                    for key, task in tasks.items()
                    if key in tracked and isinstance(task, asyncio.Task)
                )
                live = any(job.status not in _TERMINAL for job in current) or any(
                    not task.done() for task in futures
                )
                if not live:
                    break
                pending = gateway.processor.hitl_coordinator.store.pending_thread_ids(
                    agent_id=row.agent_id, user_id=row.user_id
                )
                phase = "waiting" if row.thread_id in pending else "running"
                if phase != last_phase:
                    last_phase = phase
                    await on_phase(phase)
                await asyncio.sleep(0.05)
            if not completion.done():
                completion.set_result(
                    {
                        "failed": any(
                            job.status in {"failed", "cancelled"} for job in tracked.values()
                        ),
                        "paused": False,
                        "output": "".join(pieces)[-128000:],
                    }
                )
        except asyncio.CancelledError:
            cancel_scoped_jobs(agents, row)
            if not completion.done():
                completion.cancel()
            raise
        except Exception:
            if not completion.done():
                completion.set_result(
                    {"failed": True, "paused": False, "output": "".join(pieces)[-128000:]}
                )
        finally:
            gateway.ws_hub.unregister(connection_id)

    worker = asyncio.create_task(wait(), name=f"task-team-barrier-{row.task_id}")
    completion.worker = worker

    def stop(done: asyncio.Future[dict[str, Any]]) -> None:
        if done.cancelled():
            worker.cancel()

    completion.add_done_callback(stop)
    return completion
