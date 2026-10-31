"""Conversation model snapshots preserve ownership, other threads and graph approval."""

from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage
from langgraph.types import Command
from tests.unit.agents.native_cli.test_graph_acp import (
    Settings,
    config,
    events,
    graph_for,
    runtime_for,
)

from octop.infra.agents.native_cli.config import NativeCLIError
from octop.infra.agents.native_cli.model_selection import model_choices, prepare_model_choice


def manager_for():
    settings = Settings()
    config = {"native_cli": {"enabled": True, "runner": "fake", "model_id": "fake-a"}}
    rows = {
        "agent1": SimpleNamespace(user_id=1, is_shared=False),
        "room": SimpleNamespace(user_id=1, is_shared=False),
        "other": SimpleNamespace(user_id=2, is_shared=False),
    }
    threads = {
        "one": SimpleNamespace(user_id=1, agent_id="agent1"),
        "two": SimpleNamespace(user_id=1, agent_id="agent1"),
        "room-thread": SimpleNamespace(user_id=1, agent_id="room"),
        "foreign": SimpleNamespace(user_id=2, agent_id="agent1"),
    }
    settings.set(
        "caps",
        json.dumps(
            {"models": [{"value": "fake-a", "name": "A"}, {"value": "fake-b", "name": "B"}]}
        ),
    )
    manager = SimpleNamespace(
        get_row=rows.get,
        principal_agent_id=lambda aid: "agent1" if aid == "room" else aid,
        get_config=lambda aid: config,
        native_cli=SimpleNamespace(capability_key=lambda *args: "caps"),
        _repos=SimpleNamespace(
            settings_repo=settings,
            thread_repo=SimpleNamespace(get=threads.get),
            user_repo=SimpleNamespace(
                get=lambda uid: SimpleNamespace(role="admin", disabled=False)
            ),
        ),
    )
    return manager, config


@pytest.mark.asyncio
async def test_choices_before_first_send_and_per_thread_selection_leave_engine_unchanged():
    manager, original = manager_for()
    fresh = await model_choices(manager, agent_id="agent1", user_id=1)
    assert fresh["effective_model_id"] == "fake-a"
    chosen, meta = await prepare_model_choice(
        manager, agent_id="agent1", user_id=1, thread_id="one", selected="fake-b"
    )
    assert chosen == "fake-b" and meta["cli_model_id"] == "fake-b"
    assert original["native_cli"]["model_id"] == "fake-a"
    assert (await model_choices(manager, agent_id="agent1", user_id=1, thread_id="two"))[
        "effective_model_id"
    ] == "fake-a"
    assert (
        await prepare_model_choice(
            manager, agent_id="agent1", user_id=1, thread_id="one", selected=None
        )
    )[0] == "fake-b"
    assert (
        await prepare_model_choice(
            manager, agent_id="agent1", user_id=1, thread_id="one", selected=""
        )
    )[0] == ""
    assert (await model_choices(manager, agent_id="agent1", user_id=1, thread_id="one"))[
        "effective_model_id"
    ] == ""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "agent,thread,selected,reason",
    [
        ("other", None, None, "actor_required"),
        ("agent1", "foreign", None, "thread_not_owned"),
        ("room", "one", None, "thread_not_owned"),
        ("agent1", "one", "injected-model", "model_unavailable"),
    ],
)
async def test_model_choice_rejects_unowned_thread_and_unadvertised_id(
    agent, thread, selected, reason
):
    manager, _ = manager_for()
    with pytest.raises(NativeCLIError) as error:
        if selected:
            await prepare_model_choice(
                manager, agent_id=agent, user_id=1, thread_id=thread, selected=selected
            )
        else:
            await model_choices(manager, agent_id=agent, user_id=1, thread_id=thread)
    assert error.value.code == reason


@pytest.mark.asyncio
async def test_team_choice_is_owned_and_saved_for_its_own_conversation():
    manager, _ = manager_for()
    chosen, _ = await prepare_model_choice(
        manager, agent_id="room", user_id=1, thread_id="room-thread", selected="fake-b"
    )
    assert chosen == "fake-b"
    assert (await model_choices(manager, agent_id="agent1", user_id=1, thread_id="one"))[
        "effective_model_id"
    ] == "fake-a"


@pytest.mark.asyncio
async def test_real_graph_holds_model_snapshot_across_human_approval(tmp_path):
    runtime, marker = runtime_for(tmp_path)
    writes = []
    graph = graph_for(runtime, writes)
    turn = config()
    turn["configurable"]["octop_native_model_id"] = "fake-a"
    try:
        first = await graph.ainvoke(
            {"messages": [HumanMessage(content="approved action")]}, config=turn
        )
        assert first["__interrupt__"] and not writes
        original = runtime.context_for

        async def changed(*args):
            context = await original(*args)
            return replace(context, spec=replace(context.spec, model_id="fake-b"))

        runtime.context_for = changed
        result = await graph.ainvoke(
            Command(resume={"decisions": [{"type": "approve"}]}), config=turn
        )
        assert writes == ["from-native"]
        assert result["messages"][-1].content == "Octop tool completed"
        assert [e["value"] for e in events(marker) if e["event"] == "model_value"] == ["fake-a"]
    finally:
        await runtime.aclose()


@pytest.mark.asyncio
async def test_runtime_rechecks_actual_advertised_models_not_only_cached_choices(tmp_path):
    runtime, marker = runtime_for(tmp_path, mode="text")
    turn = config()
    turn["configurable"]["octop_native_model_id"] = "cached-but-removed"
    try:
        with pytest.raises(NativeCLIError) as error:
            await graph_for(runtime, []).ainvoke(
                {"messages": [HumanMessage(content="hello")]}, config=turn
            )
        assert error.value.code == "model_unavailable"
        assert not any(e["event"] == "prompt" for e in events(marker))
    finally:
        await runtime.aclose()
