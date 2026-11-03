"""Durable children join real persisted states, not dispatch acknowledgements."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from tests.unit.tasks.test_coding import Spec, git
from tests.unit.tasks.test_task_manager import enqueue
from tests.unit.tasks.test_task_manager import setup as setup

from octop.infra.tasks.children import background_children, cancel_children
from octop.infra.tasks.coding import CodingTaskService, run_command
from octop.infra.tasks.team_completion import close_background


async def parent(e):
    row = await enqueue(e, "coordinate", "a")
    assert e.repos.task_repo.claim(row.task_id)
    return e.repos.task_repo.get(row.task_id)


def child(e, root, task_id="child", *, agent="b", attempt=None, user=None, coordination=None):
    e.repos.task_repo.enqueue(
        [
            {
                "task_id": task_id,
                "user_id": e.uid if user is None else user,
                "agent_id": agent,
                "title": task_id,
                "prompt": "fixture task",
                "dispatch": {
                    "parent_task_id": root.task_id,
                    "parent_attempt": root.attempt if attempt is None else attempt,
                    **(
                        {
                            "scope_id": coordination["scope_id"],
                            "origin_agent_id": coordination["origin_agent_id"],
                            "origin_thread_id": coordination["origin_thread_id"],
                        }
                        if coordination
                        else {}
                    ),
                },
            }
        ]
    )
    return e.repos.task_repo.get(task_id)


async def scope_for(e, row):
    e.agents.principal_agent_id = lambda agent_id: agent_id
    origin = await e.gateway.thread_registry.get_or_create(
        agent_id="a", user_id=e.uid, channel_type="dashboard", channel_subject_id="scope-source"
    )
    return e.repos.task_coordination_repo.ensure(
        {
            "scope_id": "coordination-" + row.task_id,
            "user_id": e.uid,
            "origin_agent_id": "a",
            "origin_thread_id": origin,
            "parent_task_id": row.task_id,
            "parent_attempt": row.attempt,
            "goal_text": "fixture authorized goal",
            "source_message_id": "fixture-original-input",
        }
    )


def delivered(e, task_id):
    row = e.repos.task_repo.get(task_id)
    context = e.repos.task_dispatch_repo.get(task_id)
    assert e.repos.task_dispatch_repo.mark_returned(
        task_id,
        row.attempt,
        state=row.state,
        event_id=context["current_event_id"],
        expected_attempt=row.attempt,
    )


def transition(e, task_id, state, result=""):
    row = e.repos.task_repo.get(task_id)
    assert e.repos.task_repo.transition(
        task_id,
        expected={row.state},
        expected_attempt=row.attempt,
        state=state,
        action=state,
        fields={"result": result},
    )


async def until(predicate, *, timeout=3):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


async def test_no_children_returns_no_barrier(setup):
    root = await parent(setup)
    assert await background_children(setup.manager, root) is None
    assert not setup.manager._delegated_waiters


async def test_ack_does_not_finish_parent_and_two_new_experts_execute_concurrently(setup):
    e = setup
    root = await parent(e)
    e.repos.agent_repo.create(agent_id="fresh-expert", user_id=e.uid, name="新专家")
    child(e, root, "analysis", agent="b")
    child(e, root, "writing", agent="fresh-expert")
    barrier = await background_children(e.manager, root)
    assert barrier is not None and not barrier.done()
    assert root.task_id in e.manager._delegated_waiters
    assert e.repos.task_repo.get(root.task_id).state == "running"
    gate = asyncio.Event()
    e.processor.gate = gate

    async def join():
        return await barrier

    supervisor = asyncio.create_task(join())
    e.manager._running[root.task_id] = supervisor
    await e.channels.start()
    try:
        await e.manager.process_once()
        await until(lambda: len(e.processor.received) == 2)
        assert not barrier.done()
        assert {msg.tenant_id for msg in e.processor.received} == {"b", "fresh-expert"}
        gate.set()
        outcome = await asyncio.wait_for(supervisor, timeout=5)
        assert outcome["failed"] is False
        assert set(outcome["child_task_ids"]) == {"analysis", "writing"}
        assert "verified output" in outcome["output"]
        assert root.task_id not in e.manager._delegated_waiters
    finally:
        gate.set()
        await close_background(barrier)
        await e.manager.stop()
        await e.channels.stop()


async def test_completed_children_are_consumed_once_but_later_children_join(setup):
    e = setup
    root = await parent(e)
    child(e, root, "fast")
    transition(e, "fast", "completed", "first real result")
    first = await background_children(e.manager, root)
    assert first is not None
    result = await asyncio.wait_for(first, timeout=2)
    assert result["failed"] is False and "first real result" in result["output"]
    assert await background_children(e.manager, root) is None
    child(e, root, "later")
    second = await background_children(e.manager, root)
    assert second is not None and not second.done()
    transition(e, "later", "completed", "second result")
    result = await asyncio.wait_for(second, timeout=2)
    assert result["child_task_ids"] == ["later"]
    assert "second result" in result["output"] and "first real result" not in result["output"]


async def test_concurrent_resume_paths_share_the_same_barrier(setup):
    e = setup
    root = await parent(e)
    child(e, root)
    one, two = await asyncio.gather(
        background_children(e.manager, root), background_children(e.manager, root)
    )
    assert one is two and one is not None
    transition(e, "child", "completed", "one result")
    assert (await asyncio.wait_for(one, timeout=2))["failed"] is False


async def test_new_children_during_wait_are_not_missed(setup):
    e = setup
    root = await parent(e)
    child(e, root, "one")
    barrier = await background_children(e.manager, root)
    assert barrier is not None
    child(e, root, "two")
    transition(e, "one", "completed", "one result")
    await asyncio.sleep(0.6)
    assert not barrier.done()
    transition(e, "two", "completed", "two result")
    result = await asyncio.wait_for(barrier, timeout=2)
    assert set(result["child_task_ids"]) == {"one", "two"}


async def test_member_approval_tracks_parent_phase_and_failure_is_real(setup):
    e = setup
    root = await parent(e)
    child(e, root)
    transition(e, "child", "waiting")
    e.manager._notify_result = AsyncMock()
    barrier = await background_children(e.manager, root)
    assert barrier is not None
    await until(lambda: e.repos.task_repo.get(root.task_id).state == "waiting")
    assert not barrier.done() and root.task_id in e.manager._delegated_waiters
    transition(e, "child", "running")
    await until(lambda: e.repos.task_repo.get(root.task_id).state == "running")
    transition(e, "child", "failed", "bounded failure")
    result = await asyncio.wait_for(barrier, timeout=2)
    assert result["failed"] is True
    assert "bounded failure" in result["output"]
    assert [call.args[0].state for call in e.manager._notify_result.call_args_list] == [
        "waiting",
        "running",
    ]


async def test_old_attempt_cannot_settle_a_new_parent_attempt(setup):
    e = setup
    root = await parent(e)
    child(e, root, "old")
    old = await background_children(e.manager, root)
    assert old is not None
    e.repos.task_repo.transition(
        root.task_id,
        expected={"running"},
        state="running",
        action="fixture",
        fields={"attempt": root.attempt + 1},
    )
    newer = e.repos.task_repo.get(root.task_id)
    child(e, newer, "new")
    current = await background_children(e.manager, newer)
    assert current is not None
    await until(old.done)
    assert old.cancelled()
    assert root.task_id in e.manager._delegated_waiters
    assert e.repos.task_repo.get("old").state == "cancelled"
    assert e.repos.task_repo.get("new").state == "queued"
    assert not e.manager._settled_children[(root.task_id, root.attempt)]
    transition(e, "new", "completed", "new generation")
    result = await asyncio.wait_for(current, timeout=2)
    assert result["child_task_ids"] == ["new"]


async def test_cancel_stops_descendants_workers_and_does_not_mark_consumed(setup):
    e = setup
    root = await parent(e)
    leaf = child(e, root)
    assert e.repos.task_repo.claim(leaf.task_id)
    leaf = e.repos.task_repo.get(leaf.task_id)
    child(e, leaf, "grandchild")
    stopped = asyncio.Event()

    async def busy():
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    worker = asyncio.create_task(busy())
    e.manager._running[leaf.task_id] = worker
    await asyncio.sleep(0)
    barrier = await background_children(e.manager, root)
    assert barrier is not None
    await asyncio.gather(close_background(barrier), close_background(barrier))
    assert stopped.is_set()
    assert e.repos.task_repo.get(leaf.task_id).state == "cancelled"
    assert e.repos.task_repo.get("grandchild").state == "cancelled"
    assert not e.manager._delegated_waiters
    assert not e.manager._settled_children[(root.task_id, root.attempt)]


async def test_output_is_bounded_and_foreign_child_data_is_not_exposed(setup):
    e = setup
    root = await parent(e)
    for i in range(12):
        task_id = f"result-{i}"
        child(e, root, task_id)
        transition(e, task_id, "completed", "x" * 10000)
    barrier = await background_children(e.manager, root)
    result = await asyncio.wait_for(barrier, timeout=2)
    assert len(result["output"]) <= 12000
    child(e, root, "foreign-job", agent="foreign", user=e.other)
    transition(e, "foreign-job", "completed", "foreign private result")
    foreign = await background_children(e.manager, root)
    result = await asyncio.wait_for(foreign, timeout=2)
    assert result["failed"] is True
    assert "foreign private result" not in result["output"]


async def test_cancellation_targets_only_the_requested_parent_attempt(setup):
    e = setup
    root = await parent(e)
    child(e, root, "old", attempt=root.attempt - 1)
    child(e, root, "current")
    await cancel_children(e.manager, root)
    assert e.repos.task_repo.get("current").state == "cancelled"
    assert e.repos.task_repo.get("old").state == "queued"


async def test_storage_error_fails_join_and_stops_an_observed_worker(setup, monkeypatch):
    e = setup
    root = await parent(e)
    row = child(e, root)
    stopped = asyncio.Event()

    async def busy():
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    worker = asyncio.create_task(busy())
    e.manager._running[row.task_id] = worker
    await asyncio.sleep(0)
    barrier = await background_children(e.manager, root)
    assert barrier is not None

    def unavailable(*args):
        raise RuntimeError("synthetic persistence failure")

    monkeypatch.setattr(e.repos.task_dispatch_repo, "children", unavailable)
    result = await asyncio.wait_for(barrier, timeout=2)
    assert result["failed"] is True
    assert "synthetic persistence failure" not in result["output"]
    assert stopped.is_set()
    assert not e.manager._delegated_waiters
    assert not e.manager._settled_children[(root.task_id, root.attempt)]


async def test_cancel_catches_a_claim_racing_the_queued_child(setup, monkeypatch):
    e = setup
    root = await parent(e)
    child(e, root)
    original = e.repos.task_repo.transition
    claimed = False

    def racing(task_id, **kwargs):
        nonlocal claimed
        if task_id == "child" and kwargs["action"] == "cancel" and not claimed:
            claimed = True
            assert e.repos.task_repo.claim(task_id)
        return original(task_id, **kwargs)

    monkeypatch.setattr(e.repos.task_repo, "transition", racing)
    await cancel_children(e.manager, root)
    current = e.repos.task_repo.get("child")
    assert current.attempt == 1 and current.state == "cancelled"


async def test_parent_cancel_stops_a_shielded_child_verification_process(setup, tmp_path):
    e = setup
    root = await parent(e)
    leaf = child(e, root, "verifying-child")
    assert e.repos.task_repo.claim(leaf.task_id)
    leaf = e.repos.task_repo.get(leaf.task_id)
    transition(e, leaf.task_id, "waiting")
    project = tmp_path / "fixture-code"
    project.mkdir()
    git(project, "init", "-b", "main")
    git(project, "config", "user.name", "Fixture")
    git(project, "config", "user.email", "fixture@example.invalid")
    (project / "code.py").write_text("original = True\n")
    git(project, "add", ".")
    git(project, "commit", "-m", "initial")
    started, late = tmp_path / "verify-started", tmp_path / "verify-late"
    remote_actions = []

    async def runner(argv, *, cwd, timeout, log_path=None):
        if argv[0] == "gh" or "push" in argv:
            remote_actions.append(argv)
            raise AssertionError("No remote actions are allowed in this fixture")
        return await run_command(argv, cwd=cwd, timeout=timeout, log_path=log_path)

    async def active():
        if e.repos.task_repo.get(leaf.task_id).state == "cancelled":
            raise asyncio.CancelledError

    command = f'''"{sys.executable}" -c "from pathlib import Path; import time; Path({str(started)!r}).touch(); time.sleep(.7); Path({str(late)!r}).touch()"'''
    specification = Spec(str(project), test_commands=[command], publish_pr=True)
    service = CodingTaskService(command_runner=runner)
    run = await service.prepare(leaf.task_id, e.uid, specification)
    (Path(run["worktree"]) / "change.py").write_text("changed = True\n")
    verifier = asyncio.create_task(
        service.finalize(leaf.task_id, "Fixture", specification, run, check_active=active)
    )
    e.manager._verification_tasks[(leaf.task_id, leaf.attempt)] = verifier
    await until(started.exists, timeout=5)
    await cancel_children(e.manager, root)
    assert verifier.cancelled()
    await asyncio.sleep(0.8)
    assert not late.exists()
    assert not remote_actions


async def test_pending_coordinator_keeps_a_barrier_even_without_unconsumed_children(setup):
    e = setup
    row = await parent(e)
    controller = SimpleNamespace(
        parent_pending=AsyncMock(return_value=True),
        parent_review_ready=AsyncMock(return_value=False),
    )
    e.manager._coordinator = controller
    barrier = await background_children(e.manager, row)
    assert barrier is not None
    try:
        await asyncio.sleep(0.6)
        assert not barrier.done() and row.task_id in e.manager._delegated_waiters
        assert e.manager._wake.is_set()
        controller.parent_pending.return_value = False
        controller.parent_review_ready.return_value = True
        result = await asyncio.wait_for(barrier, timeout=2)
        assert not result["failed"] and not result["child_task_ids"]
        assert result["output"] == ""
    finally:
        await close_background(barrier)


async def test_real_scope_waits_for_user_then_main_review_accepts_replacement_result(setup):
    e = setup
    row = await parent(e)
    scope = await scope_for(e, row)
    first = child(e, row, "first-result", coordination=scope)
    assert e.repos.task_repo.claim(first.task_id)
    transition(e, first.task_id, "failed", "first attempt was not sufficient")
    delivered(e, first.task_id)
    assert e.repos.task_coordination_repo.require_user(scope["scope_id"], "Which approach?")
    barrier = await background_children(e.manager, row)
    assert barrier is not None
    seen_input = []

    async def review(agents, gateway, actual_scope, prompt, user_input=""):
        seen_input.append(user_input)
        assert e.repos.task_coordination_repo.decide(
            actual_scope["scope_id"], "ready", "goal checked using replacement result", ""
        )
        return {"output": "reviewed", "failed": False, "paused": False}

    e.manager._coordinator._invoke = review
    try:
        await until(lambda: e.repos.task_repo.get(row.task_id).state == "waiting")
        assert not barrier.done() and row.task_id in e.manager._delegated_waiters
        await e.manager.continue_coordination(
            e.uid, first.task_id, prompt="Try the second approach"
        )
        second = child(e, row, "replacement", coordination=scope)
        assert e.repos.task_repo.claim(second.task_id)
        transition(e, second.task_id, "completed", "replacement achieved the original goal")
        delivered(e, second.task_id)
        await e.manager._coordinator.schedule()
        assert e.manager._coordinator.jobs
        await asyncio.gather(*e.manager._coordinator.jobs.values())
        result = await asyncio.wait_for(barrier, timeout=3)
        assert result["failed"] is False
        assert set(result["child_task_ids"]) == {"first-result", "replacement"}
        assert seen_input == ["Try the second approach"]
        assert e.repos.task_coordination_repo.get(scope["scope_id"])["decision"] == "ready"
        assert await e.manager._coordinator.parent_review_ready(row)
    finally:
        await close_background(barrier)
        await e.manager._coordinator.stop()


async def test_stopped_scope_cancels_a_join_instead_of_reporting_goal_completion(setup):
    e = setup
    row = await parent(e)
    scope = await scope_for(e, row)
    result = child(e, row, coordination=scope)
    transition(e, result.task_id, "completed", "worker finished but goal not reviewed")
    barrier = await background_children(e.manager, row)
    assert barrier is not None
    e.repos.task_coordination_repo.stop_parent(row.task_id, row.attempt)
    await until(barrier.done)
    assert barrier.cancelled()
    assert not e.manager._settled_children[(row.task_id, row.attempt)]
    await close_background(barrier)
