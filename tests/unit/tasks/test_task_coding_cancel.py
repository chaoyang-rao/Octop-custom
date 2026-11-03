"""Approval finalizers and return retries use real task persistence, not real PRs."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from octop_gateway.models import ChannelSubject, InboundMessage, TextContent
from tests.unit.tasks.test_task_manager import settled
from tests.unit.tasks.test_task_manager import setup as setup

from octop.infra.errors import OctopError
from octop.infra.tasks.models import CodingTaskSpec, TaskCreate


class GateCoding:
    def __init__(self, *, ignore_cancel: bool = False):
        self.ignore_cancel = ignore_cancel
        self.prepares = []
        self.finalizes = []
        self.published = []
        self.entered = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.release = asyncio.Event()

    async def prepare(self, task_id, user_id, spec, previous=None):
        self.prepares.append(task_id)
        return {"phase": "prepared", "worktree": spec.project_path, "branch": "fixture/task"}

    def prompt_context(self, run):
        return "fixture-only coding context"

    async def finalize(self, task_id, title, spec, run, *, locale, check_active):
        self.finalizes.append(task_id)
        self.entered.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            if not self.ignore_cancel:
                raise
            await self.release.wait()
        await check_active()
        self.published.append(task_id)
        return {
            **run,
            "phase": "published",
            "pr_url": "https://github.com/fixture/project/pull/1",
            "verification": [{"command_index": 0, "exit_code": 0, "passed": True}],
        }


async def until(predicate, timeout=3):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


async def coding_task(e, project: Path):
    project.mkdir()
    e.repos.thread_repo.upsert_project(
        agent_id="a", user_id=e.uid, project_path=str(project), project_name="Fixture"
    )
    return await e.manager.enqueue(
        e.uid,
        TaskCreate(
            agent_id="a",
            title="Fixture coding",
            prompt="A fixture-only requirement",
            coding=CodingTaskSpec(
                project_path=str(project), test_commands=["fixture-check"], publish_pr=True
            ),
        ),
    )


async def paused_coding_task(e, project):
    task = await coding_task(e, project)
    e.processor.pause = True
    await e.manager.process_once()
    await settled(e.manager)
    current = e.repos.task_repo.get(task.task_id)
    assert current.state == "waiting" and current.thread_id
    return current


async def disconnected_resume(e, row, fake):
    request = asyncio.create_task(
        e.manager.complete_waiting_turn(
            agent_id=row.agent_id,
            user_id=row.user_id,
            thread_id=row.thread_id,
            failed=False,
            paused=False,
            output="approval result",
            attempts={row.task_id: row.attempt},
        )
    )
    await asyncio.wait_for(fake.entered.wait(), timeout=3)
    assert (row.task_id, row.attempt) in e.manager._verification_tasks
    assert not e.manager._running.get(row.task_id) or e.manager._running[row.task_id].done()
    # Closing the HTTP client is intentionally distinct from cancelling a task.
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    assert e.manager._finalizers


async def test_cancel_stops_hitl_verification_after_http_client_disconnected(setup, tmp_path):
    e = setup
    fake = GateCoding()
    e.manager._coding_service = fake
    await e.channels.start()
    try:
        row = await paused_coding_task(e, tmp_path / "project")
        assert len(fake.prepares) == 1 and not fake.finalizes
        await disconnected_resume(e, row, fake)
        cancelled = await e.manager.action(
            e.uid, row.task_id, "cancel", expected_attempt=row.attempt
        )
        assert cancelled.state == "cancelled"
        await asyncio.wait_for(fake.cancelled.wait(), timeout=3)
        await until(lambda: not e.manager._verification_tasks and not e.manager._finalizers)
        fake.release.set()
        await asyncio.sleep(0)
        assert not fake.published
        assert e.repos.task_repo.get(row.task_id).state == "cancelled"
    finally:
        fake.release.set()
        await e.manager.stop()
        await e.channels.stop()


async def test_retry_joins_old_verifier_and_old_resume_cannot_write_new_attempt(setup, tmp_path):
    e = setup
    fake = GateCoding(ignore_cancel=True)
    e.manager._coding_service = fake
    await e.channels.start()
    try:
        row = await paused_coding_task(e, tmp_path / "project")
        await disconnected_resume(e, row, fake)
        await e.manager.action(e.uid, row.task_id, "cancel", expected_attempt=row.attempt)
        await asyncio.wait_for(fake.cancelled.wait(), timeout=3)
        retry = asyncio.create_task(
            e.manager.action(e.uid, row.task_id, "retry", expected_attempt=row.attempt)
        )
        await asyncio.sleep(0.05)
        assert not retry.done()
        assert e.repos.task_repo.get(row.task_id).state == "cancelled"
        fake.release.set()
        queued = await asyncio.wait_for(retry, timeout=3)
        assert queued.state == "queued" and not fake.published
        assert e.repos.task_repo.claim(row.task_id)
        next_row = e.repos.task_repo.get(row.task_id)
        assert next_row.attempt == row.attempt + 1
        marker = {"phase": "prepared", "generation": next_row.attempt}
        assert e.repos.task_dispatch_repo.update_coding(
            row.task_id, marker, expected_attempt=next_row.attempt
        )
        await e.manager.complete_waiting_turn(
            agent_id=row.agent_id,
            user_id=row.user_id,
            thread_id=row.thread_id,
            failed=False,
            paused=False,
            output="late old result",
            attempts={row.task_id: row.attempt},
        )
        current = e.repos.task_repo.get(row.task_id)
        assert current.state == "running" and current.attempt == next_row.attempt
        assert "late old result" not in current.result
        assert e.repos.task_dispatch_repo.get(row.task_id)["coding_run"] == marker
        assert len(fake.finalizes) == 1 and not fake.published
    finally:
        fake.release.set()
        await e.manager.stop()
        await e.channels.stop()


@pytest.mark.parametrize("cancel_in_claim", [False, True])
async def test_cancelled_claim_never_prepares_coding_or_starts_a_model(
    setup, tmp_path, monkeypatch, cancel_in_claim
):
    e = setup
    fake = GateCoding()
    e.manager._coding_service = fake
    row = await coding_task(e, tmp_path / "project")
    if cancel_in_claim:
        claim = e.repos.task_repo.claim

        def racing(task_id):
            changed = claim(task_id)
            if changed:
                current = e.repos.task_repo.get(task_id)
                assert e.repos.task_repo.transition(
                    task_id,
                    expected={"running"},
                    expected_attempt=current.attempt,
                    state="cancelled",
                    action="cancel",
                )
            return changed

        monkeypatch.setattr(e.repos.task_repo, "claim", racing)
        await e.manager.process_once()
        assert row.task_id not in e.manager._running
    else:
        assert e.repos.task_repo.claim(row.task_id)
        await e.manager.action(e.uid, row.task_id, "cancel")
        await e.manager._execute(row.task_id)
    assert e.repos.task_repo.get(row.task_id).state == "cancelled"
    assert not fake.prepares and not fake.finalizes and not fake.published
    assert not e.processor.received
    e.agents.start.assert_not_awaited()


async def test_return_retry_pages_past_twenty_busy_origins(setup):
    e = setup
    busy = set()
    for i in range(21):
        origin_agent = f"origin-{i}"
        e.repos.agent_repo.create(agent_id=origin_agent, user_id=e.uid, name=origin_agent)
        origin = await e.gateway.thread_registry.get_or_create(
            agent_id=origin_agent,
            user_id=e.uid,
            channel_type="dashboard",
            channel_subject_id="origin",
        )
        if i < 20:
            busy.add(origin)
        task_id = f"return-{i}"
        e.repos.task_repo.enqueue(
            [
                {
                    "task_id": task_id,
                    "user_id": e.uid,
                    "agent_id": "b",
                    "title": task_id,
                    "prompt": "fixture result",
                    "dispatch": {"origin_agent_id": origin_agent, "origin_thread_id": origin},
                }
            ]
        )
        assert e.repos.task_repo.claim(task_id)
        assert e.repos.task_repo.transition(
            task_id,
            expected={"running"},
            state="completed",
            action="completed",
            fields={"result": "verified"},
        )
    attempted = []

    class BusyOrigins:
        async def deliver(self, row):
            attempted.append(row.task_id)
            context = e.repos.task_dispatch_repo.get(row.task_id)
            if context["origin_thread_id"] in busy:
                return False
            assert e.repos.task_dispatch_repo.mark_returned(
                row.task_id,
                row.attempt,
                state=row.state,
                event_id=context["current_event_id"],
                expected_attempt=row.attempt,
            )
            return True

    e.manager._return_service = BusyOrigins()
    await e.manager._retry_returns()
    assert "return-20" not in attempted
    await e.manager._retry_returns()
    assert attempted[-1] == "return-20"
    pending = e.repos.task_dispatch_repo.pending_returns()
    assert len(pending) == 20 and all(item["task_id"] != "return-20" for item in pending)


async def test_verification_waits_for_an_admitted_turn_and_rejects_new_writes(setup, tmp_path):
    e = setup
    fake = GateCoding()
    e.manager._coding_service = fake
    await e.channels.start()
    held = None
    verification = None
    release_turn = asyncio.Event()
    turn_entered = asyncio.Event()
    write_finished = False
    try:
        row = await paused_coding_task(e, tmp_path / "project")
        assert e.repos.task_repo.transition(
            row.task_id, expected={"waiting"}, state="running", action="member_resumed"
        )
        row = e.repos.task_repo.get(row.task_id)

        async def admitted_turn():
            nonlocal write_finished
            turn_entered.set()
            await release_turn.wait()
            write_finished = True

        held = asyncio.create_task(
            e.channels.run_in_session(
                e.gateway.dashboard_channel_id, f"thread:{row.thread_id}", admitted_turn
            )
        )
        await asyncio.wait_for(turn_entered.wait(), timeout=3)
        verification = asyncio.create_task(e.manager._finish_coding(row))
        await until(
            lambda: (
                e.repos.task_dispatch_repo.get(row.task_id)["coding_run"].get("phase")
                == "verifying"
            )
        )
        await asyncio.sleep(0.05)
        assert not fake.entered.is_set() and not write_finished
        message = InboundMessage(
            channel_id=e.gateway.dashboard_channel_id,
            channel_type="dashboard",
            tenant_id=row.agent_id,
            channel_subject=ChannelSubject(subject_id=str(e.uid), chat_type="dm"),
            content=[TextContent(text="another write must not start")],
            metadata={
                "thread_id": row.thread_id,
                "session_key": e.gateway.thread_registry.get_thread(row.thread_id).session_key,
            },
        )
        with pytest.raises(OctopError):
            await e.manager.admit_turn(message)
        assert len(e.processor.received) == 1
        release_turn.set()
        await held
        await asyncio.wait_for(fake.entered.wait(), timeout=3)
        assert write_finished
        fake.release.set()
        failed, _ = await asyncio.wait_for(verification, timeout=3)
        assert not failed and fake.published == [row.task_id]
    finally:
        release_turn.set()
        fake.release.set()
        for job in [held, verification]:
            if job is not None and not job.done():
                job.cancel()
        await asyncio.gather(
            *(job for job in [held, verification] if job is not None), return_exceptions=True
        )
        await e.manager.stop()
        await e.channels.stop()
