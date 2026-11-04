"""Real peer session hooks are observable without synthesizing a discussion."""

from __future__ import annotations

import json

from langchain_core.messages import AIMessage, HumanMessage
from octop_harness.teams.util import PeerCall
from tests.unit.tasks.test_task_manager import setup as setup
from tests.unit.tasks.test_task_rooms import enqueue, room_messages
from tests.unit.tasks.test_task_rooms import room_env as room_env

from octop.infra.agents.teams.team_manager import TeamManager
from octop.infra.tasks.coordinator import scope_signature
from octop.infra.tasks.models import TaskCreate
from octop.infra.tasks.rooms import TaskRooms


async def running_parent(e):
    parent = await enqueue(e)
    assert e.repos.task_repo.claim(parent.task_id)
    tid = await e.gateway.thread_registry.get_or_create(
        agent_id="b", user_id=e.uid, channel_type="dashboard", channel_subject_id="worker-task"
    )
    assert e.repos.task_repo.transition(
        parent.task_id,
        expected={"running"},
        state="running",
        action="thread",
        fields={"thread_id": tid},
    )
    parent = e.repos.task_repo.get(parent.task_id)
    e.manager._bindings[("b", e.uid, tid)] = (parent.task_id, parent.attempt)
    return parent, tid


def peer_bridge(e):
    e.agents.record_task_peer = e.manager._rooms.register_peer
    e.agents.finish_task_peer = e.manager._rooms.finish_peer
    return TeamManager(
        agent_manager=e.agents,
        thread_registry=e.gateway.thread_registry,
        user_repo=e.repos.user_repo,
        thread_message_repo=e.repos.thread_message_repo,
        gateway=e.gateway,
    )


async def test_worker_consultation_creates_group_and_records_actual_question_and_reply(room_env):
    e = room_env
    parent, tid = await running_parent(e)
    assert not e.created
    bridge = peer_bridge(e)
    call = PeerCall(
        from_agent_id="b",
        to_agent_id="c",
        user_id=e.uid,
        message="Please check the actual evidence",
        source_thread_id=tid,
        source_session_key=e.repos.thread_repo.get(tid).session_key,
    )
    session = await bridge.prepare_peer_session(call)
    room = e.repos.task_coordination_repo.room(e.scope_id)
    assert room and len(e.created) == 1
    assert set(e.rosters[room["agent_id"]]) == {"a", "b", "c"}
    assert e.manager._rooms.has_pending_peers(e.scope_id)
    assert e.agents.teams.jobs.is_busy(room["agent_id"], "c")
    await bridge.record_peer_turn(
        call,
        session.thread_id,
        {"messages": [AIMessage("Actual reply from the consulted expert", id="consultant-reply")]},
    )
    assert not e.manager._rooms.has_pending_peers(e.scope_id)
    await e.manager._rooms.process()
    messages = room_messages(e, room)
    assert any(
        "Please check the actual evidence" in str(item.content)
        and item.additional_kwargs["speaker_agent_id"] == "b"
        for item in messages
    )
    assert any(
        item.content == "Actual reply from the consulted expert"
        and item.additional_kwargs["speaker_agent_id"] == "c"
        for item in messages
    )
    assert not any(isinstance(item, HumanMessage) for item in messages)
    assert e.repos.task_coordination_repo.get(e.scope_id)["resume_seq"] == 0
    assert not e.agents.teams.jobs.is_busy(room["agent_id"], "c")
    count = len(messages)
    await TaskRooms(e.manager).process()
    assert len(room_messages(e, room)) == count
    assert e.repos.task_repo.get(parent.task_id).state == "running"


async def test_consultation_and_its_new_room_keep_the_origin_project(room_env, tmp_path):
    e = room_env
    _parent, tid = await running_parent(e)
    project = tmp_path / "shared-project"
    project.mkdir()
    scope = e.repos.task_coordination_repo.get(e.scope_id)
    for source_id in (tid, scope["origin_thread_id"]):
        source = e.repos.thread_repo.get(source_id)
        e.repos.thread_repo.set_project(
            source_id,
            agent_id=source.agent_id,
            user_id=e.uid,
            project_path=str(project),
            project_name="Shared project",
        )
    call = PeerCall(
        from_agent_id="b",
        to_agent_id="c",
        user_id=e.uid,
        message="Check the project evidence",
        source_thread_id=tid,
        source_session_key=e.repos.thread_repo.get(tid).session_key,
    )
    session = await peer_bridge(e).prepare_peer_session(call)
    peer = e.repos.thread_repo.get(session.thread_id)
    room = e.repos.task_coordination_repo.room(e.scope_id)
    assert peer.project_path == str(project)
    assert e.repos.thread_repo.get(room["thread_id"]).project_path == str(project)


async def test_consulting_primary_keeps_single_executor_in_original_conversation(room_env):
    e = room_env
    _parent, tid = await running_parent(e)
    bridge = peer_bridge(e)
    call = PeerCall(
        from_agent_id="b",
        to_agent_id="a",
        user_id=e.uid,
        message="Clarify the goal",
        source_thread_id=tid,
        source_session_key=e.repos.thread_repo.get(tid).session_key,
    )
    session = await bridge.prepare_peer_session(call)
    await bridge.record_peer_turn(
        call,
        session.thread_id,
        {"messages": [AIMessage("Actual primary clarification", id="primary-consultation")]},
    )
    assert e.repos.task_coordination_repo.room(e.scope_id) is None
    assert not e.created


async def test_consultant_execution_cannot_turn_its_input_into_new_task_authority(
    room_env, monkeypatch
):
    e = room_env
    _parent, tid = await running_parent(e)
    bridge = peer_bridge(e)
    call = PeerCall(
        from_agent_id="b",
        to_agent_id="a",
        user_id=e.uid,
        message="Clarify only",
        source_thread_id=tid,
        source_session_key=e.repos.thread_repo.get(tid).session_key,
    )
    session = await bridge.prepare_peer_session(call)
    from octop.infra.tasks.tools import build_expert_task_tools

    monkeypatch.setattr(
        "octop.infra.tasks.tools.get_config",
        lambda: {
            "configurable": {"agent_id": "a", "user": str(e.uid), "thread_id": session.thread_id}
        },
    )
    tool = build_expert_task_tools(lambda: e.manager, e.repos, e.agents.teams)[0]
    before = len(e.repos.task_repo.list(e.uid))
    answer = await tool.ainvoke(
        {
            "name": "expert_tasks",
            "type": "tool_call",
            "id": "from-consultation",
            "args": {
                "action": "create",
                "agent_id": "c",
                "title": "not a user request",
                "prompt": "Do unrelated work",
                "state": {
                    "messages": [
                        {"type": "human", "id": "consultation-human", "content": "Clarify only"},
                        {"type": "ai", "id": "consultation-ai"},
                    ]
                },
            },
        }
    )
    assert "consultant_dispatch" in json.dumps(json.loads(answer.content))
    assert len(e.repos.task_repo.list(e.uid)) == before
    await e.manager._rooms.finish_peer(call)


def test_zero_peer_revision_preserves_completed_v27_goal_signature():
    members = [{"task_id": "task-one", "attempt": 1, "state": "completed", "event_id": 9}]
    assert (
        scope_signature({"resume_seq": 0, "peer_revision": 0}, members)
        == "715b83538bca1bdc18189444c9fd342901b7ad01bc3e10e7e9ad07a1b3814e15"
    )
    assert (
        scope_signature({"resume_seq": 0, "peer_revision": 1}, members)
        != "715b83538bca1bdc18189444c9fd342901b7ad01bc3e10e7e9ad07a1b3814e15"
    )


async def test_stopped_latest_goal_does_not_reactivate_an_older_room_goal(room_env):
    e = room_env
    await enqueue(e)
    await enqueue(e, "c")
    room = e.repos.task_coordination_repo.room(e.scope_id)
    repo = e.repos.task_coordination_repo
    repo.ensure(
        {
            "scope_id": "later-goal",
            "user_id": e.uid,
            "origin_agent_id": room["agent_id"],
            "origin_thread_id": room["thread_id"],
            "source_message_id": "new-user",
            "goal_text": "Later actual goal",
        }
    )
    repo.bind_room("later-goal", room["agent_id"], room["thread_id"])
    assert repo.scope_for_room(e.uid, room["thread_id"])["scope_id"] == "later-goal"
    repo.stop("later-goal", e.uid)
    assert repo.scope_for_room(e.uid, room["thread_id"]) is None
    assert (
        repo.scope_for_room(e.uid, room["thread_id"], include_stopped=True)["scope_id"]
        == "later-goal"
    )


async def test_primary_task_descendants_share_original_goal_and_one_group(room_env):
    e = room_env
    parent = await enqueue(e, "a", key="primary-task")
    assert e.repos.task_repo.claim(parent.task_id)
    tid = await e.gateway.thread_registry.get_or_create(
        agent_id="a", user_id=e.uid, channel_type="dashboard", channel_subject_id="primary-task"
    )
    e.repos.task_repo.transition(
        parent.task_id,
        expected={"running"},
        state="running",
        action="thread",
        fields={"thread_id": tid},
    )
    parent = e.repos.task_repo.get(parent.task_id)
    e.manager._bindings[("a", e.uid, tid)] = (parent.task_id, parent.attempt)
    child = await e.manager.enqueue(
        e.uid,
        TaskCreate(
            agent_id="b", title="Actual child", prompt="Assigned subtask", origin_thread_id=tid
        ),
        request_key="child-tool-call",
        coordination={
            "scope_id": "not-a-new-user-goal",
            "source_message_id": "internal-prompt",
            "goal_text": "Task instructions",
            "initial_user_turn": True,
        },
    )
    context = e.repos.task_dispatch_repo.get(child.task_id)
    assert context["scope_id"] == e.scope_id
    assert context["parent_task_id"] == parent.task_id
    assert e.repos.task_coordination_repo.get("not-a-new-user-goal") is None
    assert len(e.created) == 1
