"""Refresh enterprise authorization on live WebSocket activity, including first-frame auth."""

from __future__ import annotations

import asyncio
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send
from starlette.websockets import WebSocketDisconnect

from octop.infra.auth.enterprise import (
    CURRENT_ENTERPRISE_SOCKET,
    EnterpriseSocketContext,
    client_for,
    enterprise_error,
)
from octop.infra.errors import ErrorCode, OctopError


class EnterpriseSocketMiddleware:
    def __init__(self, app: ASGIApp, *, server: Any) -> None:
        self.app = app
        self.server = server

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        client = client_for(self.server) if scope["type"] == "websocket" else None
        if client is None:
            await self.app(scope, receive, send)
            return
        context = EnterpriseSocketContext()
        marker = CURRENT_ENTERPRISE_SOCKET.set(context)
        closed = False

        async def check() -> None:
            if context.user is None:
                return
            previous = set(context.user.permissions)
            current = await client.authorize(context.user)
            if set(current.permissions) != previous:
                raise enterprise_error(ErrorCode.ENTERPRISE_ACCESS_DENIED)

        async def close(exc: OctopError) -> None:
            nonlocal closed
            if not closed:
                closed = True
                await send({"type": "websocket.close", "code": 4403, "reason": exc.code.value})

        async def guarded_receive() -> Message:
            while not closed:
                try:
                    message = await asyncio.wait_for(receive(), timeout=10)
                    await check()
                    return message
                except TimeoutError:
                    try:
                        await check()
                    except OctopError as exc:
                        await close(exc)
                except OctopError as exc:
                    await close(exc)
            return {"type": "websocket.disconnect", "code": 4403}

        async def guarded_send(message: Message) -> None:
            if closed:
                return
            try:
                await check()
            except OctopError as exc:
                await close(exc)
                raise WebSocketDisconnect(code=4403) from None
            await send(message)

        try:
            await self.app(scope, guarded_receive, guarded_send)
        except WebSocketDisconnect:
            if not closed:
                raise
        finally:
            CURRENT_ENTERPRISE_SOCKET.reset(marker)
