"""Fence child admission against the final transition of its parent generation."""

from __future__ import annotations

import asyncio
from typing import Any, cast

from octop.infra.db.repos._base import now_ts
from octop.infra.db.repos.tasks import TaskRow
from octop.infra.tasks.children import _snapshot, background_children, cancel_children
from octop.infra.tasks.models import TERMINAL_STATES
from octop.infra.tasks.team_completion import close_background

_ACTIVE = {"running", "waiting"}
_RESULT_LIMIT = 128000


def _same_active_generation(current: Any, row: TaskRow) -> bool:
    return bool(
        current is not None
        and current.user_id == row.user_id
        and current.attempt == row.attempt
        and current.state in _ACTIVE
    )


async def enqueue_dispatch(
    manager: Any, task: dict[str, Any], parent: TaskRow | None
) -> str | None:
    """Insert once, or reject a child whose original parent generation has ended.

    The repository returns an existing task id on an idempotent replay. No
    parent lookup is repeated after admission: a late request never moves to a
    different parent, or silently becomes an independent task.
    """
    if parent is None:
        return cast(str | None, await asyncio.to_thread(manager._repo.enqueue, [task]))
    async with manager._mutation_locks.setdefault(parent.task_id, asyncio.Lock()):
        current = await asyncio.to_thread(manager._repo.get, parent.task_id)
        dispatch = task.get("dispatch")
        context = await asyncio.to_thread(manager._repos.task_dispatch_repo.get, parent.task_id)
        phase = ((context or {}).get("coding_run") or {}).get("phase")
        if (
            not _same_active_generation(current, parent)
            or task.get("user_id") != parent.user_id
            or not isinstance(dispatch, dict)
            or dispatch.get("parent_task_id") != parent.task_id
            or dispatch.get("parent_attempt") != parent.attempt
            or phase in {"verifying", "pushed"}
        ):
            raise manager._error("invalid_transition", user_id=parent.user_id, status=409)
        return cast(str | None, await asyncio.to_thread(manager._repo.enqueue, [task]))


def _append_child_output(
    fields: dict[str, Any], append_result: str | None, output: str
) -> tuple[dict[str, Any], str | None]:
    if not output:
        return fields, append_result
    if "result" in fields:
        previous = str(fields["result"] or "")
        fields["result"] = "\n\n".join(part for part in (previous, output) if part)[-_RESULT_LIMIT:]
    else:
        append_result = "\n\n".join(part for part in (append_result, output) if part)
    return fields, append_result


async def finish_task(
    manager: Any,
    row: TaskRow,
    *,
    state: str,
    fields: dict[str, Any],
    append_result: str | None = None,
    action: str | None = None,
) -> bool:
    """Join admitted children and commit a final state under the admission fence.

    True means the transition was applied. False means the row disappeared or
    this generation was already stopped/replaced. A rejected CAS while the
    same generation is still active raises instead of claiming completion.
    Child waits and descendant cancellation never hold the parent action lock.
    """
    result_fields = dict(fields)
    waited = False
    children_failed = False
    key = (row.task_id, row.attempt)
    while True:
        join = False
        async with manager._mutation_locks.setdefault(row.task_id, asyncio.Lock()):
            current = await asyncio.to_thread(manager._repo.get, row.task_id)
            if not _same_active_generation(current, row):
                return False
            if state == "completed":
                coordinator = getattr(manager, "_coordinator", None)
                review_ready = (
                    bool(await coordinator.parent_review_ready(current))
                    if coordinator is not None
                    else False
                )
                review_pending = (
                    bool(await coordinator.parent_pending(current))
                    if coordinator is not None
                    else False
                )
                children = await _snapshot(manager, current)
                settled = manager._settled_children.setdefault(key, set())
                pending = {
                    child_id
                    for child_id, child in children.items()
                    if child is not None and child.state not in TERMINAL_STATES
                }
                # An explicitly retried child reopens its contribution. A
                # previously consumed terminal result is never appended twice.
                settled.difference_update(pending)
                join = bool(review_pending or pending or set(children) - settled)
                if (
                    not join
                    and not review_ready
                    and (
                        children_failed
                        or any(
                            child is None or child.state != "completed"
                            for child in children.values()
                        )
                    )
                ):
                    state = "failed"
                    result_fields["error_code"] = (
                        result_fields.get("error_code") or "execution_failed"
                    )
            if not join:
                if waited and state in TERMINAL_STATES and "finished_at" in result_fields:
                    result_fields["finished_at"] = now_ts()
                changed = await asyncio.to_thread(
                    manager._repo.transition,
                    row.task_id,
                    expected=_ACTIVE,
                    expected_attempt=row.attempt,
                    state=state,
                    action=action if action is not None else state,
                    fields=result_fields,
                    append_result=append_result,
                )
                if not changed:
                    latest = await asyncio.to_thread(manager._repo.get, row.task_id)
                    if _same_active_generation(latest, row):
                        raise manager._error("invalid_transition", user_id=row.user_id, status=409)
                    return False
        if not join:
            if state == "failed":
                await cancel_children(manager, current)
            return True
        completion = await background_children(manager, current)
        if completion is None:
            # Another finalizer may just have consumed this shared join. Read
            # the rows again under the fence before attempting completion.
            continue
        waited = True
        try:
            outcome = await asyncio.shield(completion)
        except asyncio.CancelledError:
            await close_background(completion)
            raise
        result_fields, append_result = _append_child_output(
            result_fields, append_result, str(outcome.get("output") or "")
        )
        if outcome.get("failed"):
            # A later coordinator review may accept the goal after recovering
            # from a failed/cancelled member. Decide under the final fence.
            children_failed = True
