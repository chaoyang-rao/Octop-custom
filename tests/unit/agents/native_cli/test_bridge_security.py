"""Native bridge authentication, schema limits and literal Windows argv."""

from __future__ import annotations

import asyncio

import aiohttp
import pytest

from octop.infra.agents.native_cli import launch
from octop.infra.agents.native_cli.bridge import NativeCall, NativeToolBridge
from octop.infra.agents.native_cli.launch import resolve_native_launch


@pytest.mark.asyncio
async def test_bridge_never_executes_tools_and_rejects_cross_origin_or_other_key():
    queue = asyncio.Queue()
    bridge = NativeToolBridge(
        queue, [{"name": "allowed", "description": "test", "inputSchema": {"type": "object"}}]
    )
    await bridge.start()
    try:
        async with aiohttp.ClientSession() as client:
            for headers in [
                {},
                {"Authorization": "Bearer wrong"},
                {"Authorization": "Bearer " + bridge.token, "Origin": "https://evil.example"},
            ]:
                async with client.post(
                    bridge.url,
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                    headers=headers,
                ) as result:
                    assert result.status == 403

            async def call():
                async with client.post(
                    bridge.url,
                    headers={"Authorization": "Bearer " + bridge.token},
                    json={
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/call",
                        "params": {"name": "allowed", "arguments": {"value": "one"}},
                    },
                ) as response:
                    return await response.json()

            task = asyncio.create_task(call())
            pending = await asyncio.wait_for(queue.get(), timeout=2)
            assert isinstance(pending, NativeCall) and not task.done()
            bridge.feed(pending.call_id, "returned by actual graph", failed=False)
            answer = await task
            assert answer["result"]["content"][0]["text"] == "returned by actual graph"
    finally:
        await bridge.close()


def test_windows_npx_uses_node_without_shell_or_arg_expansion(monkeypatch, tmp_path):
    shim = tmp_path / "npx.cmd"
    shim.write_text("unused")
    script = tmp_path / "node_modules" / "npm" / "bin" / "npx-cli.js"
    script.parent.mkdir(parents=True)
    script.write_text("unused")
    node = tmp_path / "node.exe"
    node.write_text("unused")
    monkeypatch.setattr(launch.sys, "platform", "win32")
    monkeypatch.setattr(
        launch.shutil, "which", lambda command: str(shim if command == "npx" else node)
    )
    executable, args = resolve_native_launch("npx", ["-y", "package@1.0.0", "literal & value"])
    assert executable == str(node)
    assert args == [str(script), "-y", "package@1.0.0", "literal & value"]
    assert "cmd.exe" not in executable
