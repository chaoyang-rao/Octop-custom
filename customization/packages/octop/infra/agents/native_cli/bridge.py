"""Ephemeral loopback MCP server: enqueue tool calls, never execute them here."""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass
from typing import Any

from aiohttp import web

from octop.infra.agents.native_cli.config import NativeCLIError
from octop.infra.agents.native_cli.media import mcp_content


@dataclass
class NativeCall:
    call_id: str
    name: str
    arguments: dict[str, Any]
    result: asyncio.Future[dict[str, Any]]
    permission: bool = False


class NativeToolBridge:
    def __init__(self, events: asyncio.Queue[Any], schemas: list[dict[str, Any]]) -> None:
        self.events = events
        self.schemas = {
            str(tool["name"]): tool for tool in schemas if tool["name"] != "native_cli_permission"
        }
        self.token = secrets.token_urlsafe(32)
        self.port = 0
        self.supports_images = True
        self.runner: web.AppRunner | None = None
        self.pending: dict[str, NativeCall] = {}

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/mcp"

    async def start(self) -> None:
        app = web.Application(client_max_size=1024 * 1024)
        app.router.add_post("/mcp", self._handle)
        self.runner = web.AppRunner(app, access_log=None)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        server = site._server
        sockets = getattr(server, "sockets", ()) if server is not None else ()
        if not sockets:
            await self.close()
            raise RuntimeError("native_cli_bridge_failed")
        self.port = int(sockets[0].getsockname()[1])

    async def enqueue(
        self, name: str, arguments: dict[str, Any], *, permission: bool = False
    ) -> dict[str, Any]:
        if len(self.pending) >= 32:
            return {"isError": True, "content": [{"type": "text", "text": "Tool queue is full"}]}
        call_id = "native_" + secrets.token_hex(12)
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        call = NativeCall(call_id, name, arguments, future, permission)
        self.pending[call_id] = call
        await self.events.put(call)
        try:
            return await future
        finally:
            self.pending.pop(call_id, None)

    async def _handle(self, request: web.Request) -> web.Response:
        expected_host = f"127.0.0.1:{self.port}"
        if (
            request.headers.get("Origin")
            or request.host != expected_host
            or not secrets.compare_digest(
                request.headers.get("Authorization", ""), f"Bearer {self.token}"
            )
        ):
            return web.Response(status=403)
        try:
            payload = await request.json()
        except (ValueError, UnicodeError):
            return web.json_response(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": "Invalid JSON"},
                },
                status=400,
            )
        if not isinstance(payload, dict):
            return web.Response(status=400)
        identifier = payload.get("id")
        if identifier is None:
            return web.Response(status=202)
        result: dict[str, Any]
        method = payload.get("method")
        if method == "initialize":
            result = {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "octop-native-tools", "version": "1.0"},
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": list(self.schemas.values())}
        elif method == "tools/call":
            params = payload.get("params")
            if (
                not isinstance(params, dict)
                or params.get("name") not in self.schemas
                or not isinstance(params.get("arguments", {}), dict)
            ):
                return web.json_response(
                    {
                        "jsonrpc": "2.0",
                        "id": identifier,
                        "error": {"code": -32602, "message": "Tool not available"},
                    }
                )
            result = await self.enqueue(str(params["name"]), dict(params.get("arguments") or {}))
        else:
            return web.json_response(
                {
                    "jsonrpc": "2.0",
                    "id": identifier,
                    "error": {"code": -32601, "message": "Method not found"},
                }
            )
        return web.json_response({"jsonrpc": "2.0", "id": identifier, "result": result})

    def feed(self, call_id: str, content: Any, *, failed: bool) -> bool:
        call = self.pending.get(call_id)
        if call is None or call.result.done():
            return False
        try:
            projected = mcp_content(content, supports_images=self.supports_images)
        except NativeCLIError as exc:
            call.result.set_result(
                {"isError": True, "content": [{"type": "text", "text": str(exc)}]}
            )
            raise
        call.result.set_result({"isError": failed, "content": projected})
        return True

    async def close(self) -> None:
        for call in list(self.pending.values()):
            if not call.result.done():
                call.result.cancel()
        self.pending.clear()
        if self.runner is not None:
            await self.runner.cleanup()
            self.runner = None
