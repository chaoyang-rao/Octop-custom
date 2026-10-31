"""Real ACP subprocess + HTTP MCP + LangGraph ToolNode/HITL, no paid LLMs."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from octop_harness.acp.models import ACPRunnerConfig

from octop.infra.agents.native_cli.config import NativeCLIError, NativeSpec
from octop.infra.agents.native_cli.integration import native_permission_tool
from octop.infra.agents.native_cli.model import NativeACPChatModel
from octop.infra.agents.native_cli.runtime import NativeContext, NativeRuntime
from octop.infra.connectors.accounts.actor import authenticated_vault_actor


class Settings:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.values[key] = value

    def delete(self, key):
        self.values.pop(key, None)


def runtime_for(tmp_path, *, mode="tool", settings=None, load=True):
    script = Path(__file__).resolve().parents[3] / "support" / "native_cli" / "fake_agent.py"
    marker = tmp_path / "events.jsonl"
    runner = ACPRunnerConfig(
        enabled=True,
        command=sys.executable,
        args=[str(script)],
        env={
            "FAKE_NATIVE_MODE": mode,
            "FAKE_NATIVE_MARKER": str(marker),
            "FAKE_NATIVE_LOAD": "1" if load else "0",
        },
    )

    async def context(agent_id, thread_id, actor):
        if agent_id != "agent1" or thread_id != "thread1" or actor != 1:
            raise NativeCLIError("thread_not_owned")
        return NativeContext(
            1, "agent1", "thread1", str(tmp_path), NativeSpec(True, "fake"), runner
        )

    runtime = NativeRuntime(settings_repo=settings or Settings(), context_for=context)
    return runtime, marker


def graph_for(runtime, writes, *, native_permission=False, checkpoint=None):
    @tool
    async def recorded_tool(value: str) -> str:
        """Record one controlled local test action."""
        writes.append(value)
        return "recorded"

    permission = native_permission_tool("en")
    tools = [recorded_tool, permission]
    interrupt = {
        "native_cli_permission" if native_permission else "recorded_tool": {
            "allowed_decisions": ["approve", "reject"]
        }
    }
    model = NativeACPChatModel(runtime=runtime, agent_id="agent1", owner_id=1)
    return create_agent(
        model=model,
        tools=tools,
        middleware=[HumanInTheLoopMiddleware(interrupt_on=interrupt)],
        checkpointer=checkpoint or InMemorySaver(),
    )


def config(actor=1):
    return {
        "configurable": {
            "thread_id": "thread1",
            "octop_authenticated_user_id": actor,
            "octop_execution_user_id": actor,
        }
    }


def events(marker):
    return [json.loads(line) for line in marker.read_text().splitlines()] if marker.exists() else []


@pytest.mark.asyncio
async def test_mcp_tool_waits_for_real_graph_human_approval(tmp_path, monkeypatch):
    monkeypatch.setenv("OCTOP_HOME", str(tmp_path))
    runtime, marker = runtime_for(tmp_path)
    writes = []
    graph = graph_for(runtime, writes)
    try:
        async with asyncio.timeout(15):
            first = await graph.ainvoke(
                {"messages": [HumanMessage(content="do the test")]}, config=config()
            )
            assert first.get("__interrupt__")
            assert writes == []
            assert len(runtime.sessions) == 1
            session = next(iter(runtime.sessions.values()))
            assert session.state == "waiting" and session.prompt_task is not None
            state = await graph.aget_state(config())
            assert state.next
            result = await graph.ainvoke(
                Command(resume={"decisions": [{"type": "approve"}]}), config=config()
            )
        assert writes == ["from-native"]
        assert result["messages"][-1].content == "Octop tool completed"
        received = [entry for entry in events(marker) if entry["event"] == "tool_result"]
        assert len(received) == 1 and received[0]["result"]["result"]["isError"] is False
    finally:
        if runtime.last_failure:
            print("native-test failure stage/type:", runtime.last_failure)
        await runtime.aclose()


@pytest.mark.asyncio
async def test_octop_tool_rejection_is_returned_as_error_without_execution(tmp_path):
    runtime, marker = runtime_for(tmp_path)
    writes = []
    graph = graph_for(runtime, writes)
    try:
        async with asyncio.timeout(15):
            await graph.ainvoke({"messages": [HumanMessage(content="test")]}, config=config())
            result = await graph.ainvoke(
                Command(resume={"decisions": [{"type": "reject", "message": "do not run"}]}),
                config=config(),
            )
        assert writes == []
        received = [entry for entry in events(marker) if entry["event"] == "tool_result"]
        assert received[0]["result"]["result"]["isError"] is True
        assert result["messages"][-1].content == "Octop tool rejected"
    finally:
        await runtime.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["approve", "reject"])
async def test_native_permission_uses_once_only_and_rejection_is_not_success(tmp_path, decision):
    runtime, marker = runtime_for(tmp_path, mode="permission")
    writes = []
    graph = graph_for(runtime, writes, native_permission=True)
    try:
        async with asyncio.timeout(15):
            first = await graph.ainvoke(
                {"messages": [HumanMessage(content="test permission")]}, config=config()
            )
            assert first.get("__interrupt__")
            assert not any(entry["event"] == "action" for entry in events(marker))
            if decision == "approve":
                result = await graph.ainvoke(
                    Command(resume={"decisions": [{"type": "approve"}]}), config=config()
                )
                assert result["messages"][-1].content == "approved"
            else:
                with pytest.raises(NativeCLIError) as error:
                    await graph.ainvoke(
                        Command(resume={"decisions": [{"type": "reject", "message": "no"}]}),
                        config=config(),
                    )
                assert error.value.code == "permission_rejected"
        recorded = events(marker)
        permission = next(entry for entry in recorded if entry["event"] == "permission")
        assert permission["outcome"].get("optionId") == (
            "once" if decision == "approve" else "reject"
        )
        assert sum(entry["event"] == "action" for entry in recorded) == (
            1 if decision == "approve" else 0
        )
    finally:
        await runtime.aclose()


@pytest.mark.asyncio
async def test_other_or_mismatched_authenticated_actor_cannot_start_cli(tmp_path):
    runtime, marker = runtime_for(tmp_path, mode="text")
    graph = graph_for(runtime, [])
    try:
        with pytest.raises(NativeCLIError) as error:
            await graph.ainvoke({"messages": [HumanMessage(content="private")]}, config=config(2))
        assert error.value.code == "actor_required" and not marker.exists()
        with authenticated_vault_actor(2), pytest.raises(NativeCLIError):
            await graph.ainvoke({"messages": [HumanMessage(content="private")]}, config=config())
        assert not marker.exists()
    finally:
        await runtime.aclose()


@pytest.mark.asyncio
async def test_idle_native_session_loads_only_when_advertised(tmp_path):
    settings = Settings()
    runtime, marker = runtime_for(tmp_path, mode="text", settings=settings)
    graph = graph_for(runtime, [])
    try:
        async with asyncio.timeout(15):
            await graph.ainvoke({"messages": [HumanMessage(content="first")]}, config=config())
        await runtime.aclose()
        next_runtime, _ = runtime_for(tmp_path, mode="text", settings=settings)
        next_graph = graph_for(next_runtime, [])
        try:
            async with asyncio.timeout(15):
                await next_graph.ainvoke(
                    {"messages": [HumanMessage(content="next")]}, config=config()
                )
            assert any(entry["event"] == "session/load" for entry in events(marker))
        finally:
            await next_runtime.aclose()
    finally:
        await runtime.aclose()


@pytest.mark.asyncio
async def test_cancel_closes_real_cli_process_and_does_not_replay(tmp_path):
    runtime, marker = runtime_for(tmp_path, mode="wait")
    graph = graph_for(runtime, [])
    job = asyncio.create_task(
        graph.ainvoke({"messages": [HumanMessage(content="wait")]}, config=config())
    )
    try:
        async with asyncio.timeout(10):
            while not any(entry["event"] == "prompt" for entry in events(marker)):
                await asyncio.sleep(0.02)
        process = next(iter(runtime.sessions.values())).process
        job.cancel()
        with pytest.raises(asyncio.CancelledError):
            await job
        assert process.returncode is not None
        assert runtime.sessions == {}
        assert not any("native_cli.session" in key for key in runtime.settings.values)
    finally:
        job.cancel()
        await runtime.aclose()
