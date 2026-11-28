"""Catalog backport on the packaged runtime, including the legacy graph order."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import deepagents.graph as deepagents_graph
from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from octop_harness.agent import _patched_summarization_factory
from octop_harness.config import HarnessAgentConfig
from octop_harness.middleware.context_budget import ContextBudgetGuardMiddleware
from octop_harness.middleware.context_usage import ContextUsageMiddleware
from octop_harness.middleware.conversation_mode import ConversationModeMiddleware
from octop_harness.middleware.skill_discovery import SkillDiscoveryMiddleware
from octop_harness.middleware.skill_filter import SkillFilterMiddleware
from octop_harness.middleware.tool_search import ToolSearchMiddleware


class _Model(FakeMessagesListChatModel):
    seen: list[Any] = []
    bound: list[Any] = []

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        self.bound.append(list(tools))
        return self

    def _generate(
        self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> Any:
        self.seen.append(list(messages))
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def _graph(
    tmp_path: Path, model: _Model, *, progressive: bool = True, tools: list[Any] | None = None
):
    for i in range(20):
        slug = f"sample-{i}"
        p = tmp_path / "skills" / slug / "SKILL.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        desc = "Excel table export " + "long workflow description " * 30
        p.write_text(f"---\nname: {slug}\ndescription: {desc}\n---\nSKILL BODY\n", encoding="utf-8")
    backend = FilesystemBackend(root_dir=tmp_path)
    middleware = [
        SkillFilterMiddleware(config=HarnessAgentConfig(skills_disabled=frozenset({"sample-0"}))),
        ConversationModeMiddleware(),
    ]
    if progressive:
        middleware.extend(
            [
                ToolSearchMiddleware(deferred_tools=frozenset(), defer_other_tools=True),
                SkillDiscoveryMiddleware(backend=backend, sources=["/skills/"], language="zh"),
                ContextBudgetGuardMiddleware(),
                ContextUsageMiddleware(max_tokens=1000000),
            ]
        )
    # This is the same compatibility adapter used by packaged HarnessAgent.
    with _patched_summarization_factory(deepagents_graph.create_summarization_middleware):
        return create_deep_agent(
            model=model,
            backend=backend,
            skills=["/skills/"],
            middleware=middleware,
            tools=tools or [],
        )


def _check_legacy_graph_keeps_catalog_filtered_before_rendering(tmp_path: Path, mode: str) -> None:
    model = _Model(responses=[AIMessage(content="ok")], seen=[], bound=[])
    graph = _graph(tmp_path, model)
    graph.invoke(
        {"messages": [HumanMessage(content="Summarize the supplied text")]},
        {"configurable": {"thread_id": "legacy", "user": "alice", "conversation_mode": mode}},
    )
    prompt = "\n".join(m.text for m in model.seen[0] if isinstance(m, SystemMessage))
    assert "sample-0" not in prompt
    assert "long workflow description" not in prompt
    assert ("search_skills" in [getattr(t, "name", "") for t in model.bound[0]]) is (
        mode == "craft"
    )


async def _check_legacy_graph_search_then_read_keeps_full_skill_available(
    tmp_path: Path, asynchronous: bool
) -> None:
    model = _Model(
        responses=[
            AIMessage(
                content="",
                tool_calls=[{"id": "find", "name": "search_skills", "args": {"query": "Excel"}}],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "read",
                        "name": "read_file",
                        "args": {"file_path": "/skills/sample-1/SKILL.md"},
                    }
                ],
            ),
            AIMessage(content="done"),
        ],
        seen=[],
        bound=[],
    )
    graph = _graph(tmp_path, model)
    inputs = {"messages": [HumanMessage(content="Create an Excel report")]}
    config = {
        "configurable": {"thread_id": "legacy", "user": "alice", "conversation_mode": "craft"}
    }
    result = await graph.ainvoke(inputs, config) if asynchronous else graph.invoke(inputs, config)
    assert result["messages"][-1].text == "done"
    assert any(isinstance(m, ToolMessage) and "SKILL BODY" in m.text for m in result["messages"])
    assert all("sample-0" not in m.text for m in result["messages"] if isinstance(m, ToolMessage))


def _check_deferred_tool_loads_full_schema_and_executes_once(tmp_path: Path) -> None:
    calls = []

    def report(value: str) -> str:
        calls.append(value)
        return value

    tool = StructuredTool.from_function(
        report, name="uncommon_report", description="Export a report " + "details " * 200
    )
    model = _Model(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {"id": "find", "name": "tool_search", "args": {"query": "uncommon report"}}
                ],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {"id": "run", "name": "uncommon_report", "args": {"value": "verified"}}
                ],
            ),
            AIMessage(content="done"),
        ],
        seen=[],
        bound=[],
    )
    graph = _graph(tmp_path, model, tools=[tool])
    result = graph.invoke(
        {"messages": [HumanMessage(content="Export the report")]},
        {"configurable": {"thread_id": "legacy", "user": "alice", "conversation_mode": "craft"}},
    )
    assert calls == ["verified"]
    assert result["messages"][-1].text == "done"
    first = next(t for t in model.bound[0] if getattr(t, "name", "") == "uncommon_report")
    loaded = next(t for t in model.bound[-1] if getattr(t, "name", "") == "uncommon_report")
    assert first.args == {}
    assert "value" in loaded.args


class ProgressiveCatalogTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory(prefix="octop-catalog-compat-")
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_modes_filter_before_rendering(self) -> None:
        for mode in ("craft", "ask", "plan"):
            with self.subTest(mode=mode):
                _check_legacy_graph_keeps_catalog_filtered_before_rendering(self.root / mode, mode)

    async def test_sync_and_async_search_then_read(self) -> None:
        for asynchronous in (False, True):
            with self.subTest(asynchronous=asynchronous):
                await _check_legacy_graph_search_then_read_keeps_full_skill_available(
                    self.root / str(asynchronous), asynchronous
                )

    def test_deferred_tool_executes_once_after_loading(self) -> None:
        _check_deferred_tool_loads_full_schema_and_executes_once(self.root)
