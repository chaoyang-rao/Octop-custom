"""Join durable expert children without charging a coordinating parent a slot."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from octop.i18n import tr
from octop.infra.db.repos._base import now_ts
from octop.infra.db.repos.tasks import TaskRow
from octop.infra.tasks.models import TERMINAL_STATES
from octop.infra.tasks.team_completion import TeamCompletion, cancel_scoped_jobs
from octop.infra.utils.locale import DEFAULT_LOCALE

_ACTIVE = {"queued", "paused", "running", "waiting"}
_POLL_SECONDS = 0.5
_OUTPUT_LIMIT = 12000


async def _snapshot(manager: Any, row: TaskRow) -> dict[str, TaskRow | None]:
    def read() -> dict[str, TaskRow | None]:
        ids = manager._repos.task_dispatch_repo.children(row.task_id, row.attempt)
        return {
            child_id: child
            if (child := manager._repo.get(child_id)) is not None and child.user_id == row.user_id
            else None
            for child_id in ids
        }

    return await asyncio.to_thread(read)


def _summary(
    manager: Any, row: TaskRow, children: dict[str, TaskRow | None], *, review_ready: bool = False
) -> str:
    if not children:
        return ""
    locale = manager._locales.get(row.user_id, DEFAULT_LOCALE)
    failed = not review_ready and any(
        child is None or child.state != "completed" for child in children.values()
    )
    text = tr(
        "tasks.children.failed" if failed else "tasks.children.summary", locale, count=len(children)
    )
    for child_id, child in children.items():
        if child is None:
            block = f"\n\n[{child_id}]\n{tr('tasks.children.failed', locale)}"
        else:
            result = child.result[:1500]
            if len(child.result) > 1500:
                result += "…"
            if not result and child.state != "completed":
                result = tr("tasks.children.failed", locale)
            block = f"\n\n[{child.title[:200]} · {child_id}]\n{result}"
        remaining = _OUTPUT_LIMIT - len(text)
        if len(block) > remaining:
            return (text + block)[: _OUTPUT_LIMIT - 1] + "…"
        text += block
    return text


async def _cancel_tree(
    manager: Any, row: TaskRow, *, observed: dict[str, TaskRow | None] | None = None
) -> None:
    pending = [row]
    seen = {row.task_id}
    stopped: set[asyncio.Task[Any]] = set()
    while pending:
        parent = pending.pop()
        children = await _snapshot(manager, parent)
        for child_id, snapshot in children.items():
            if snapshot is None or child_id in seen:
                continue
            seen.add(child_id)
            async with manager._mutation_locks.setdefault(child_id, asyncio.Lock()):
                child = await asyncio.to_thread(manager._repo.get, child_id)
                if child is None or child.user_id != row.user_id:
                    continue
                old = observed.get(child_id) if observed else None
                if (
                    old is not None
                    and child.attempt != old.attempt
                    and not (old.state == "queued" and child.attempt == old.attempt + 1)
                ):
                    continue
                pending.append(child)
                if child.state not in _ACTIVE and child.state != "cancelled":
                    continue
                changed = child.state == "cancelled" or await asyncio.to_thread(
                    manager._repo.transition,
                    child_id,
                    expected=_ACTIVE,
                    expected_attempt=child.attempt,
                    state="cancelled",
                    action="cancel",
                    actor_user_id=row.user_id,
                    fields={"finished_at": now_ts()},
                )
                if not changed and child.state == "queued":
                    # Admission increments an attempt without taking an action
                    # lock. Cancel a first claim racing this queued snapshot.
                    claimed = await asyncio.to_thread(manager._repo.get, child_id)
                    if (
                        claimed is not None
                        and claimed.user_id == row.user_id
                        and claimed.attempt == child.attempt + 1
                    ):
                        child = claimed
                        pending[-1] = child
                        changed = await asyncio.to_thread(
                            manager._repo.transition,
                            child_id,
                            expected=_ACTIVE,
                            expected_attempt=child.attempt,
                            state="cancelled",
                            action="cancel",
                            actor_user_id=row.user_id,
                            fields={"finished_at": now_ts()},
                        )
                if not changed:
                    continue
                for lease in list(manager._resume_leases.get(child_id, set())):
                    if lease.attempt == child.attempt:
                        lease.cancel()
                continuation = manager._continuations.get(child_id)
                if continuation is not None:
                    continuation.cancel()
                with contextlib.suppress(Exception):
                    cancel_scoped_jobs(manager._agents, child)
                if child.thread_id:
                    if child.attempt:
                        manager._bindings[(child.agent_id, child.user_id, child.thread_id)] = (
                            child.task_id,
                            child.attempt,
                        )
                    manager._agents.cancel_stream(child.agent_id, child.thread_id)
                    with contextlib.suppress(Exception):
                        manager._gateway.processor.hitl_coordinator.expire_pending_for_thread(
                            child.thread_id, agent_id=child.agent_id, user_id=child.user_id
                        )
                        manager._gateway.processor.teams.cancel_member_hitl(child.thread_id)
                worker = manager._running.get(child_id)
                if (
                    worker is not None
                    and worker is not asyncio.current_task()
                    and not worker.done()
                ):
                    if not worker.cancelling():
                        worker.cancel()
                    stopped.add(worker)
                verification = manager._verification_tasks.get((child_id, child.attempt))
                if (
                    verification is not None
                    and verification is not asyncio.current_task()
                    and not verification.done()
                ):
                    if not verification.cancelling():
                        verification.cancel()
                    stopped.add(verification)
    if stopped:
        await asyncio.gather(*stopped, return_exceptions=True)
    manager._wake.set()


async def cancel_children(manager: Any, row: TaskRow) -> None:
    """Cancel only descendants attached to this parent generation, without action locks."""
    await _cancel_tree(manager, row)


async def _coordination(manager: Any, row: TaskRow) -> tuple[bool, bool, bool]:
    controller = getattr(manager, "_coordinator", None)
    if controller is None:
        return False, False, False
    scopes = await asyncio.to_thread(
        manager._repos.task_coordination_repo.for_parent, row.task_id, row.attempt
    )
    if any(scope["state"] == "stopped" for scope in scopes):
        raise asyncio.CancelledError
    pending = bool(await controller.parent_pending(row))
    ready = not pending and bool(await controller.parent_review_ready(row))
    attention = any(scope["state"] in {"needs_user", "interrupted"} for scope in scopes)
    return pending, ready, attention


async def _finish_cancellation(
    manager: Any, row: TaskRow, tracked: dict[str, TaskRow | None]
) -> None:
    cleanup = asyncio.create_task(_cancel_tree(manager, row, observed=tracked))
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            # close_background and an app shutdown can cancel the same join.
            # Neither may abandon its descendant cleanup halfway through.
            continue
        except Exception:
            break
    try:
        await cleanup
    except Exception:
        # If persistence is temporarily unavailable, still stop executions we
        # already observed. Admission checks handle their durable rows later.
        stopped: set[asyncio.Task[Any]] = set()
        for child in tracked.values():
            if child is None:
                continue
            for lease in list(manager._resume_leases.get(child.task_id, set())):
                if lease.attempt == child.attempt:
                    lease.cancel()
            with contextlib.suppress(Exception):
                if child.thread_id:
                    manager._agents.cancel_stream(child.agent_id, child.thread_id)
            for job in (
                manager._running.get(child.task_id),
                manager._verification_tasks.get((child.task_id, child.attempt)),
            ):
                if job is not None and job is not asyncio.current_task() and not job.done():
                    if not job.cancelling():
                        job.cancel()
                    stopped.add(job)
        if stopped:
            await asyncio.gather(*stopped, return_exceptions=True)


def _release_join(manager: Any, key: tuple[str, int], completion: TeamCompletion) -> None:
    completions = manager._children_completions
    if completions.get(key) is completion:
        completions.pop(key, None)
    if not any(item[0] == key[0] and not future.done() for item, future in completions.items()):
        manager._delegated_waiters.discard(key[0])
    manager._wake.set()


async def background_children(manager: Any, row: TaskRow) -> TeamCompletion | None:
    """Return one shared barrier for each parent's unconsumed child results."""
    key = (row.task_id, row.attempt)
    # A resume and its finalizer can reach the same join concurrently.
    if not hasattr(manager, "_children_join_lock"):
        manager._children_join_lock = asyncio.Lock()
        manager._children_completions = {}
    async with manager._children_join_lock:
        completions: dict[tuple[str, int], TeamCompletion] = manager._children_completions
        existing = completions.get(key)
        if existing is not None and not existing.done():
            return existing
        settled = manager._settled_children.get(key, set())
        initial = {
            child_id: child
            for child_id, child in (await _snapshot(manager, row)).items()
            if child_id not in settled
        }
        coordination_pending, _, _ = await _coordination(manager, row)
        if not initial and not coordination_pending:
            return None
        manager._settled_children[key] = settled
        completion = TeamCompletion()
        completions[key] = completion
        manager._delegated_waiters.add(row.task_id)
        manager._wake.set()
        started = asyncio.Event()

        async def wait() -> None:
            tracked = dict(initial)
            review_requested = False

            def merge(snapshot: dict[str, TaskRow | None]) -> None:
                for child_id in tracked:
                    if child_id not in snapshot:
                        tracked[child_id] = None
                tracked.update(
                    {
                        child_id: child
                        for child_id, child in snapshot.items()
                        if child_id not in settled
                    }
                )

            def done() -> bool:
                return all(
                    child is None or child.state in TERMINAL_STATES for child in tracked.values()
                )

            try:
                started.set()
                while True:
                    current = await asyncio.to_thread(manager._repo.get, row.task_id)
                    if (
                        current is None
                        or current.user_id != row.user_id
                        or current.attempt != row.attempt
                        or current.state not in {"running", "waiting"}
                    ):
                        raise asyncio.CancelledError
                    merge(await _snapshot(manager, row))
                    coordination_pending, review_ready, attention = await _coordination(
                        manager, row
                    )
                    if done() and not coordination_pending:
                        # A new child may have been admitted while the last
                        # completed row was being read. Re-read before settling.
                        merge(await _snapshot(manager, row))
                        coordination_pending, review_ready, attention = await _coordination(
                            manager, row
                        )
                        if not done() or coordination_pending:
                            continue
                        current = await asyncio.to_thread(manager._repo.get, row.task_id)
                        if (
                            current is None
                            or current.attempt != row.attempt
                            or current.state not in {"running", "waiting"}
                        ):
                            raise asyncio.CancelledError
                        if not completion.done():
                            completion.set_result(
                                {
                                    "failed": not review_ready
                                    and any(
                                        child is None or child.state != "completed"
                                        for child in tracked.values()
                                    ),
                                    "paused": False,
                                    "output": _summary(
                                        manager, row, tracked, review_ready=review_ready
                                    ),
                                    "child_task_ids": list(tracked),
                                }
                            )
                            settled.update(tracked)
                        break
                    if done() and coordination_pending:
                        if not review_requested:
                            manager._wake.set()
                            review_requested = True
                    else:
                        review_requested = False
                    phase = (
                        "waiting"
                        if attention
                        or any(
                            child is not None and child.state in {"waiting", "paused"}
                            for child in tracked.values()
                        )
                        else "running"
                    )
                    if current.state != phase:
                        changed = await asyncio.to_thread(
                            manager._repo.transition,
                            row.task_id,
                            expected={current.state},
                            expected_attempt=row.attempt,
                            state=phase,
                            action="member_approval" if phase == "waiting" else "member_resumed",
                        )
                        if changed:
                            updated = await asyncio.to_thread(manager._repo.get, row.task_id)
                            if updated is not None:
                                with contextlib.suppress(Exception):
                                    await manager._notify_result(updated)
                    await asyncio.sleep(_POLL_SECONDS)
            except asyncio.CancelledError:
                await _finish_cancellation(manager, row, tracked)
                if not completion.done():
                    completion.cancel()
                raise
            except Exception:
                await _finish_cancellation(manager, row, tracked)
                if not completion.done():
                    completion.set_result(
                        {
                            "failed": True,
                            "paused": False,
                            "output": tr(
                                "tasks.children.failed",
                                manager._locales.get(row.user_id, DEFAULT_LOCALE),
                            ),
                            "child_task_ids": list(tracked),
                        }
                    )
            finally:
                _release_join(manager, key, completion)

        worker = asyncio.create_task(wait(), name=f"task-children-{row.task_id}-{row.attempt}")
        completion.worker = worker

        def stop(future: asyncio.Future[dict[str, Any]]) -> None:
            if future.cancelled() and not worker.cancelling():
                worker.cancel()

        completion.add_done_callback(stop)
        try:
            await started.wait()
        except asyncio.CancelledError:
            completion.cancel()
            worker.cancel()
            if not started.is_set():
                await _finish_cancellation(manager, row, initial)
                _release_join(manager, key, completion)
            await asyncio.gather(worker, return_exceptions=True)
            raise
        return completion
