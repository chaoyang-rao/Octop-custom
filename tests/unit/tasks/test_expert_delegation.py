"""Real task admission and tool identity, without models or external writes."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.unit.tasks.test_task_manager import settled
from tests.unit.tasks.test_task_manager import setup as setup

from octop.infra.agents.threads.project_runtime import thread_project_config
from octop.infra.tasks.models import CodingTaskSpec, TaskCreate
from octop.infra.tasks.tools import build_expert_task_tools


async def call_tool(
    e, monkeypatch, args, *, actor="a", call_id="dispatch-1", mode="craft", turn="turn-1"
):
    origin = await e.gateway.thread_registry.get_or_create(
        agent_id=actor,
        user_id=e.uid,
        channel_type="dashboard",
        channel_subject_id=f"origin-{actor}",
    )
    monkeypatch.setattr(
        "octop.infra.tasks.tools.get_config",
        lambda: {
            "configurable": {
                "agent_id": actor,
                "user": str(e.uid),
                "thread_id": origin,
                "locale": "en",
                "conversation_mode": mode,
            }
        },
    )
    teams = SimpleNamespace(primary_expert_for_user=lambda _: e.repos.agent_repo.get("a"))
    tool = build_expert_task_tools(lambda: e.manager, e.repos, teams)[0]
    value = await tool.ainvoke(
        {
            "name": "expert_tasks",
            "type": "tool_call",
            "id": call_id,
            "args": {**args, "state": {"messages": [{"type": "ai", "id": turn}]}},
        }
    )
    return json.loads(value.content), origin


async def test_new_expert_is_available_and_dispatch_is_idempotent(setup, monkeypatch):
    e = setup
    e.repos.agent_repo.create(agent_id="new-expert", user_id=e.uid, name="New specialist")
    listed, _ = await call_tool(e, monkeypatch, {"action": "experts"})
    assert {x["agent_id"] for x in listed} == {"a", "b", "new-expert"}
    args = {
        "action": "create",
        "agent_id": "new-expert",
        "title": "Research",
        "prompt": "Summarize the supplied facts and return a short report.",
    }
    first, origin = await call_tool(e, monkeypatch, args)
    repeated, _ = await call_tool(e, monkeypatch, args)
    assert first["task_id"] == repeated["task_id"]
    rows = await e.manager.list(e.uid)
    assert len(rows) == 1
    assert rows[0]["agent_id"] == "new-expert"
    assert rows[0]["dispatch"]["origin_thread_id"] == origin
    assert "request_key" not in json.dumps(rows)
    assert rows[0]["dispatch"]["coding_spec"] is None
    await e.channels.start()
    try:
        await e.manager.process_once()
        await settled(e.manager)
        row = e.repos.task_repo.get(first["task_id"])
        assert row.state == "completed"
        e.agents.start.assert_awaited_once_with("new-expert")
        assert e.processor.received[0].tenant_id == "new-expert"
    finally:
        await e.channels.stop()


@pytest.mark.parametrize("actor,mode", [("b", "craft"), ("a", "plan"), ("a", "ask")])
async def test_delegation_respects_primary_role_and_conversation_mode(
    setup, monkeypatch, actor, mode
):
    e = setup
    result, _ = await call_tool(
        e,
        monkeypatch,
        {"action": "create", "agent_id": "b", "title": "Do work", "prompt": "Do this task"},
        actor=actor,
        mode=mode,
    )
    assert "error" in result
    assert await e.manager.list(e.uid) == []


async def test_foreign_expert_and_foreign_origin_are_rejected(setup, monkeypatch):
    e = setup
    result, _ = await call_tool(
        e,
        monkeypatch,
        {"action": "create", "agent_id": "foreign", "title": "No", "prompt": "Do not run"},
    )
    assert "error" in result
    foreign = await e.gateway.thread_registry.get_or_create(
        agent_id="foreign", user_id=e.other, channel_type="dashboard", channel_subject_id="foreign"
    )
    from octop.infra.errors import OctopError

    with pytest.raises(OctopError):
        await e.manager.enqueue(
            e.uid, TaskCreate(agent_id="b", title="No", prompt="No", origin_thread_id=foreign)
        )
    assert await e.manager.list(e.uid) == []


async def test_provider_call_ids_can_repeat_in_distinct_source_turns(setup, monkeypatch):
    e = setup
    args = {"action": "create", "agent_id": "b", "title": "First", "prompt": "First assignment"}
    first, _ = await call_tool(e, monkeypatch, args, call_id="call_1", turn="assistant-turn-1")
    second, _ = await call_tool(
        e,
        monkeypatch,
        {**args, "title": "Second", "prompt": "Second assignment"},
        call_id="call_1",
        turn="assistant-turn-2",
    )
    assert first["task_id"] != second["task_id"]
    assert len(await e.manager.list(e.uid)) == 2


async def test_real_tool_node_injects_source_message_identity(setup, monkeypatch):
    from langchain_core.messages import AIMessage, HumanMessage
    from langgraph.graph import END, START, MessagesState, StateGraph
    from langgraph.prebuilt import ToolNode

    e = setup
    origin = await e.gateway.thread_registry.get_or_create(
        agent_id="a", user_id=e.uid, channel_type="dashboard", channel_subject_id="tool-node"
    )
    monkeypatch.setattr(
        "octop.infra.tasks.tools.get_config",
        lambda: {
            "configurable": {
                "agent_id": "a",
                "user": str(e.uid),
                "thread_id": origin,
                "locale": "en",
            }
        },
    )
    teams = SimpleNamespace(primary_expert_for_user=lambda _: e.repos.agent_repo.get("a"))
    tools = build_expert_task_tools(lambda: e.manager, e.repos, teams)
    assert "state" not in tools[0].tool_call_schema.model_fields
    node = ToolNode(tools)
    builder = StateGraph(MessagesState)
    builder.add_node("tools", node)
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)
    graph = builder.compile()
    message = AIMessage(
        content="",
        id="host-assistant-1",
        tool_calls=[
            {
                "name": "expert_tasks",
                "id": "call_1",
                "args": {
                    "action": "create",
                    "agent_id": "b",
                    "title": "Via runtime",
                    "prompt": "Use the runtime-injected source identity",
                },
            }
        ],
    )
    state = {"messages": [HumanMessage(content="Do the work", id="host-user-1"), message]}
    first = await graph.ainvoke(state)
    again = await graph.ainvoke(state)
    assert (
        json.loads(first["messages"][-1].content)["task_id"]
        == json.loads(again["messages"][-1].content)["task_id"]
    )
    assert len(await e.manager.list(e.uid)) == 1


async def test_queued_parent_cannot_delegate_back_to_its_own_expert(setup):
    e = setup
    origin = await e.gateway.thread_registry.get_or_create(
        agent_id="a", user_id=e.uid, channel_type="dashboard", channel_subject_id="parent"
    )
    parent = await e.manager.enqueue(
        e.uid, TaskCreate(agent_id="a", title="parent", prompt="work", thread_id=origin)
    )
    assert e.repos.task_repo.claim(parent.task_id)
    parent = e.repos.task_repo.get(parent.task_id)
    e.manager._bindings[("a", e.uid, origin)] = (parent.task_id, parent.attempt)
    from octop.infra.errors import OctopError

    with pytest.raises(OctopError):
        await e.manager.enqueue(
            e.uid, TaskCreate(agent_id="a", title="cycle", prompt="work", origin_thread_id=origin)
        )
    child = await e.manager.enqueue(
        e.uid, TaskCreate(agent_id="b", title="child", prompt="work", origin_thread_id=origin)
    )
    context = e.repos.task_dispatch_repo.get(child.task_id)
    assert context["parent_task_id"] == parent.task_id
    assert context["parent_attempt"] == parent.attempt


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
async def test_any_owned_expert_can_run_isolated_code_task(setup, tmp_path):
    e = setup
    root = tmp_path / "repository"
    root.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(root)], check=True, capture_output=True)
    (root / "answer.txt").write_text("before")
    (root / "verify.py").write_text(
        "from pathlib import Path\nassert Path('answer.txt').read_text() == 'after'\n"
    )
    subprocess.run(["git", "-C", str(root), "add", "."], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.test",
            "commit",
            "-m",
            "fixture",
        ],
        check=True,
        capture_output=True,
    )
    (root / "keep-uncommitted.txt").write_text("original user's unsaved work")
    e.repos.thread_repo.upsert_project(
        agent_id="a", user_id=e.uid, project_path=str(root.resolve())
    )
    e.repos.agent_repo.create(agent_id="fresh-native", user_id=e.uid, name="Native expert")

    async def execute(message):
        context = e.repos.task_dispatch_repo.get(message.metadata["task_id"])
        run = context["coding_run"]
        worktree = Path(run["worktree"])
        assert not (worktree / "keep-uncommitted.txt").exists()
        config = thread_project_config(
            e.repos.thread_repo,
            agent_id="fresh-native",
            thread_id=message.metadata["thread_id"],
            task_repo=e.repos.task_repo,
            dispatch_repo=e.repos.task_dispatch_repo,
        )
        assert config["octop_project_path"] == str(worktree)
        (worktree / "answer.txt").write_text("after")
        yield {"type": "token", "content": "Code change prepared"}
        yield {"type": "done"}

    e.processor.iter_turn_chunks = execute
    task = await e.manager.enqueue(
        e.uid,
        TaskCreate(
            agent_id="fresh-native",
            title="Change answer",
            prompt="Update answer and verify it.",
            coding=CodingTaskSpec(
                project_path=str(root), test_commands=[f'"{sys.executable}" verify.py']
            ),
        ),
    )
    await e.channels.start()
    try:
        await e.manager.process_once()
        await settled(e.manager)
    finally:
        await e.channels.stop()
    result = await e.manager.detail(e.uid, task.task_id)
    assert result["state"] == "completed", result
    assert result["dispatch"]["coding_run"]["phase"] == "ready"
    assert result["dispatch"]["coding_run"]["verification"][0]["passed"]
    assert (root / "answer.txt").read_text() == "before"
    assert (root / "keep-uncommitted.txt").read_text() == "original user's unsaved work"
    assert not result["dispatch"]["coding_run"].get("pr_url")
