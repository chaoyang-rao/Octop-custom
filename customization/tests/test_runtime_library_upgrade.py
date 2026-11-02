"""Runtime upgrade contracts; no ACP processes, user homes, or LLM calls."""

import asyncio
import tempfile
import unittest
from contextlib import asynccontextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from mcp.shared.exceptions import McpError
from mcp.types import ErrorData

from octop_harness.agent import HarnessAgent
from octop_harness.config import HarnessAgentConfig
from octop_harness.middleware.filesystem_guard import FilesystemGuardMiddleware
from octop_harness.middleware.mcp_tool_error import McpToolErrorMiddleware
from octop_harness.middleware.tool_failbreak import (
    ToolFailbreakError,
    ToolFailbreakMiddleware,
    tool_failbreak_scope,
)


@asynccontextmanager
async def invocation():
    yield


class HitlUpgradeTests(unittest.IsolatedAsyncioTestCase):
    def agent(self, resume_stream, paused):
        agent = HarnessAgent.__new__(HarnessAgent)
        agent._get_protocol = lambda protocol: SimpleNamespace(resume_stream=resume_stream)
        agent._invocation = invocation
        agent._hitl_resume_configs = paused
        return agent

    async def test_resume_preserves_paused_scope_and_refreshes_trusted_bindings(self):
        captured = {}

        async def resume_stream(thread_id, decisions, config):
            captured.update(deepcopy(config))
            config["configurable"]["actor"]["id"] = "protocol-mutation"
            yield {"type": "done"}

        cached = {
            "configurable": {
                "thread_id": "t1",
                "user_id": 7,
                "tools_disabled": ["execute"],
                "octop_project_path": "old-project",
                "actor": {"id": "old-actor"},
            },
            "metadata": {"trace": "paused"},
        }
        original = deepcopy(cached)
        other = {"configurable": {"thread_id": "t2", "user_id": 8}}
        agent = self.agent(resume_stream, {"t1": cached, "t2": other})
        supplied = {
            "thread_id": "forged",
            "octop_project_path": "current-project",
            "task_attempt": 3,
            "actor": {"id": "current-actor"},
        }
        chunks = [chunk async for chunk in agent.resume_hitl("t1", [], configurable=supplied)]
        self.assertEqual(chunks, [{"type": "done"}])
        self.assertEqual(captured["configurable"]["thread_id"], "t1")
        self.assertEqual(captured["configurable"]["user_id"], 7)
        self.assertEqual(captured["configurable"]["tools_disabled"], ["execute"])
        self.assertEqual(captured["configurable"]["octop_project_path"], "current-project")
        self.assertEqual(captured["configurable"]["task_attempt"], 3)
        self.assertEqual(captured["configurable"]["actor"], {"id": "current-actor"})
        self.assertEqual(captured["metadata"], {"trace": "paused"})
        self.assertEqual(cached, original)
        self.assertEqual(supplied["actor"], {"id": "current-actor"})
        self.assertNotIn("t1", agent._hitl_resume_configs)
        self.assertIs(agent._hitl_resume_configs["t2"], other)

    async def test_repeated_pause_keeps_refreshed_scope_for_next_resume(self):
        configs = []

        async def resume_stream(thread_id, decisions, config):
            configs.append(deepcopy(config))
            yield {"type": "hitl_required"} if len(configs) == 1 else {"type": "done"}

        agent = self.agent(
            resume_stream,
            {"t1": {"configurable": {"thread_id": "t1", "task_attempt": 1, "user_id": 7}}},
        )
        first = [
            chunk async for chunk in agent.resume_hitl("t1", [], configurable={"task_attempt": 2})
        ]
        self.assertEqual(first, [{"type": "hitl_required"}])
        self.assertEqual(agent._hitl_resume_configs["t1"]["configurable"]["task_attempt"], 2)
        second = [chunk async for chunk in agent.resume_hitl("t1", [])]
        self.assertEqual(second, [{"type": "done"}])
        self.assertEqual(configs[1]["configurable"]["task_attempt"], 2)
        self.assertEqual(configs[1]["configurable"]["user_id"], 7)
        self.assertNotIn("t1", agent._hitl_resume_configs)

    async def test_resume_without_cached_scope_uses_host_scope_and_authoritative_thread(self):
        captured = {}

        async def resume_stream(thread_id, decisions, config):
            captured.update(config)
            yield {"type": "done"}

        agent = self.agent(resume_stream, {})
        chunks = [
            chunk
            async for chunk in agent.resume_hitl(
                "t1", [], configurable={"thread_id": "wrong", "octop_project_path": "project"}
            )
        ]
        self.assertEqual(chunks, [{"type": "done"}])
        self.assertEqual(
            captured["configurable"], {"thread_id": "t1", "octop_project_path": "project"}
        )

    async def test_cancelled_resume_keeps_paused_scope_and_cancellation(self):
        async def resume_stream(thread_id, decisions, config):
            raise asyncio.CancelledError
            yield  # pragma: no cover - keep an async generator

        cached = {"configurable": {"thread_id": "t1", "user_id": 7}}
        agent = self.agent(resume_stream, {"t1": cached})
        with self.assertRaises(asyncio.CancelledError):
            async for _ in agent.resume_hitl("t1", []):
                pass
        self.assertIs(agent._hitl_resume_configs["t1"], cached)


class McpFailureUpgradeTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_middleware_order_counts_softened_mcp_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            agent = HarnessAgent.__new__(HarnessAgent)
            agent._config = HarnessAgentConfig(
                workspace_dir=Path(directory),
                model_retry_enabled=False,
                media_offload_enabled=False,
                pii_enabled=False,
                bootstrap_enabled=False,
                tool_guard_enabled=False,
            )
            agent._model_factory = SimpleNamespace()
            agent._get_protocol = lambda name=None: None
            agent._peek_backend_mount = lambda: (directory, False)
            agent._workspace = None
            agent._memory_runtime = SimpleNamespace(build_middleware=lambda: None)
            agent._team_manager = None
            agent._mcp_tool_name_set = frozenset()
            agent._default_max_input_tokens = lambda: 0
            agent._build_tool_search_middleware = lambda: None
            agent._build_bootstrap_middleware = lambda: None
            chain = agent._build_middleware()

        failbreak = next(m for m in chain if isinstance(m, ToolFailbreakMiddleware))
        mcp_errors = next(m for m in chain if isinstance(m, McpToolErrorMiddleware))
        filesystem = next(m for m in chain if isinstance(m, FilesystemGuardMiddleware))
        self.assertLess(chain.index(failbreak), chain.index(mcp_errors))
        self.assertLess(chain.index(failbreak), chain.index(filesystem))
        request = SimpleNamespace(tool_call={"name": "mcp/edit", "id": "call-1", "args": {}})

        async def tool(_request):
            raise McpError(ErrorData(code=-32602, message="Invalid field type"))

        async def softened(_request):
            return await mcp_errors.awrap_tool_call(_request, tool)

        with tool_failbreak_scope():
            first = await failbreak.awrap_tool_call(request, softened)
            self.assertEqual(first.status, "error")
            self.assertEqual(first.tool_call_id, "call-1")
            self.assertIn("Fix the tool arguments", first.content)
            for _ in range(3):
                await failbreak.awrap_tool_call(request, softened)
            with self.assertRaises(ToolFailbreakError):
                await failbreak.awrap_tool_call(request, softened)


if __name__ == "__main__":
    unittest.main()
