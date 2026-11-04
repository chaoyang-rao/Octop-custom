"""Offline graph acceptance for the frozen harness's scoped memory wiring."""

from __future__ import annotations

import asyncio
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import HumanMessage, get_buffer_string
from octop_harness.agent import HarnessAgent
from octop_harness.config import HarnessAgentConfig, ModelConfig, ProviderConfig
from octop_harness.llm.factory import ChatModelFactory
from octop_harness.memory.runtime import MemoryRuntime
from octop_harness.middleware.memory import MemoryMiddleware
from pydantic import Field


class RecordingModel(FakeListChatModel):
    prompts: list[str] = Field(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, **kwargs):
        self.prompts.append(get_buffer_string(messages))
        return super()._generate(messages, **kwargs)

    async def _agenerate(self, messages, **kwargs):
        return self._generate(messages, **kwargs)


class ScopedRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_agent_keeps_legacy_checkpoint_and_closes_scopes_asynchronously(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            spec = {
                "namespace": "shared_project",
                "backend": {"type": "sqlite", "db_path": str(root / "project.sqlite")},
            }

            def resolve(cfg):
                if cfg.get("user") != "1" or cfg.get("thread_id") != "actual":
                    raise PermissionError("not owned")
                return {
                    "scopes": {"project": spec},
                    "default_scope": "project",
                    "recall_scopes": ["project"],
                    "scope_id": "shared_project",
                    "source": {
                        "user_id": 1,
                        "agent_id": "a",
                        "thread_id": "actual",
                        "room_agent_id": "a",
                        "project_path": "project",
                        "project_name": "Project",
                    },
                }

            providers = [
                ProviderConfig(
                    id="offline",
                    base_url="http://127.0.0.1:1",
                    api_key="offline-placeholder",
                    models=[ModelConfig(id="fake", max_input_tokens=64000)],
                )
            ]
            cfg = HarnessAgentConfig(
                name="legacy_agent",
                workspace_dir=root,
                backend="filesystem",
                providers=providers,
                default_model="offline/fake",
                bootstrap_enabled=False,
                memory_aux_model_enabled=False,
                memory_scope_resolver=resolve,
                memory_extract_on_session_end=False,
                session_log_enabled=False,
            )
            model = RecordingModel(responses=["Offline expert response"])
            factory = ChatModelFactory(providers)
            with (
                patch.object(factory, "get_chat_model", return_value=model),
                patch.object(HarnessAgent, "_init_logging", return_value=None),
            ):
                agent = HarnessAgent(cfg, model_factory=factory, agent_id="a")
                try:
                    await agent.call(
                        {
                            "messages": "User confirmed project codename jade",
                            "thread_id": "actual",
                            "user": "1",
                            "configurable": {"user": "1"},
                        }
                    )
                    with agent._memory_runtime.middleware.pause_background():
                        pass
                    view = agent.memory_for_context({"thread_id": "actual", "user": "1"})
                    self.assertIn("jade", str(view.search("jade")))
                    self.assertEqual(agent.memory.namespace, "legacy_agent")
                finally:
                    await agent.aclose()
            self.assertIsNone(agent.memory)

    async def test_close_drains_accepted_workers_before_releasing_scopes(self):
        started, release = threading.Event(), threading.Event()
        order = []
        middleware = MemoryMiddleware(service=None, jsonl_enabled=False)
        runtime = MemoryRuntime.__new__(MemoryRuntime)
        runtime._config = SimpleNamespace(memory_scope_resolver=lambda _: {})
        runtime._middleware = middleware
        runtime._service = SimpleNamespace(close=lambda: order.append("closed"))
        runtime._memory_key = runtime._memory = None

        def worker():
            started.set()
            if not release.wait(5):
                raise TimeoutError("test worker was not released")
            order.append("captured")

        middleware._submit_background(worker, label="test-capture")
        await asyncio.to_thread(started.wait, 5)
        closing = asyncio.create_task(asyncio.to_thread(runtime.close))
        try:
            with self.assertRaises(TimeoutError):
                await asyncio.wait_for(asyncio.shield(closing), 0.02)
            self.assertEqual(order, [])
        finally:
            release.set()
            await closing
        self.assertEqual(order, ["captured", "closed"])

    async def test_real_graph_recall_and_capture_obey_scope_without_model_network(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)

            def resolve(cfg):
                tid = str(cfg.get("thread_id") or "")
                if cfg.get("user") != "1" or tid not in {"one", "two", "different"}:
                    raise PermissionError("not owned")
                project = "different" if tid == "different" else "same"
                specs = {
                    name: {
                        "namespace": f"test_{name}_{identity}",
                        "backend": {
                            "type": "sqlite",
                            "db_path": str(root / f"{name}_{identity}.sqlite"),
                        },
                    }
                    for name, identity in (
                        ("user", "one"),
                        ("project", project),
                        ("expert", "expert"),
                        ("session", tid),
                    )
                }
                return {
                    "scopes": specs,
                    "default_scope": "project",
                    "recall_scopes": ["session", "user", "project"],
                    "scope_id": specs["project"]["namespace"],
                    "source": {
                        "user_id": 1,
                        "agent_id": "a",
                        "thread_id": tid,
                        "room_agent_id": "a",
                        "project_path": project,
                        "project_name": project,
                    },
                }

            cfg = HarnessAgentConfig(
                name="legacy",
                workspace_dir=root,
                memory_aux_model_enabled=False,
                memory_scope_resolver=resolve,
                memory_extract_on_session_end=False,
                session_log_enabled=False,
            )
            runtime = MemoryRuntime(
                config=cfg, workspace_path=root, model_factory=SimpleNamespace()
            )
            mw = runtime.build_middleware()
            model = RecordingModel(responses=["Assistant conjecture is ultraviolet"])
            graph = create_agent(model, tools=[], middleware=[mw])
            try:
                await graph.ainvoke(
                    {
                        "messages": [
                            HumanMessage(content="Project confirmed codename is jade", id="u1")
                        ]
                    },
                    config={"configurable": {"thread_id": "one", "user": "1"}},
                )
                with mw.pause_background():
                    pass
                result = await graph.ainvoke(
                    {"messages": [HumanMessage(content="jade", id="u2")]},
                    config={"configurable": {"thread_id": "two", "user": "1"}},
                )
                self.assertIn("Project confirmed codename", model.prompts[-1])
                self.assertNotIn("ultraviolet", model.prompts[-1])
                with mw.pause_background():
                    pass
                await graph.ainvoke(
                    {"messages": [HumanMessage(content="jade", id="u3")]},
                    config={"configurable": {"thread_id": "different", "user": "1"}},
                )
                self.assertNotIn("Project confirmed codename", model.prompts[-1])
                self.assertEqual(runtime.memory.namespace, "legacy")
                self.assertEqual(len(runtime.build_tools()), 3)
                self.assertNotIn("memory_scope_resolver", cfg.to_dict())
                self.assertIsNone(
                    HarnessAgentConfig.from_dict(
                        {**cfg.to_dict(), "memory_scope_resolver": "forged"}
                    ).memory_scope_resolver
                )
                self.assertTrue(result["messages"][0].additional_kwargs.get("_octop_memory_recall"))
            finally:
                runtime.close()

    async def test_invalid_scope_does_not_fall_back_to_legacy(self):
        with tempfile.TemporaryDirectory() as temp:

            def deny(_):
                raise PermissionError("denied")

            cfg = HarnessAgentConfig(
                name="legacy",
                workspace_dir=temp,
                memory_aux_model_enabled=False,
                memory_scope_resolver=deny,
                memory_extract_on_session_end=False,
                session_log_enabled=False,
            )
            runtime = MemoryRuntime(
                config=cfg, workspace_path=Path(temp), model_factory=SimpleNamespace()
            )
            runtime._service._root.save("Legacy private fact is secret")
            with self.assertRaises(PermissionError):
                runtime.service.for_context({"thread_id": "other", "user": "2"})
            runtime.close()


if __name__ == "__main__":
    unittest.main()
