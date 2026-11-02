"""Regression checks for the portable runtime's pending tool-loop protection."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from langchain_core.messages import ToolMessage

from octop_harness.middleware.tool_failbreak import (
    ToolFailbreakError,
    ToolFailbreakMiddleware,
    tool_failbreak_scope,
)


class ToolFailbreakTests(unittest.IsolatedAsyncioTestCase):
    async def test_truncation_keeps_call_identity_and_never_changes_tool_arguments(self):
        request = SimpleNamespace(tool_call={"name": "read_file", "args": {"path": "report.md"}})
        result = ToolMessage(content="HEAD" + "x" * 100 + "TAIL", tool_call_id="call-1")
        middleware = ToolFailbreakMiddleware(max_result_chars=16)
        with tool_failbreak_scope():
            truncated = await middleware.awrap_tool_call(request, AsyncMock(return_value=result))
        self.assertTrue(truncated.content.startswith("HEAD"))
        self.assertTrue(truncated.content.endswith("TAIL"))
        self.assertEqual(truncated.tool_call_id, "call-1")
        self.assertEqual(request.tool_call["args"], {"path": "report.md"})
        self.assertEqual(result.content, "HEAD" + "x" * 100 + "TAIL")

    async def test_failure_limit_success_reset_and_new_turn_isolation(self):
        request = SimpleNamespace(tool_call={"name": "edit_file"})
        error = ToolMessage(content="String not found", tool_call_id="call-1", status="error")
        success = ToolMessage(content="Updated", tool_call_id="call-2")
        middleware = ToolFailbreakMiddleware(max_consecutive_failures=2)
        fail = AsyncMock(return_value=error)
        with tool_failbreak_scope():
            await middleware.awrap_tool_call(request, fail)
            await middleware.awrap_tool_call(request, AsyncMock(return_value=success))
            await middleware.awrap_tool_call(request, fail)
            with self.assertRaises(ToolFailbreakError):
                await middleware.awrap_tool_call(request, fail)
        with tool_failbreak_scope():
            self.assertIs(await middleware.awrap_tool_call(request, fail), error)

    async def test_cancellation_is_preserved(self):
        with tool_failbreak_scope(), self.assertRaises(asyncio.CancelledError):
            await ToolFailbreakMiddleware().awrap_tool_call(
                SimpleNamespace(tool_call={"name": "execute"}),
                AsyncMock(side_effect=asyncio.CancelledError),
            )


if __name__ == "__main__":
    unittest.main()
