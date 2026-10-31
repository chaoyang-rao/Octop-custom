"""Approval responses captured before body start cannot revive a cancelled attempt."""

from __future__ import annotations

import asyncio
import contextlib
from types import SimpleNamespace

import pytest
from starlette.responses import StreamingResponse
from tests.unit.tasks.test_task_manager import enqueue, settled
from tests.unit.tasks.test_task_manager import setup as setup

from octop.infra.errors import OctopError
from octop.infra.gateway.hitl.coordinator import HitlChannelCoordinator, HitlStreamContext


@pytest.mark.asyncio
async def test_delayed_response_body_cannot_resume_after_cancel_and_retry(setup):
    e = setup
    await e.channels.start()
    try:
        task = await enqueue(e)
        e.processor.pause = True
        await e.manager.process_once()
        await settled(e.manager)
        row = e.repos.task_repo.get(task.id)
        coordinator = HitlChannelCoordinator()
        coordinator.set_task_binding_resolver(e.manager.task_binding)
        e.processor.hitl_coordinator = coordinator
        pending = coordinator.register_from_request(
            {"action_requests": [{"name": "execute", "args": {}}]},
            ctx=HitlStreamContext(
                thread_id=row.thread_id,
                agent_id="a",
                user_id=e.uid,
                session_key=e.gateway.thread_registry.get_thread(row.thread_id).session_key,
                channel_type="dashboard",
            ),
        )
        assert pending.task_id == task.id and pending.task_attempt == row.attempt
        lease = await e.manager.bind_resume(
            agent_id="a", user_id=e.uid, thread_id=row.thread_id, pending=pending
        )
        assert lease and lease.attempts == {task.id: 1}
        executed = []

        async def body():
            try:
                await lease.enter()
                executed.append("external tool must not execute")
                yield "data: complete\n\n"
            finally:
                lease.close()
                await e.manager.complete_waiting_turn(
                    agent_id="a",
                    user_id=e.uid,
                    thread_id=row.thread_id,
                    failed=False,
                    paused=False,
                    output="old output",
                    attempts=lease.attempts,
                )

        response = StreamingResponse(body())
        # The response object exists, but nobody has started its async body.
        await e.manager.action(e.uid, task.id, "cancel")
        assert pending.status == "expired" and lease.cancelled
        await e.manager.action(e.uid, task.id, "retry")
        e.processor.gate = asyncio.Event()
        await e.manager.process_once()
        for _ in range(100):
            if len(e.processor.received) == 2:
                break
            await asyncio.sleep(0.005)
        assert e.repos.task_repo.get(task.id).attempt == 2
        with pytest.raises(OctopError):
            _ = [frame async for frame in response.body_iterator]
        assert executed == []
        assert e.repos.task_repo.get(task.id).state == "running"
        assert "old output" not in e.repos.task_repo.get(task.id).result
        e.processor.gate.set()
        await settled(e.manager)
    finally:
        await e.manager.stop()
        await e.channels.stop()


@pytest.mark.asyncio
async def test_attached_approval_stream_is_cancelled_before_retry(setup):
    e = setup
    await e.channels.start()
    try:
        task = await enqueue(e)
        e.processor.pause = True
        await e.manager.process_once()
        await settled(e.manager)
        row = e.repos.task_repo.get(task.id)
        coordinator = HitlChannelCoordinator()
        coordinator.set_task_binding_resolver(e.manager.task_binding)
        e.processor.hitl_coordinator = coordinator
        pending = coordinator.register_from_request(
            {"action_requests": [{"name": "execute", "args": {}}]},
            ctx=HitlStreamContext(
                thread_id=row.thread_id,
                agent_id="a",
                user_id=e.uid,
                session_key=e.gateway.thread_registry.get_thread(row.thread_id).session_key,
                channel_type="dashboard",
            ),
        )
        assert pending.task_id == task.id and pending.task_attempt == row.attempt
        lease = await e.manager.bind_resume(
            agent_id="a", user_id=e.uid, thread_id=row.thread_id, pending=pending
        )
        entered = asyncio.Event()
        blocked = asyncio.Event()
        executed = []

        async def stream():
            try:
                await lease.enter()
                entered.set()
                await blocked.wait()
                executed.append("must not run")
            finally:
                lease.close()

        running = asyncio.create_task(stream())
        await asyncio.wait_for(entered.wait(), timeout=2)
        await e.manager.action(e.uid, task.id, "cancel")
        await e.manager.action(e.uid, task.id, "retry")
        assert running.done() and running.cancelled()
        assert executed == [] and e.repos.task_repo.get(task.id).state == "queued"
    finally:
        await e.manager.stop()
        await e.channels.stop()


@pytest.mark.asyncio
async def test_real_endpoint_response_captured_before_cancel_never_resumes_new_attempt(setup):
    from fastapi import FastAPI, Request

    from octop.api.routers.chat.models import HitlResumeBody
    from octop.api.routers.chat.routes import resume_hitl
    from octop.infra.users.identity import User

    e = setup
    await e.channels.start()
    called = []
    e.agents.get_row = e.repos.agent_repo.get
    try:
        task = await enqueue(e)
        e.processor.pause = True
        await e.manager.process_once()
        await settled(e.manager)
        row = e.repos.task_repo.get(task.id)
        coordinator = HitlChannelCoordinator()
        coordinator.set_task_binding_resolver(e.manager.task_binding)
        e.processor.hitl_coordinator = coordinator
        pending = coordinator.register_from_request(
            {"action_requests": [{"name": "execute", "args": {}}]},
            ctx=HitlStreamContext(
                thread_id=row.thread_id,
                agent_id="a",
                user_id=e.uid,
                session_key=e.gateway.thread_registry.get_thread(row.thread_id).session_key,
                channel_type="dashboard",
            ),
        )

        async def graph_resume(**kwargs):
            called.append("external tools could begin here")
            yield {"type": "done"}

        e.processor.iter_hitl_resume_chunks = graph_resume
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/agents/a/chat/hitl/resume",
                "headers": [(b"accept-language", b"en")],
                "app": FastAPI(),
            }
        )
        server = SimpleNamespace(
            app_runtime=SimpleNamespace(gateway=e.gateway, agent_registry=e.agents),
            task_manager=e.manager,
        )
        response = await resume_hitl(
            agent_id="a",
            body=HitlResumeBody(
                thread_id=row.thread_id,
                pending_id=pending.pending_id,
                decisions=[{"type": "approve"}],
            ),
            request=request,
            user=User(e.uid, "owner", "admin", "Owner"),
            server=server,
        )
        # No body iteration has occurred. The endpoint has already captured the old lease.
        await e.manager.action(e.uid, task.id, "cancel")
        await e.manager.action(e.uid, task.id, "retry")
        e.processor.gate = asyncio.Event()
        await e.manager.process_once()
        for _ in range(100):
            if len(e.processor.received) == 2:
                break
            await asyncio.sleep(0.005)
        with contextlib.suppress(OctopError):
            _ = [piece async for piece in response.body_iterator]
        assert called == [] and pending.status == "expired"
        assert e.repos.task_repo.get(task.id).state == "running"
        assert e.repos.task_repo.get(task.id).attempt == 2
        e.processor.gate.set()
        await settled(e.manager)
    finally:
        await e.manager.stop()
        await e.channels.stop()
