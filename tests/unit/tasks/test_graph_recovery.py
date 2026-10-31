"""Actual LangGraph/HITL + local fake ACP recovery, without a paid CLI/model."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from octop_gateway.models import ChannelSubject, InboundMessage, TextContent
from tests.unit.agents.native_cli.test_graph_acp import (
    Settings,
    config,
    events,
    graph_for,
    runtime_for,
)
from tests.unit.tasks.test_task_manager import settled
from tests.unit.tasks.test_task_manager import setup as setup

from octop.config import OctopConfig
from octop.infra.agents.native_cli.config import NativeCLIError
from octop.infra.gateway.hitl.coordinator import HitlChannelCoordinator, HitlStreamContext
from octop.infra.tasks.manager import TaskManager
from octop.infra.tasks.models import TaskCreate


def real_graph_ingress(e, current):
    async def turn(message):
        e.processor.received.append(message)
        graph = current[0]
        result = await graph.ainvoke(
            {"messages": [HumanMessage(content=message.text)]}, config=config()
        )
        interrupts = result.get("__interrupt__") or []
        if interrupts:
            record = e.processor.hitl_coordinator.register_from_request(
                interrupts[0].value,
                ctx=HitlStreamContext(
                    thread_id=message.metadata["thread_id"],
                    agent_id="agent1",
                    user_id=e.uid,
                    session_key=message.metadata["session_key"],
                    channel_type="dashboard",
                ),
            )
            yield {
                "type": "hitl_required",
                "request": interrupts[0].value,
                "pending_id": record.pending_id,
            }
        else:
            yield {"type": "token", "content": str(result["messages"][-1].content)}
        yield {"type": "done"}

    return turn


async def prepare(e, tmp_path):
    e.repos.agent_repo.create(agent_id="agent1", user_id=e.uid, name="Native")
    e.gateway.thread_registry.create_thread(
        agent_id="agent1",
        user_id=e.uid,
        channel_type="dashboard",
        session_key="agent1:dashboard:1:dm",
        thread_id="thread1",
    )
    with e.db.connect() as conn:
        conn.execute(
            "UPDATE threads SET project_path=?,project_name='preserved' WHERE thread_id='thread1'",
            (str(tmp_path),),
        )
    settings = Settings()
    runtime, marker = runtime_for(tmp_path, mode="permission", settings=settings)
    checkpoint = InMemorySaver()
    graph = graph_for(runtime, [], native_permission=True, checkpoint=checkpoint)
    current = [graph]
    e.agents._repos = e.repos
    e.agents.native_cli = runtime
    e.agents.native_execution_ref = lambda aid: (
        "native_cli_agent1/session" if aid == "agent1" else None
    )
    e.agents.get_agent = lambda _: SimpleNamespace(graph=current[0])
    coordinator = HitlChannelCoordinator()
    coordinator.set_task_binding_resolver(e.manager.task_binding)
    e.processor.hitl_coordinator = coordinator
    e.processor.iter_turn_chunks = real_graph_ingress(e, current)
    task = await e.manager.enqueue(
        e.uid,
        TaskCreate(
            agent_id="agent1",
            title="native recovery",
            prompt="controlled action",
            thread_id="thread1",
        ),
    )
    await e.manager.process_once()
    await settled(e.manager)
    assert e.repos.task_repo.get(task.id).state == "waiting"
    return task, runtime, marker, settings, checkpoint, current, coordinator


async def restarted(e, tmp_path, settings, checkpoint, current):
    runtime, marker = runtime_for(tmp_path, mode="permission", settings=settings)
    current[0] = graph_for(runtime, [], native_permission=True, checkpoint=checkpoint)
    e.agents.native_cli = runtime
    manager = TaskManager(
        repos=e.repos,
        gateway=e.gateway,
        agent_manager=e.agents,
        config=OctopConfig(default_timezone="Asia/Shanghai"),
    )
    coordinator = HitlChannelCoordinator()
    coordinator.set_task_binding_resolver(manager.task_binding)
    e.processor.hitl_coordinator = coordinator
    e.channels.get_channel(e.gateway.dashboard_channel_id).set_task_admission(manager.admit_turn)
    await manager.start()
    return manager, runtime, marker, coordinator


@pytest.mark.asyncio
async def test_rebuilt_old_graph_interrupt_remains_bound_and_requires_explicit_retry(
    setup, tmp_path
):
    e = setup
    await e.channels.start()
    manager = None
    runtime2 = None
    task, runtime, marker, settings, checkpoint, current, coordinator = await prepare(e, tmp_path)
    try:
        old_state = await current[0].aget_state(config())
        request = old_state.tasks[0].interrupts[0].value
        await runtime.aclose()
        manager, runtime2, marker, coordinator = await restarted(
            e, tmp_path, settings, checkpoint, current
        )
        assert e.repos.task_repo.get(task.id).state == "interrupted"
        # Opening this chat and sending a plain WS turn cannot strip Task
        # metadata to resume the interrupted Graph as an unmanaged chat.
        with pytest.raises(Exception) as ordinary_turn:
            await manager.admit_turn(
                InboundMessage(
                    channel_id=e.gateway.dashboard_channel_id,
                    channel_type="dashboard",
                    tenant_id="agent1",
                    channel_subject=ChannelSubject(subject_id=str(e.uid), chat_type="dm"),
                    content=[TextContent(text="continue")],
                    metadata={"thread_id": "thread1"},
                )
            )
        assert getattr(ordinary_turn.value, "status", None) == 409
        rebuilt = coordinator.register_from_request(
            request,
            ctx=HitlStreamContext(
                thread_id="thread1",
                agent_id="agent1",
                user_id=e.uid,
                session_key="agent1:dashboard:1:dm",
                channel_type="dashboard",
            ),
        )
        assert rebuilt.task_id == task.id and rebuilt.task_attempt == 1
        with pytest.raises(Exception) as rejected:
            await manager.bind_resume(
                agent_id="agent1", user_id=e.uid, thread_id="thread1", pending=rebuilt
            )
        assert getattr(rejected.value, "status", None) == 409
        context = await runtime2.context_for("agent1", "thread1", e.uid)
        with pytest.raises(NativeCLIError) as interrupted:
            await runtime2.conversation(context, [])
        assert interrupted.value.code == "interrupted"
        assert not any(event["event"] == "action" for event in events(marker))
        await manager.action(e.uid, task.id, "retry")
        for _ in range(300):
            row = e.repos.task_repo.get(task.id)
            if row.attempt == 2 and row.state == "waiting":
                break
            await asyncio.sleep(0.01)
        assert row.attempt == 2 and row.state == "waiting"
        assert rebuilt.status == "expired"
        assert not any(event["event"] == "action" for event in events(marker))
        state = await current[0].aget_state(config())
        assert any(
            isinstance(message, ToolMessage) and message.status == "error"
            for message in state.values["messages"]
        )
        assert e.repos.thread_repo.get("thread1").project_path == str(tmp_path)
    finally:
        if manager:
            await manager.stop()
        await e.manager.stop()
        if runtime2:
            await runtime2.aclose()
        await runtime.aclose()
        await e.channels.stop()


@pytest.mark.asyncio
async def test_retry_does_not_reuse_previously_approved_native_permission(
    setup, tmp_path, monkeypatch
):
    e = setup
    await e.channels.start()
    manager = None
    runtime2 = None
    task, runtime, marker, settings, checkpoint, current, coordinator = await prepare(e, tmp_path)
    save = runtime._save

    async def lost_final_checkpoint(session, state):
        if state == "idle" and any(event["event"] == "action" for event in events(marker)):
            raise RuntimeError("simulated process loss before final persistence")
        await save(session, state)

    monkeypatch.setattr(runtime, "_save", lost_final_checkpoint)
    try:
        # Real approval reaches the fake ACP once; the process is then lost before
        # its final idle state can be committed, leaving a working/waiting record.
        with pytest.raises(RuntimeError, match="simulated process loss"):
            await current[0].ainvoke(
                Command(resume={"decisions": [{"type": "approve"}]}), config=config()
            )
        assert sum(event["event"] == "action" for event in events(marker)) == 1
        await runtime.aclose()
        manager, runtime2, marker, coordinator = await restarted(
            e, tmp_path, settings, checkpoint, current
        )
        await manager.action(e.uid, task.id, "retry")
        for _ in range(300):
            row = e.repos.task_repo.get(task.id)
            if row.attempt == 2 and row.state == "waiting":
                break
            await asyncio.sleep(0.01)
        assert row.attempt == 2 and row.state == "waiting"
        assert sum(event["event"] == "action" for event in events(marker)) == 1
        pending = coordinator.store.resolve_pending_for_thread(
            "thread1", agent_id="agent1", user_id=e.uid
        )
        assert pending and pending.task_attempt == 2
        # A new explicit approval, not the old ToolMessage, is necessary.
        await current[0].ainvoke(
            Command(resume={"decisions": [{"type": "approve"}]}), config=config()
        )
        assert sum(event["event"] == "action" for event in events(marker)) == 2
    finally:
        if manager:
            await manager.stop()
        await e.manager.stop()
        if runtime2:
            await runtime2.aclose()
        await runtime.aclose()
        await e.channels.stop()
