"""Real queue, history and coordination with fake model responses only."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from langchain.agents.middleware import ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from octop_gateway.models import ChannelSubject, InboundMessage, TextContent
from tests.unit.tasks.test_task_manager import settled
from tests.unit.tasks.test_task_manager import setup as setup
from tests.unit.tasks.test_task_rooms import enqueue, finish, room_messages, save_turn
from tests.unit.tasks.test_task_rooms import room_env as room_env

from octop.infra.agents.middleware.task_dispatch import TaskDispatchMiddleware
from octop.infra.errors import OctopError
from octop.infra.tasks.models import CodingTaskSpec, TaskCreate
from octop.infra.tasks.rooms import TaskRooms, discussion_messages
from octop.infra.tasks.scope import CoordinatorContext, coordinator_scope


async def test_legacy_review_is_tagged_and_survives_checkpoint_compaction(room_env, monkeypatch):
    e = room_env
    e.archive.enabled = False
    await enqueue(e)
    await enqueue(e, "c")
    context = CoordinatorContext(
        scope_id=e.scope_id, user_id=e.uid, origin_agent_id="a", origin_thread_id=e.origin
    )
    monkeypatch.setattr(
        "octop.infra.agents.middleware.task_dispatch.runtime_config",
        lambda _r: {"configurable": {"agent_id": "a", "thread_id": e.origin, "user": str(e.uid)}},
    )
    middleware = TaskDispatchMiddleware(e.agents.teams, lambda: e.manager)
    original = AIMessage("Legacy actual primary review", id="legacy-review")
    with coordinator_scope(context):
        response = middleware.wrap_model_call(
            SimpleNamespace(), lambda _r: ModelResponse(result=[original])
        )
    assert "octop_task_scope_id" not in original.additional_kwargs
    assert response.result[0].additional_kwargs["octop_task_scope_id"] == e.scope_id
    await e.harness.aappend_messages(e.origin, response.result)
    await e.manager._rooms.process()
    room = e.repos.task_coordination_repo.room(e.scope_id)
    assert any(item.content == original.content for item in room_messages(e, room))
    e.harness.messages[e.origin] = [
        AIMessage(
            "Review after compaction",
            id="new-review",
            additional_kwargs={"octop_task_scope_id": e.scope_id},
        )
    ]
    e.harness.version += 1
    await TaskRooms(e.manager).process()
    assert any(item.content == "Review after compaction" for item in room_messages(e, room))
    assert all(item.content != "old reply" for item in room_messages(e, room))


async def test_real_queue_records_member_results_then_primary_review(room_env):
    e = room_env
    first = await enqueue(e)
    second = await enqueue(e, "c")

    async def worker_turn(message):
        e.processor.received.append(message)
        text = f"Real recorded result from {message.tenant_id}"
        await save_turn(
            e,
            message.tenant_id,
            message.metadata["thread_id"],
            [
                HumanMessage(message.text, id="user-" + message.metadata["task_id"]),
                AIMessage(text, id="answer-" + message.metadata["task_id"]),
            ],
        )
        yield {"type": "token", "content": text}
        yield {"type": "done"}

    e.processor.iter_turn_chunks = worker_turn
    await e.manager.process_once()
    await settled(e.manager)
    assert all(e.repos.task_repo.get(row.task_id).state == "completed" for row in [first, second])
    assert {
        call.kwargs["speaker_id"] for call in e.processor.teams.relay_task_chunk.await_args_list
    } == {"b", "c"}

    async def review(_agents, _gateway, scope, prompt, *, user_input):
        assert "Real recorded result from b" in prompt and "Real recorded result from c" in prompt
        context = CoordinatorContext(
            scope_id=scope["scope_id"],
            user_id=e.uid,
            origin_agent_id="a",
            origin_thread_id=e.origin,
            active_signature=scope["active_signature"],
        )
        with coordinator_scope(context):
            await save_turn(
                e,
                "a",
                e.origin,
                [
                    AIMessage(
                        "Actual combined review",
                        id="review-end-to-end",
                        additional_kwargs={"octop_task_scope_id": e.scope_id},
                    )
                ],
            )
            await e.manager.decide_coordination(
                e.uid, e.scope_id, decision="ready", summary="Actual combined review", question=""
            )
        return {"failed": False, "paused": False, "output": "Actual combined review"}

    e.manager._coordinator._invoke = review
    await e.manager.process_once()
    assert len(e.manager._coordinator.jobs) == 1
    await asyncio.gather(*e.manager._coordinator.jobs.values())
    await e.manager._rooms.process()
    room = e.repos.task_coordination_repo.room(e.scope_id)
    messages = room_messages(e, room)
    assert {
        message.additional_kwargs["speaker_agent_id"]
        for message in messages
        if str(message.content).startswith("Real recorded result")
    } == {"b", "c"}
    assert any(
        message.content == "Actual combined review"
        and message.additional_kwargs["speaker_agent_id"] == "a"
        for message in messages
    )
    assert e.repos.task_coordination_repo.get(e.scope_id)["decision"] == "ready"
    assert len(e.created) == 1 and len(e.processor.received) == 2


async def test_group_input_cannot_grant_publication_or_bypass_plan_mode(
    room_env, monkeypatch, tmp_path
):
    e = room_env
    await enqueue(e)
    await enqueue(e, "c")
    room = e.repos.task_coordination_repo.room(e.scope_id)
    e.repos.task_coordination_repo.require_user(e.scope_id, "Please clarify")
    message = InboundMessage(
        channel_id=e.gateway.dashboard_channel_id,
        channel_type="dashboard",
        tenant_id=room["agent_id"],
        channel_subject=ChannelSubject(subject_id=str(e.uid), chat_type="dm"),
        content=[TextContent(text="Planning only")],
        metadata={"client_message_id": "plan-input", "conversation_mode": "plan"},
    )
    await e.manager.record_room_input(message, user_id=e.uid, thread_id=room["thread_id"])
    assert e.repos.task_coordination_repo.get(e.scope_id)["state"] == "needs_user"
    monkeypatch.setattr(e.manager, "_validate_coding", lambda *_: None)
    with pytest.raises(OctopError) as error:
        await e.manager.enqueue(
            e.uid,
            TaskCreate(
                agent_id="c",
                title="code",
                prompt="code",
                origin_thread_id=room["thread_id"],
                coding=CodingTaskSpec(
                    project_path=str(tmp_path), test_commands=["echo test"], publish_pr=True
                ),
            ),
            coordination={
                "source_message_id": "pub-input",
                "goal_text": "Try publishing",
                "scope_id": "not-authority",
            },
        )
    assert error.value.details["task_reason"] == "coordination_publish"
    assert e.repos.task_coordination_repo.get(e.scope_id)["resume_seq"] == 0


def test_tool_pairs_are_namespaced_for_provider_content_blocks():
    source = [
        AIMessage(
            content=[{"type": "tool_use", "id": "call-1", "name": "inspect", "input": {}}],
            id="step",
            tool_calls=[{"id": "call-1", "name": "inspect", "args": {}}],
        ),
        ToolMessage("evidence", id="result", tool_call_id="call-1"),
    ]
    first = discussion_messages(source, prefix="a" * 150, speaker_id="b", allowed_speakers={"b"})
    second = discussion_messages(source, prefix="c" * 150, speaker_id="c", allowed_speakers={"c"})
    identifier = first[0].tool_calls[0]["id"]
    assert len(identifier) < 64 and identifier != second[0].tool_calls[0]["id"]
    assert first[0].content[0]["id"] == identifier == first[1].tool_call_id


async def test_room_input_is_not_replayed_as_a_second_user_message(room_env):
    e = room_env
    first = await enqueue(e)
    second = await enqueue(e, "c")
    await finish(e, first)
    await finish(e, second)
    await e.manager._retry_returns()
    room = e.repos.task_coordination_repo.room(e.scope_id)
    await save_turn(
        e, room["agent_id"], room["thread_id"], [HumanMessage("Use CSV", id="real-room-user")]
    )
    e.repos.task_coordination_repo.require_user(e.scope_id, "Which format?")
    message = InboundMessage(
        channel_id=e.gateway.dashboard_channel_id,
        channel_type="dashboard",
        tenant_id=room["agent_id"],
        channel_subject=ChannelSubject(subject_id=str(e.uid), chat_type="dm"),
        content=[TextContent(text="Use CSV")],
        metadata={"client_message_id": "real-room-user"},
    )
    await e.manager.record_room_input(message, user_id=e.uid, thread_id=room["thread_id"])
    seen = []

    async def review(_a, _g, scope, prompt, *, user_input):
        seen.append(user_input)
        assert "Use CSV" in prompt
        context = CoordinatorContext(
            scope_id=e.scope_id,
            user_id=e.uid,
            origin_agent_id="a",
            origin_thread_id=e.origin,
            active_signature=scope["active_signature"],
        )
        with coordinator_scope(context):
            await e.manager.decide_coordination(
                e.uid, e.scope_id, decision="ready", summary="CSV confirmed", question=""
            )
        return {"failed": False, "paused": False, "output": "CSV confirmed"}

    e.manager._coordinator._invoke = review
    await e.manager.process_once()
    await asyncio.gather(*e.manager._coordinator.jobs.values())
    assert seen == [""]
    assert not any(
        isinstance(item, HumanMessage) and item.content == "Use CSV"
        for item in e.harness.messages[e.origin]
    )


async def test_group_activity_and_approval_fence_the_automatic_source_turn(room_env, monkeypatch):
    e = room_env
    from octop.infra.tasks.coordinator_turn import CoordinatorTurnBusy, _ready

    await enqueue(e)
    await enqueue(e, "c")
    room = e.repos.task_coordination_repo.room(e.scope_id)
    scope = e.repos.task_coordination_repo.get(e.scope_id)
    context = CoordinatorContext(
        scope_id=e.scope_id, user_id=e.uid, origin_agent_id="a", origin_thread_id=e.origin
    )
    e.agents._repos = e.repos
    pending = SimpleNamespace(pending_thread_ids=lambda **_: [])
    e.processor.hitl_coordinator.store = pending
    monkeypatch.setattr(e.hub, "is_turn_active", lambda tid: tid == room["thread_id"])
    assert not await e.manager._coordinator._source_ready(scope)
    with pytest.raises(CoordinatorTurnBusy):
        await _ready(e.agents, e.gateway, context)
    monkeypatch.setattr(e.hub, "is_turn_active", lambda _: False)
    pending.pending_thread_ids = lambda **kw: (
        [room["thread_id"]] if kw["agent_id"] == room["agent_id"] else []
    )
    with pytest.raises(CoordinatorTurnBusy):
        await _ready(e.agents, e.gateway, context)
    pending.pending_thread_ids = lambda **_: []
    await _ready(e.agents, e.gateway, context)
    assert not e.processor.received


async def test_group_running_status_clears_when_work_stops(room_env):
    e = room_env
    first = await enqueue(e)
    await enqueue(e, "c")
    assert e.repos.task_repo.claim(first.task_id)
    await e.manager._rooms.process()
    room = e.repos.task_coordination_repo.room(e.scope_id)
    assert e.agents.teams.jobs.is_busy(room["agent_id"], "b")
    await e.manager.action(e.uid, first.task_id, "cancel")
    await e.manager._rooms.process()
    assert not e.agents.teams.jobs.is_busy(room["agent_id"], "b")
    assert any("取消" in str(item.content) for item in room_messages(e, room))
