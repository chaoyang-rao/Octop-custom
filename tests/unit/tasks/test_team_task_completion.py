"""A task waits for real inbox/member-HITL/host-reply lifecycles without paid models."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage
from octop_harness.request import ChatRequest
from octop_harness.teams.inbox import HarnessAgentInboxManager
from octop_harness.teams.util import derive_peer_thread_id
from tests.unit.tasks.test_task_manager import enqueue, settled
from tests.unit.tasks.test_task_manager import setup as setup

from octop.api.routers.chat.routes import iter_dashboard_hitl_resume_sse
from octop.infra.agents.teams.jobs import TeamJobTracker
from octop.infra.agents.teams.team_manager import TeamManager
from octop.infra.gateway.hitl.coordinator import HitlChannelCoordinator


@pytest.mark.asyncio
async def test_member_approval_handoff_waits_for_member_and_host_wrapup(setup):
    e = setup
    await e.channels.start()
    with e.db.connect() as conn:
        conn.execute("UPDATE agents SET kind='team' WHERE agent_id='a'")
    e.agents.get_row = e.repos.agent_repo.get
    e.agents.teams = SimpleNamespace(jobs=TeamJobTracker())
    e.agents.get_agent = lambda _: SimpleNamespace(
        aget_history=AsyncMock(return_value=[AIMessage(content="member result")])
    )
    coordinator = HitlChannelCoordinator()
    coordinator.set_task_binding_resolver(e.manager.task_binding)
    team = TeamManager(
        agent_manager=e.agents,
        thread_registry=e.gateway.thread_registry,
        user_repo=e.repos.user_repo,
        gateway=e.gateway,
        hitl_coordinator=coordinator,
    )
    e.processor.teams = team
    e.processor.hitl_coordinator = coordinator

    async def member_stream(agent_id, request):
        assert agent_id == "b"
        yield {"type": "token", "content": "checking "}
        yield {
            "type": "hitl_required",
            "request": {
                "action_requests": [{"name": "execute", "args": {"command": "not executed"}}],
                "review_configs": [
                    {"action_name": "execute", "allowed_decisions": ["approve", "reject"]}
                ],
            },
        }

    async def member_resume(agent_id, thread_id, decisions):
        assert agent_id == "b" and decisions == [{"type": "approve"}]
        yield {"type": "token", "content": "member result "}

    e.agents.stream = member_stream
    e.agents.resume_hitl = member_resume
    host_started = asyncio.Event()
    host_release = asyncio.Event()

    async def call_host(agent_id, request):
        assert agent_id == "a"
        host_started.set()
        await host_release.wait()
        return {"messages": [AIMessage(content="host summary")]}

    async def invoke(msg):
        return await team.stream_peer_to_room(
            ChatRequest(
                messages=msg.message,
                thread_id=derive_peer_thread_id(msg.source_thread_id, msg.target_agent_id),
                agent_id=msg.target_agent_id,
                user=str(e.uid),
            ),
            room_thread_id=msg.source_thread_id,
            speaker_id=msg.target_agent_id,
        )

    inbox = HarnessAgentInboxManager(call_agent=call_host, processor=team, invoke_target=invoke)
    e.agents.harness_manager = SimpleNamespace(team=SimpleNamespace(inbox=inbox))

    async def host_dispatch(message):
        e.processor.received.append(message)
        inbox.enqueue(
            target_agent_id="b",
            source_agent_id="a",
            source_thread_id=message.metadata["thread_id"],
            message="review",
            user_id=e.uid,
            metadata={"session_key": message.metadata["session_key"]},
        )
        yield {"type": "token", "content": "dispatched "}
        yield {"type": "done"}

    e.processor.iter_turn_chunks = host_dispatch
    try:
        task = await enqueue(e)
        await e.manager.process_once()
        pending = None
        for _ in range(300):
            row = e.repos.task_repo.get(task.id)
            if row.thread_id:
                pending = coordinator.store.resolve_pending_for_thread(
                    row.thread_id, agent_id="a", user_id=e.uid
                )
            if pending and row.state == "waiting":
                break
            await asyncio.sleep(0.01)
        assert pending and pending.resume_agent_id == "b"
        assert pending.task_id == task.id and pending.task_attempt == 1
        lease = await e.manager.bind_resume(
            agent_id="a", user_id=e.uid, thread_id=row.thread_id, pending=pending
        )
        assert e.repos.task_repo.get(task.id).state == "waiting"
        # This is the real HTTP early-return path: it delivers to the member,
        # rather than incorrectly resuming the team-host graph or finishing the task.
        frames = [
            item
            async for item in iter_dashboard_hitl_resume_sse(
                server=SimpleNamespace(
                    app_runtime=SimpleNamespace(gateway=e.gateway), task_manager=e.manager
                ),
                processor=e.processor,
                hitl_coordinator=coordinator,
                agent_id="a",
                thread_id=row.thread_id,
                user_id=e.uid,
                decisions=[{"type": "approve"}],
                pending=pending,
                session_key=e.gateway.thread_registry.get_thread(row.thread_id).session_key,
                channel_type="dashboard",
                locale="en",
                is_disconnected=AsyncMock(return_value=False),
                resume_lease=lease,
            )
        ]
        assert frames
        await asyncio.wait_for(host_started.wait(), timeout=2)
        assert e.repos.task_repo.get(task.id).state in {"running", "waiting"}
        assert not e.manager._running[task.id].done()
        host_release.set()
        await settled(e.manager)
        finished = e.repos.task_repo.get(task.id)
        assert finished.state == "completed"
        assert "member result" in finished.result and "host summary" in finished.result
    finally:
        host_release.set()
        await e.manager.stop()
        await inbox.shutdown()
        await e.channels.stop()
