"""Real SQLite fences for parent completion and late expert admission."""

from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import RepoBundle
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.tasks.admission import enqueue_dispatch, finish_task
from octop.infra.tasks.children import background_children, cancel_children


@pytest.fixture
async def env(tmp_path, monkeypatch):
    monkeypatch.setenv("OCTOP_HOME", str(tmp_path))
    db = SqlitePool(tmp_path / "admission.sqlite")
    run_migrations(db)
    repos = RepoBundle.from_pool(db)
    uid = repos.user_repo.create(username="owner", password_hash="synthetic", role="admin")
    other = repos.user_repo.create(username="other", password_hash="synthetic", role="admin")
    for aid, owner in [("host", uid), ("worker", uid), ("foreign", other)]:
        repos.agent_repo.create(agent_id=aid, user_id=owner, name=aid)
    repos.task_repo.enqueue(
        [
            {
                "task_id": "parent",
                "user_id": uid,
                "agent_id": "host",
                "title": "Parent",
                "prompt": "Coordinate",
                "dispatch": {"coding_spec": None},
            }
        ]
    )
    assert repos.task_repo.claim("parent")
    parent = repos.task_repo.get("parent")
    assert parent is not None

    def error(key, **kwargs):
        return OctopError(ErrorCode.SLASH_BAD_ARGS, key, status=kwargs.get("status", 400))

    manager = SimpleNamespace(
        _repo=repos.task_repo,
        _repos=repos,
        _mutation_locks={},
        _settled_children={},
        _delegated_waiters=set(),
        _resume_leases={},
        _continuations={},
        _running={},
        _bindings={},
        _verification_tasks={},
        _locales={uid: "en"},
        _wake=asyncio.Event(),
        _error=error,
        _agents=SimpleNamespace(cancel_stream=Mock()),
        _publish=AsyncMock(),
    )
    spawned = []

    def spawn(awaitable):
        task = asyncio.create_task(awaitable)
        spawned.append(task)
        return task

    def child(task_id="child"):
        return {
            "task_id": task_id,
            "user_id": uid,
            "agent_id": "worker",
            "title": task_id,
            "prompt": "Deliver a result",
            "dispatch": {"parent_task_id": parent.task_id, "parent_attempt": parent.attempt},
        }

    try:
        yield SimpleNamespace(
            m=manager, repos=repos, uid=uid, other=other, parent=parent, child=child, spawn=spawn
        )
    finally:
        for task in spawned:
            if not task.done():
                task.cancel()
        joins = list(getattr(manager, "_children_completions", {}).values())
        workers = [join.worker for join in joins if join.worker is not None]
        for join in joins:
            join.cancel()
        for worker in workers:
            worker.cancel()
        await asyncio.gather(*spawned, *workers, return_exceptions=True)
        db.close()


async def joined(manager):
    async def wait():
        while "parent" not in manager._delegated_waiters:
            await asyncio.sleep(0.01)

    await asyncio.wait_for(wait(), timeout=3)


def complete(repo, task_id="child", *, state="completed", result="worker result"):
    assert repo.claim(task_id)
    assert repo.transition(
        task_id, expected={"running"}, state=state, action=state, fields={"result": result}
    )


async def test_no_parent_keeps_normal_task_enqueue_unchanged(env):
    task = env.child()
    task.pop("dispatch")
    task["options"] = {"quiet": True}
    assert await enqueue_dispatch(env.m, task, None) is None
    row = env.repos.task_repo.get("child")
    assert row is not None and row.state == "queued"
    assert json.loads(row.options_json) == {"quiet": True}


async def test_child_insert_holds_fence_and_parent_waits_for_its_result(env, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = env.repos.task_repo.enqueue

    def gated(tasks):
        entered.set()
        assert release.wait(5)
        return original(tasks)

    monkeypatch.setattr(env.repos.task_repo, "enqueue", gated)
    insertion = env.spawn(enqueue_dispatch(env.m, env.child(), env.parent))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        finishing = env.spawn(
            finish_task(
                env.m,
                env.parent,
                state="completed",
                fields={"result": "parent body", "finished_at": 1},
            )
        )
        await asyncio.sleep(0)
        assert not finishing.done()
        release.set()
        assert await insertion is None
        await joined(env.m)
        assert env.repos.task_repo.get("parent").state == "running"
        complete(env.repos.task_repo)
        assert await asyncio.wait_for(finishing, 3)
        row = env.repos.task_repo.get("parent")
        assert row.state == "completed"
        assert "parent body" in row.result and "worker result" in row.result
        assert row.finished_at > 1
    finally:
        release.set()


async def test_parent_completion_holds_fence_and_late_insert_is_rejected(env, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = env.repos.task_repo.transition

    def gated(task_id, **kwargs):
        if task_id == "parent" and kwargs["state"] == "completed":
            entered.set()
            assert release.wait(5)
        return original(task_id, **kwargs)

    monkeypatch.setattr(env.repos.task_repo, "transition", gated)
    finishing = env.spawn(
        finish_task(env.m, env.parent, state="completed", fields={"result": "done"})
    )
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        insertion = env.spawn(enqueue_dispatch(env.m, env.child(), env.parent))
        await asyncio.sleep(0)
        assert not insertion.done()
        release.set()
        assert await finishing
        with pytest.raises(OctopError) as caught:
            await insertion
        assert caught.value.status == 409
        assert env.repos.task_repo.get("child") is None
        assert env.repos.task_repo.get("parent").state == "completed"
    finally:
        release.set()


async def test_cancel_acquires_parent_lock_while_completion_waits_for_children(env):
    await enqueue_dispatch(env.m, env.child(), env.parent)
    finishing = env.spawn(
        finish_task(env.m, env.parent, state="completed", fields={"result": "body"})
    )
    await joined(env.m)

    async def cancel():
        async with env.m._mutation_locks["parent"]:
            assert env.repos.task_repo.transition(
                "parent", expected={"running", "waiting"}, state="cancelled", action="cancel"
            )
        await cancel_children(env.m, env.parent)

    await asyncio.wait_for(cancel(), 1)
    await asyncio.gather(finishing, return_exceptions=True)
    assert env.repos.task_repo.get("parent").state == "cancelled"
    assert env.repos.task_repo.get("child").state == "cancelled"


async def test_cancelled_caller_reaps_its_late_child_barrier(env):
    await enqueue_dispatch(env.m, env.child(), env.parent)
    finishing = env.spawn(
        finish_task(env.m, env.parent, state="completed", fields={"result": "body"})
    )
    await joined(env.m)
    completion = env.m._children_completions[(env.parent.task_id, env.parent.attempt)]
    worker = completion.worker
    finishing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await finishing
    assert worker is not None and worker.done()
    assert env.repos.task_repo.get("child").state == "cancelled"
    assert "parent" not in env.m._delegated_waiters


@pytest.mark.parametrize(
    "change", ["stopped", "generation", "owner", "context", "verifying", "pushed"]
)
async def test_revalidates_original_parent_context_before_insert(env, change):
    parent, task = env.parent, env.child()
    if change == "stopped":
        env.repos.task_repo.transition(
            "parent", expected={"running"}, state="cancelled", action="cancel"
        )
    elif change == "generation":
        parent = replace(parent, attempt=0)
    elif change == "owner":
        task["user_id"] = env.other
    elif change == "context":
        task["dispatch"]["parent_attempt"] = 0
    else:
        env.repos.task_dispatch_repo.update_coding("parent", {"phase": change})
    with pytest.raises(OctopError) as caught:
        await enqueue_dispatch(env.m, task, parent)
    assert caught.value.status == 409
    assert env.repos.task_repo.get("child") is None


async def test_append_mode_keeps_prior_segments_and_new_child_output(env):
    await enqueue_dispatch(env.m, env.child(), env.parent)
    complete(env.repos.task_repo)
    env.repos.task_repo.transition(
        "parent",
        expected={"running"},
        state="running",
        action="segment",
        fields={"result": "prior segment"},
    )
    assert await finish_task(
        env.m,
        env.parent,
        state="completed",
        fields={"finished_at": 1},
        append_result="approval segment",
        action="approval_resumed",
    )
    result = env.repos.task_repo.get("parent").result
    assert "prior segment" in result and "approval segment" in result
    assert result.count("worker result") == 1
    assert env.repos.task_repo.events("parent")[-1]["action"] == "approval_resumed"


async def test_already_consumed_children_are_not_appended_twice(env):
    await enqueue_dispatch(env.m, env.child(), env.parent)
    complete(env.repos.task_repo)
    completion = await background_children(env.m, env.parent)
    assert completion is not None
    outcome = await completion
    body = "parent body\n\n" + outcome["output"]
    assert await finish_task(env.m, env.parent, state="completed", fields={"result": body})
    assert env.repos.task_repo.get("parent").result == body
    assert not await finish_task(env.m, env.parent, state="completed", fields={"result": "stale"})
    assert env.repos.task_repo.get("parent").result == body


async def test_failed_parent_stops_remaining_children_without_replacing_its_body(env):
    await enqueue_dispatch(env.m, env.child(), env.parent)
    assert await finish_task(
        env.m, env.parent, state="failed", fields={"result": "original failure"}
    )
    assert env.repos.task_repo.get("parent").result == "original failure"
    assert env.repos.task_repo.get("child").state == "cancelled"


async def test_a_failed_child_prevents_successful_parent_completion(env):
    await enqueue_dispatch(env.m, env.child(), env.parent)
    complete(env.repos.task_repo, state="failed", result="child failed")
    assert await finish_task(env.m, env.parent, state="completed", fields={"result": "parent body"})
    row = env.repos.task_repo.get("parent")
    assert row.state == "failed" and row.error_code == "execution_failed"
    assert "parent body" in row.result and "child failed" in row.result


async def test_rejected_transition_is_not_reported_as_finished_while_still_active(env, monkeypatch):
    monkeypatch.setattr(env.repos.task_repo, "transition", lambda *args, **kwargs: False)
    with pytest.raises(OctopError) as caught:
        await finish_task(env.m, env.parent, state="completed", fields={"result": "done"})
    assert caught.value.status == 409
    assert env.repos.task_repo.get("parent").state == "running"


def attach_review(env):
    """A short read-only coordinator port; keep real SQL and the real join."""
    repo = env.repos.task_coordination_repo
    env.repos.thread_repo.insert(
        thread_id="review-origin",
        agent_id="host",
        user_id=env.uid,
        channel_type="dashboard",
        session_key="admission-review-origin",
    )
    repo.ensure(
        {
            "scope_id": "review",
            "user_id": env.uid,
            "origin_agent_id": "host",
            "origin_thread_id": "review-origin",
            "parent_task_id": env.parent.task_id,
            "parent_attempt": env.parent.attempt,
            "goal_text": "Deliver the complete goal",
        }
    )

    class Review:
        async def parent_pending(self, row):
            scopes = await asyncio.to_thread(repo.for_parent, row.task_id, row.attempt)
            return any(
                s["state"] in {"pending", "running", "needs_user", "interrupted"} for s in scopes
            )

        async def parent_review_ready(self, row):
            scopes = await asyncio.to_thread(repo.for_parent, row.task_id, row.attempt)
            return bool(scopes) and all(
                s["state"] == "idle" and s["decision"] == "ready" for s in scopes
            )

    env.m._coordinator = Review()
    return repo


def review_ready(repo):
    assert repo.claim("review", "review-signature")
    assert repo.decide("review", "ready", "The complete goal is verified.", "")
    assert repo.finish("review", "review-signature", "idle")


async def test_settled_children_still_wait_for_pending_coordinator_review(env):
    await enqueue_dispatch(env.m, env.child(), env.parent)
    complete(env.repos.task_repo)
    consumed = await background_children(env.m, env.parent)
    assert consumed is not None
    await consumed
    repo = attach_review(env)
    finishing = env.spawn(
        finish_task(env.m, env.parent, state="completed", fields={"result": "original body"})
    )
    await joined(env.m)
    assert not finishing.done()
    assert env.repos.task_repo.get("parent").state != "completed"
    review_ready(repo)
    assert await asyncio.wait_for(finishing, 3)
    row = env.repos.task_repo.get("parent")
    assert row.state == "completed" and row.result == "original body"


async def test_explicit_ready_review_accepts_a_recovered_goal_with_failed_history(env):
    await enqueue_dispatch(env.m, env.child(), env.parent)
    complete(env.repos.task_repo, state="failed", result="historical failed attempt")
    repo = attach_review(env)
    review_ready(repo)
    assert await finish_task(
        env.m, env.parent, state="completed", fields={"result": "review accepted"}
    )
    assert env.repos.task_repo.get("parent").state == "completed"
    assert env.repos.task_repo.get("parent").error_code is None


async def test_needs_user_review_does_not_hold_parent_lock_against_cancel(env):
    repo = attach_review(env)
    assert repo.require_user("review", "Confirm the report format.")
    finishing = env.spawn(
        finish_task(env.m, env.parent, state="completed", fields={"result": "body"})
    )
    await joined(env.m)

    async def cancel():
        async with env.m._mutation_locks["parent"]:
            assert env.repos.task_repo.transition(
                "parent", expected={"running", "waiting"}, state="cancelled", action="cancel"
            )

    await asyncio.wait_for(cancel(), 1)
    await asyncio.gather(finishing, return_exceptions=True)
    assert env.repos.task_repo.get("parent").state == "cancelled"
