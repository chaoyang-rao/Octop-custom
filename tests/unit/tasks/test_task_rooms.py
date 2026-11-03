"""Task groups use real control-plane/history persistence and no model/network calls."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, message_to_dict
from octop_gateway.models import ChannelSubject, InboundMessage, TextContent
from tests.unit.tasks.test_task_manager import setup as setup
from tests.unit.tasks.test_task_returns import Agents, Harness

from octop.infra.agents.teams.jobs import TeamJobTracker
from octop.infra.history.projection import message_inputs
from octop.infra.history.reader import read_page
from octop.infra.history.service import HistoryArchive
from octop.infra.history.store import HistoryStore
from octop.infra.tasks.models import TaskCreate
from octop.infra.tasks.rooms import TaskRooms, discussion_messages


@pytest.fixture
async def room_env(setup, tmp_path):
    e = setup
    e.repos.agent_repo.create(
        agent_id="c", user_id=e.uid, name="New expert", config_json='{"model":"own"}'
    )
    e.origin = await e.gateway.thread_registry.get_or_create(
        agent_id="a", user_id=e.uid, channel_type="dashboard", channel_subject_id="original"
    )
    e.scope_id = "owned-goal"
    e.harness = Harness(e.origin)
    e.repos.thread_message_repo.mark_projection(e.origin, "pending")
    store = HistoryStore(tmp_path / "room-history.sqlite", identity="room-test")
    archive = HistoryArchive(
        store, e.repos.thread_message_repo, e.repos.trajectory_event_repo, enabled=True
    )
    history_agents = Agents(e.harness, archive)
    e.archive = archive
    e.rosters = {}
    e.created = []

    def primary(_uid):
        return e.repos.agent_repo.get("a")

    def validate(owner, ids):
        ids = list(dict.fromkeys(["a", *ids]))
        if any(
            (row := e.repos.agent_repo.get(aid)) is None
            or row.user_id != owner.id
            or row.kind == "team"
            for aid in ids
        ):
            raise ValueError("foreign or invalid team member")
        return ids

    async def create(spec):
        e.created.append(spec.agent_id)
        e.repos.agent_repo.create(
            agent_id=spec.agent_id,
            user_id=spec.user_id,
            name=spec.name,
            kind=spec.kind,
            template_name=spec.template_name,
            config_json=json.dumps(spec.config),
        )
        e.rosters[spec.agent_id] = list(spec.member_ids)
        return e.repos.agent_repo.get(spec.agent_id)

    e.agents.teams = SimpleNamespace(
        primary_expert_for_user=primary,
        require_primary=primary,
        validate_member_ids=validate,
        member_ids=lambda aid: e.rosters.get(aid, []),
        replace_members=lambda aid, ids: e.rosters.__setitem__(aid, list(ids)),
        jobs=TeamJobTracker(),
    )
    e.agents.create = create
    e.agents.principal_agent_id = lambda aid: (
        "a" if e.repos.agent_repo.get(aid).kind == "team" else aid
    )
    e.agents.get_agent = history_agents.get_agent
    e.agents.try_begin_history_backfill = history_agents.try_begin_history_backfill
    e.agents.end_history_backfill = history_agents.end_history_backfill
    e.agents.history_archive = archive
    e.agents.read_conversation_page = lambda aid, tid, **kw: read_page(
        archive, e.agents, aid, tid, messages=e.repos.thread_message_repo, **kw
    )
    e.processor.teams.relay_task_chunk = AsyncMock()
    e.processor.teams.finish_task_wall = AsyncMock()
    await e.channels.start()
    try:
        yield e
    finally:
        await e.manager.stop()
        await e.channels.stop()
        store.close()


async def enqueue(e, agent="b", *, key=None, origin=None, coordination=None):
    return await e.manager.enqueue(
        e.uid,
        TaskCreate(
            agent_id=agent,
            title=f"Task for {agent}",
            prompt=f"Actual assignment to {agent}",
            origin_thread_id=origin or e.origin,
        ),
        request_key=key,
        coordination=coordination
        or {
            "scope_id": e.scope_id,
            "source_message_id": "original-human",
            "goal_text": "Compare actual findings",
            "initial_user_turn": True,
        },
    )


async def save_turn(e, agent_id, thread_id, messages):
    await e.harness.aappend_messages(thread_id, messages)
    turn = e.archive.begin(agent_id, thread_id)
    e.archive.save_messages(turn, [message_to_dict(message) for message in messages])
    e.archive.finish(turn["id"], "completed")
    e.repos.thread_message_repo.append_if_ready(thread_id, message_inputs(messages))


async def finish(e, row, *, text="Actual expert finding"):
    assert e.repos.task_repo.claim(row.task_id)
    tid = await e.gateway.thread_registry.get_or_create(
        agent_id=row.agent_id,
        user_id=e.uid,
        channel_type="dashboard",
        channel_subject_id=f"task-{row.task_id}",
    )
    assert e.repos.task_repo.transition(
        row.task_id,
        expected={"running"},
        state="running",
        action="thread",
        fields={"thread_id": tid},
    )
    await save_turn(
        e,
        row.agent_id,
        tid,
        [
            HumanMessage(row.prompt, id=f"human-{row.task_id}"),
            AIMessage(
                "Checking evidence",
                id=f"tool-ai-{row.task_id}",
                tool_calls=[{"id": "call-1", "name": "inspect", "args": {}}],
            ),
            ToolMessage("Actual tool evidence", tool_call_id="call-1", id=f"tool-{row.task_id}"),
            AIMessage(text, id=f"reply-{row.task_id}"),
        ],
    )
    assert e.repos.task_repo.transition(
        row.task_id,
        expected={"running"},
        state="completed",
        action="completed",
        fields={"result": text},
    )
    return tid


def room_messages(e, room):
    return e.harness.messages.get(room["thread_id"], [])


async def test_single_expert_stays_private_and_second_expert_creates_one_room(room_env):
    e = room_env
    await enqueue(e, key="one")
    await enqueue(e, key="two")
    assert not e.created
    assert e.repos.task_coordination_repo.room(e.scope_id) is None
    row = await enqueue(e, "c", key="three")
    room = e.repos.task_coordination_repo.room(e.scope_id)
    assert room and len(e.created) == 1
    assert set(e.rosters[room["agent_id"]]) == {"a", "b", "c"}
    assert e.repos.thread_repo.get(room["thread_id"]).user_id == e.uid
    assert (await enqueue(e, "c", key="three")).task_id == row.task_id
    fresh = TaskRooms(e.manager)
    await asyncio.gather(fresh.ensure(e.scope_id), fresh.ensure(e.scope_id))
    assert len(e.created) == 1
    assert (await e.manager.detail(e.uid, row.task_id))["dispatch"]["coordination"]["room"][
        "thread_id"
    ] == room["thread_id"]
    assert e.repos.agent_repo.get("c").config_json == '{"model":"own"}'


async def test_completed_first_reply_is_backfilled_with_real_tool_pairs_and_review(room_env):
    e = room_env
    first = await enqueue(e)
    await finish(e, first)
    await enqueue(e, "c")
    await e.manager._rooms.process()
    room = e.repos.task_coordination_repo.room(e.scope_id)
    messages = room_messages(e, room)
    reply = next(item for item in messages if item.content == "Actual expert finding")
    assert reply.additional_kwargs["speaker_agent_id"] == "b"
    ai = next(item for item in messages if isinstance(item, AIMessage) and item.tool_calls)
    tool = next(item for item in messages if isinstance(item, ToolMessage))
    assert ai.tool_calls[0]["id"] == tool.tool_call_id
    assert tool.tool_call_id != "call-1"
    assert all(item.content != "old reply" for item in messages)
    await save_turn(
        e,
        "a",
        e.origin,
        [
            AIMessage(
                "Actual primary review",
                id="review-1",
                additional_kwargs={"octop_task_scope_id": e.scope_id},
            ),
            AIMessage("Unrelated private reply", id="private-2"),
        ],
    )
    await e.manager._rooms.process()
    assert any(
        item.content == "Actual primary review"
        and item.additional_kwargs["speaker_agent_id"] == "a"
        for item in room_messages(e, room)
    ), (
        e.repos.task_coordination_repo.room_cursor(e.scope_id, e.origin),
        e.repos.thread_message_repo.range_rows(e.origin, 0, 100),
        room_messages(e, room),
    )
    assert all(item.content != "Unrelated private reply" for item in room_messages(e, room))
    before = len(room_messages(e, room))
    await TaskRooms(e.manager).process()
    assert len(room_messages(e, room)) == before
    page = await read_page(
        e.archive,
        e.agents,
        room["agent_id"],
        room["thread_id"],
        limit=100,
        messages=e.repos.thread_message_repo,
    )
    assert "Actual expert finding" in json.dumps(page)
    assert "Unrelated private reply" not in json.dumps(page)
    assert len(e.repos.task_repo.list(e.uid)) == 2


async def test_checkpoint_crash_recovers_one_complete_batch(room_env):
    e = room_env
    await enqueue(e)
    await enqueue(e, "c")
    room = e.repos.task_coordination_repo.room(e.scope_id)
    scope = e.repos.task_coordination_repo.get(e.scope_id)
    batch = discussion_messages(
        [
            AIMessage(
                "Tool step", id="step", tool_calls=[{"id": "same", "name": "inspect", "args": {}}]
            ),
            ToolMessage("Evidence", id="evidence", tool_call_id="same"),
            AIMessage("Result", id="result"),
        ],
        prefix="crash-batch",
        speaker_id="b",
        allowed_speakers={"a", "b", "c"},
    )
    e.harness.fail_after_append = True
    assert not await e.manager._rooms._append(scope, room["agent_id"], room["thread_id"], batch)
    assert await TaskRooms(e.manager)._append(scope, room["agent_id"], room["thread_id"], batch)
    assert await TaskRooms(e.manager)._append(scope, room["agent_id"], room["thread_id"], batch)
    ids = [item.id for item in room_messages(e, room)]
    assert all(ids.count(item.id) == 1 for item in batch)
    documents = e.archive.store.documents(room["thread_id"], "message")
    stored = [item["value"]["data"]["id"] for item in documents]
    assert all(stored.count(item.id) == 1 for item in batch)


async def test_group_user_input_reuses_goal_and_deduplicates_old_replays(room_env):
    e = room_env
    await enqueue(e)
    await enqueue(e, "c")
    room = e.repos.task_coordination_repo.room(e.scope_id)
    repo = e.repos.task_coordination_repo
    repo.require_user(e.scope_id, "Need format")
    for identifier, text in [
        ("user-1", "Use CSV"),
        ("user-2", "Add a chart"),
        ("user-1", "Use CSV"),
    ]:
        message = InboundMessage(
            channel_id=e.gateway.dashboard_channel_id,
            channel_type="dashboard",
            tenant_id=room["agent_id"],
            channel_subject=ChannelSubject(subject_id=str(e.uid), chat_type="dm"),
            content=[TextContent(text=text)],
            metadata={"thread_id": room["thread_id"], "client_message_id": identifier},
        )
        await e.manager.record_room_input(message, user_id=e.uid, thread_id=room["thread_id"])
    scope = repo.get(e.scope_id)
    assert scope["user_input"] == "Add a chart" and scope["resume_seq"] == 2
    child = await enqueue(
        e,
        "c",
        origin=room["thread_id"],
        coordination={
            "scope_id": "should-not-create",
            "source_message_id": "user-2",
            "goal_text": "Add a chart",
            "initial_user_turn": True,
        },
    )
    dispatch = e.repos.task_dispatch_repo.get(child.task_id)
    assert dispatch["scope_id"] == e.scope_id
    assert dispatch["origin_thread_id"] == e.origin
    assert repo.get("should-not-create") is None
    assert len(e.created) == 1


async def test_deleted_room_is_not_recreated_and_other_owner_cannot_bind(room_env):
    e = room_env
    await enqueue(e)
    await enqueue(e, "c")
    room = e.repos.task_coordination_repo.room(e.scope_id)
    assert e.repos.task_coordination_repo.scope_for_room(e.other, room["thread_id"]) is None
    foreign_thread = await e.gateway.thread_registry.get_or_create(
        agent_id="foreign", user_id=e.other, channel_type="dashboard", channel_subject_id="foreign"
    )
    with pytest.raises(ValueError):
        e.repos.task_coordination_repo.bind_room(e.scope_id, "foreign", foreign_thread)
    e.gateway.thread_registry.delete_thread(room["thread_id"])
    assert e.repos.task_coordination_repo.room(e.scope_id)["thread_id"] is None
    assert await TaskRooms(e.manager).ensure(e.scope_id) is None
    assert len(e.created) == 1


async def test_original_team_room_is_reused_without_a_new_team(room_env):
    e = room_env
    e.repos.agent_repo.create(
        agent_id="existing-team", user_id=e.uid, name="Existing team", kind="team"
    )
    e.rosters["existing-team"] = ["a", "b"]
    original = await e.gateway.thread_registry.get_or_create(
        agent_id="existing-team",
        user_id=e.uid,
        channel_type="dashboard",
        channel_subject_id="existing",
    )
    await enqueue(e, origin=original)
    room = e.repos.task_coordination_repo.room(e.scope_id)
    assert room["agent_id"] == "existing-team" and room["thread_id"] == original
    assert not e.created


async def test_occupied_room_defers_history_without_overwriting(room_env):
    e = room_env
    await enqueue(e)
    await enqueue(e, "c")
    room = e.repos.task_coordination_repo.room(e.scope_id)
    scope = e.repos.task_coordination_repo.get(e.scope_id)
    message = AIMessage(
        "Later result", id="late-event", additional_kwargs={"speaker_agent_id": "b"}
    )

    async def occupied():
        e.gateway.steer.is_hitl_paused = lambda tid: tid == room["thread_id"]

    await occupied()
    before = list(room_messages(e, room))
    assert not await e.manager._rooms._append(scope, room["agent_id"], room["thread_id"], [message])
    assert room_messages(e, room) == before
    e.gateway.steer.is_hitl_paused = lambda tid: False
    assert await e.manager._rooms._append(scope, room["agent_id"], room["thread_id"], [message])


async def test_stopping_goal_preserves_group_and_prevents_new_automatic_tasks(room_env):
    e = room_env
    first = await enqueue(e)
    second = await enqueue(e, "c")
    room = e.repos.task_coordination_repo.room(e.scope_id)
    await e.manager.stop_coordination(e.uid, first.task_id)
    assert e.repos.task_coordination_repo.get(e.scope_id)["state"] == "stopped"
    assert e.repos.task_repo.get(second.task_id).state == "cancelled"
    assert e.repos.agent_repo.get(room["agent_id"]) is not None
    assert e.repos.thread_repo.get(room["thread_id"]) is not None
    assert e.repos.task_coordination_repo.scope_for_room(e.uid, room["thread_id"]) is None
