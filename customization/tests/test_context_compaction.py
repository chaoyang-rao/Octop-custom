"""Context integrity contracts using offline models and synthetic messages."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from deepagents.middleware.summarization import SummarizationMiddleware
from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.exceptions import ContextOverflowError
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, get_buffer_string
from langchain_core.outputs import ChatGeneration, ChatResult
from octop_harness.agent import _patched_summarization_factory
from octop_harness.context_usage import breakdown_from_model_request
from octop_harness.middleware.model_router import ModelRouterMiddleware
from octop_harness.middleware.model_settings import ModelSettingsMiddleware, apply_configurable_model_settings
from octop_harness.middleware.summarization_limits import harden_summarization_middleware
from pydantic import Field

from octop.infra.agents.middleware.model_failover import SafeModelFailoverMiddleware
from octop.infra.agents.providers.health import ModelHealthRegistry
from octop.infra.agents.providers.store import AutoRouteCandidate


class RecordingModel(FakeListChatModel):
    prompts: list[str] = Field(default_factory=list)
    overflow: bool = False
    fail_chat: bool = False

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.prompts.append(get_buffer_string(messages))
        if self.overflow:
            raise ContextOverflowError("offline context window exceeded")
        if self.fail_chat and "<primary_objective>" not in self.prompts[-1]:
            raise ConnectionError("offline injected primary model failure")
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="CHECKPOINT"))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop, run_manager, **kwargs)


def middleware(model):
    mw = SummarizationMiddleware(
        model=model,
        backend=SimpleNamespace(),
        trigger=("tokens", 100),
        keep=("messages", 2),
        trim_tokens_to_summarize=8000,
    )
    mw._lc_helper._summary_model = model
    return harden_summarization_middleware(mw)


class SummaryIntegrityTests(unittest.IsolatedAsyncioTestCase):
    async def test_snapshot_identity_is_bound_to_the_executing_expert(self):
        from octop_harness.middleware.context_usage import ContextUsageMiddleware

        model = RecordingModel(responses=["unused"], profile={"max_input_tokens": 32000})
        mw = ContextUsageMiddleware(agent_id="primary")
        request = ModelRequest(
            model=model,
            messages=[HumanMessage(content="hello")],
            runtime=SimpleNamespace(config={"configurable": {"thread_id": "room", "agent_id": "other"}}),
        )

        async def handler(_):
            return ModelResponse(
                result=[
                    AIMessage(
                        content="ok",
                        usage_metadata={
                            "input_tokens": 1000,
                            "output_tokens": 10,
                            "total_tokens": 1010,
                        },
                    )
                ]
            )

        response = await mw.awrap_model_call(request, handler)
        stamp = response.result[0].additional_kwargs["context_usage"]
        self.assertEqual((stamp["agent_id"], stamp["thread_id"]), ("primary", "room"))
        self.assertEqual(stamp["max_tokens"], 32000)

    async def test_legacy_incomplete_summary_is_rebuilt_from_raw_messages(self):
        model = RecordingModel(responses=["unused"], profile={"max_input_tokens": 128000})
        mw = middleware(model)
        mw._aoffload_to_backend = AsyncMock(return_value="/conversation_history/test.md")
        history = [
            HumanMessage(content="ORIGINAL_GOAL_KEEP_THIS"),
            AIMessage(content="accepted"),
            HumanMessage(content="later evidence " * 1000),
            AIMessage(content="noted"),
            HumanMessage(content="continue"),
        ]
        old_event = {
            "cutoff_index": 2,
            "summary_message": HumanMessage(content="incomplete old summary"),
            "file_path": "/conversation_history/old.md",
        }
        state = {"messages": history, "_summarization_event": old_event}

        async def handler(request):
            return ModelResponse(result=[AIMessage(content="ok")])

        response = await mw.awrap_model_call(ModelRequest(model=model, messages=history, state=state), handler)
        self.assertIn("ORIGINAL_GOAL_KEEP_THIS", "\n".join(model.prompts))
        self.assertEqual(response.command.update["_summarization_event"]["coverage_version"], 2)
        self.assertIs(state["_summarization_event"], old_event)
        self.assertNotIn("coverage_version", old_event)

    async def test_failed_rebuild_leaves_existing_checkpoint_untouched(self):
        model = RecordingModel(responses=["unused"], profile={"max_input_tokens": 128000}, overflow=True)
        mw = middleware(model)
        mw._aoffload_to_backend = AsyncMock(return_value="/conversation_history/test.md")
        history = [
            HumanMessage(content="original goal"),
            AIMessage(content="accepted"),
            HumanMessage(content="later evidence " * 1000),
            AIMessage(content="noted"),
        ]
        old_event = {"cutoff_index": 2, "summary_message": HumanMessage(content="old"), "file_path": "old.md"}
        state = {"messages": history, "_summarization_event": old_event}
        with self.assertRaises(ContextOverflowError):
            await mw.awrap_model_call(ModelRequest(model=model, messages=history, state=state), AsyncMock())
        self.assertIs(state["_summarization_event"], old_event)
        self.assertEqual(history[0].content, "original goal")

    def test_unknown_capacity_survives_snapshot_serialization(self):
        from octop_harness.context_usage import ContextUsage, build_context_usage, shrink_context_usage

        model = RecordingModel(responses=["unused"])
        usage = build_context_usage(
            ModelRequest(model=model, messages=[HumanMessage(content="hello")]),
            response_messages=[
                AIMessage(
                    content="ok",
                    usage_metadata={
                        "input_tokens": 220000,
                        "output_tokens": 10,
                        "total_tokens": 220010,
                    },
                )
            ],
            max_tokens=0,
        )
        restored = ContextUsage.from_dict(usage.to_dict())
        self.assertEqual(restored.max_tokens, 0)
        self.assertEqual(restored.used_tokens, 220000)
        self.assertEqual(shrink_context_usage(restored, 2).max_tokens, 0)
        self.assertEqual(shrink_context_usage(restored, 2).used_tokens, 219998)

    def test_output_is_reserved_once_and_cannot_expand_the_physical_window(self):
        model = RecordingModel(responses=["unused"], profile={"max_input_tokens": 32000})
        request = ModelRequest(
            model=model,
            messages=[HumanMessage(content="hello")],
            runtime=SimpleNamespace(
                config={
                    "configurable": {
                        "max_input_tokens": 1000000,
                        "model_settings": {"max_tokens": 8000},
                    }
                }
            ),
        )
        first = apply_configurable_model_settings(request)
        second = apply_configurable_model_settings(first)
        self.assertEqual(first.model.profile["max_input_tokens"], 24000)
        self.assertEqual(second.model.profile["max_input_tokens"], 24000)
        self.assertEqual(model.profile["max_input_tokens"], 32000)

    async def test_old_large_tool_result_is_offloaded_before_summary(self):
        from deepagents.backends import FilesystemBackend
        from deepagents.middleware.summarization import create_summarization_middleware

        model = RecordingModel(responses=["unused"], profile={"max_input_tokens": 32000})
        tool = ToolMessage(content="full result " * 20000, tool_call_id="call-1", id="result-1")
        messages = [
            HumanMessage(content="ROOT_GOAL"),
            AIMessage(content="", tool_calls=[{"id": "call-1", "name": "search", "args": {}}]),
            tool,
        ]
        messages.extend([HumanMessage(content="continue"), AIMessage(content="ack")] * 6)
        with tempfile.TemporaryDirectory() as directory:
            mw = harden_summarization_middleware(
                create_summarization_middleware(model, FilesystemBackend(root_dir=Path(directory), virtual_mode=True))
            )
            mw._harness_auto_context_defaults = True
            received = []

            async def handler(request):
                received.extend(request.messages)
                return ModelResponse(result=[AIMessage(content="ok")])

            await mw.awrap_model_call(ModelRequest(model=model, messages=messages, state={}), handler)
            self.assertFalse(model.prompts, "tool-only pressure should not require an LLM summary")
            projected = next(item for item in received if isinstance(item, ToolMessage))
            self.assertEqual(projected.tool_call_id, "call-1")
            self.assertIn("large_tool_results", projected.content)
            self.assertEqual(tool.content, "full result " * 20000)
            self.assertTrue(any(Path(directory).rglob("call-1")))

    async def test_every_old_message_reaches_summary_including_first_goal(self):
        model = RecordingModel(responses=["unused"], profile={"max_input_tokens": 128000})
        history = [HumanMessage(content="ORIGINAL_GOAL_KEEP_THIS")]
        markers = []
        for index in range(35):
            marker = f"IMPORTANT_DECISION_{index:03d}"
            markers.append(marker)
            history.extend([HumanMessage(content=marker + " data" * 1000), AIMessage(content="accepted")])
        await middleware(model)._acreate_summary(history)
        seen = "\n".join(model.prompts)
        self.assertIn("ORIGINAL_GOAL_KEEP_THIS", seen)
        for marker in markers:
            self.assertIn(marker, seen)

    async def test_summary_failure_never_becomes_successful_placeholder(self):
        model = RecordingModel(responses=["unused"], overflow=True)
        with self.assertRaises(ContextOverflowError):
            await middleware(model)._acreate_summary([HumanMessage(content="user decision")])

    def test_request_budget_does_not_mutate_cached_model(self):
        model = RecordingModel(responses=["unused"], profile={"max_input_tokens": 128000})
        request = ModelRequest(
            model=model,
            messages=[HumanMessage(content="hello")],
            runtime=SimpleNamespace(config={"configurable": {"max_input_tokens": 64000}}),
        )
        updated = apply_configurable_model_settings(request)
        self.assertEqual(model.profile["max_input_tokens"], 128000)
        self.assertEqual(updated.model.profile["max_input_tokens"], 64000)
        self.assertIsNot(updated.model, model)

    async def test_two_rooms_keep_independent_budgets_during_overlapping_calls(self):
        model = RecordingModel(responses=["unused"], profile={"max_input_tokens": 128000})
        mw = middleware(model)
        entered = 0
        ready = asyncio.Event()

        async def run(cap):
            request = ModelRequest(
                model=model,
                messages=[HumanMessage(content="hello")],
                state={},
                runtime=SimpleNamespace(config={"configurable": {"max_input_tokens": cap}}),
            )

            async def handler(value):
                nonlocal entered
                entered += 1
                if entered == 2:
                    ready.set()
                await asyncio.wait_for(ready.wait(), timeout=2)
                self.assertEqual(value.model.profile["max_input_tokens"], cap)
                return ModelResponse(result=[AIMessage(content="ok")])

            return await mw.awrap_model_call(request, handler)

        await asyncio.gather(run(32000), run(64000))
        self.assertEqual(model.profile["max_input_tokens"], 128000)

    async def test_real_graph_compacts_before_calling_smaller_fallback(self):
        import deepagents
        from deepagents.backends import FilesystemBackend
        from deepagents.middleware.summarization import create_summarization_middleware

        large = RecordingModel(responses=["unused"], fail_chat=True, profile={"max_input_tokens": 128000})
        small = RecordingModel(responses=["unused"], profile={"max_input_tokens": 32000})
        models = {"p/large": large, "p/small": small}
        config = SimpleNamespace(
            model_selector=None, pick_default_model_ref=lambda: "p/large", pick_multimodal_model_ref=lambda: None
        )
        router = ModelRouterMiddleware(config, SimpleNamespace(get_chat_model=models.__getitem__))
        failover = SafeModelFailoverMiddleware(
            health=ModelHealthRegistry(),
            candidates=lambda *_: [AutoRouteCandidate("p/small", 32000)],
            model_for_ref=models.__getitem__,
            max_retries=0,
            initial_delay=0,
            max_delay=0,
            on_failure="error",
        )
        checked = []

        class CheckBudget(AgentMiddleware):
            async def awrap_model_call(inner, request, handler):
                count = sum(breakdown_from_model_request(request).values())
                cap = request.model.profile["max_input_tokens"]
                checked.append((cap, count))
                self.assertLessEqual(count, int(cap * 0.95), "oversized request reached provider")
                return await handler(request)

        def factory(*args, **kwargs):
            mw = harden_summarization_middleware(create_summarization_middleware(*args, **kwargs))
            mw._harness_auto_context_defaults = True
            return mw

        history = [HumanMessage(content="ROOT_GOAL"), AIMessage(content="accepted")]
        for i in range(24):
            history.extend(
                [HumanMessage(content=f"DECISION_{i}: " + "evidence " * 1000), AIMessage(content="accepted")]
            )
        history.append(HumanMessage(content="finish the analysis"))
        with tempfile.TemporaryDirectory() as directory:
            with _patched_summarization_factory(factory):
                graph = deepagents.create_deep_agent(
                    model=large,
                    backend=FilesystemBackend(root_dir=Path(directory), virtual_mode=True),
                    middleware=[router, ModelSettingsMiddleware(), failover, CheckBudget()],
                )
            result = await graph.ainvoke(
                {"messages": history},
                {"configurable": {"model": "p/large", "octop_auto_route": True}},
            )
        self.assertEqual(result["messages"][-1].content, "CHECKPOINT")
        self.assertTrue(any(cap == 32000 for cap, _ in checked))
        self.assertTrue(any("ROOT_GOAL" in prompt and "<primary_objective>" in prompt for prompt in small.prompts))


if __name__ == "__main__":
    unittest.main()
