"""Capability and revocation guard for device sessions on every ASGI surface.

The context also covers desktop/phone streams that authenticate in their first
frame, rather than in the WebSocket URL. Ordinary JWT sessions are untouched.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from urllib.parse import parse_qs, urlsplit

from starlette.types import ASGIApp, Message, Receive, Scope, Send
from starlette.websockets import WebSocketDisconnect

from octop.infra.errors import OctopError
from octop.infra.mobile_access.access import (
    CURRENT_MOBILE_REQUEST,
    MobileRequestContext,
    is_mobile_token,
    resolve_mobile_user,
)
from octop.infra.utils.locale import normalize_locale


class MobileDeviceAccessMiddleware:
    def __init__(self, app: ASGIApp, *, server: Any, recheck_seconds: float = 10) -> None:
        self.app = app
        self.server = server
        self.recheck_seconds = recheck_seconds

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        fallback_locale = normalize_locale(
            headers.get(b"accept-language", b"").decode("latin-1").split(",")[0]
        )
        host = urlsplit("//" + headers.get(b"host", b"").decode("latin-1")).hostname
        client = scope.get("client")
        secure = scope.get("scheme") in {"https", "wss"} or bool(
            client
            and client[0] in {"127.0.0.1", "::1"}
            and host in {"127.0.0.1", "::1", "localhost"}
        )
        context = MobileRequestContext(
            str(scope["path"]),
            "WS" if scope["type"] == "websocket" else str(scope["method"]),
            secure_transport=secure,
        )
        marker = CURRENT_MOBILE_REQUEST.set(context)
        authorization = headers.get(b"authorization", b"").decode("latin-1")
        query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
        token = (
            authorization[7:].strip()
            if authorization.lower().startswith("bearer ")
            else str((query.get("token") or query.get("access_token") or [""])[0])
        )
        closed = False
        last_checked = 0.0

        async def check(force: bool = False) -> None:
            nonlocal last_checked
            active = context.token
            if active is None or (not force and time.monotonic() - last_checked < 1):
                return
            await asyncio.to_thread(
                resolve_mobile_user, self.server, active, path=context.path, method=context.method
            )
            last_checked = time.monotonic()

        async def guarded_receive() -> Message:
            nonlocal closed
            while True:
                try:
                    await check(force=True)
                    return await asyncio.wait_for(receive(), timeout=self.recheck_seconds)
                except TimeoutError:
                    continue
                except OctopError:
                    if not closed:
                        closed = True
                        await send(
                            {
                                "type": "websocket.close",
                                "code": 4401,
                                "reason": "device session revoked or expired",
                            }
                        )
                    return {"type": "websocket.disconnect", "code": 4401}

        async def guarded_send(message: Message) -> None:
            nonlocal closed
            if closed:
                return
            try:
                await check()
            except OctopError:
                closed = True
                await send(
                    {
                        "type": "websocket.close",
                        "code": 4401,
                        "reason": "device session revoked or expired",
                    }
                )
                raise WebSocketDisconnect(code=4401) from None
            await send(message)

        response_started = False

        async def guarded_http_send(message: Message) -> None:
            nonlocal closed, response_started
            if closed:
                return
            try:
                await check()
            except OctopError as exc:
                closed = True
                if not response_started:
                    import json

                    body = json.dumps(
                        exc.to_envelope(locale=context.locale or fallback_locale)
                    ).encode()
                    await send(
                        {
                            "type": "http.response.start",
                            "status": exc.status,
                            "headers": [(b"content-type", b"application/json")],
                        }
                    )
                    await send({"type": "http.response.body", "body": body})
                else:
                    # Stop disclosing SSE/download output while allowing an accepted
                    # server-side operation to finish and retain its history.
                    await send({"type": "http.response.body", "body": b"", "more_body": False})
                return
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            if is_mobile_token(token):
                context.token = token
                try:
                    await check(force=True)
                except OctopError as exc:
                    if scope["type"] == "websocket":
                        await send(
                            {"type": "websocket.close", "code": 4403 if exc.status == 403 else 4401}
                        )
                    else:
                        import json

                        body = json.dumps(
                            exc.to_envelope(
                                locale=context.locale
                                or normalize_locale(
                                    headers.get(b"accept-language", b"")
                                    .decode("latin-1")
                                    .split(",")[0]
                                )
                            )
                        ).encode()
                        await send(
                            {
                                "type": "http.response.start",
                                "status": exc.status,
                                "headers": [(b"content-type", b"application/json")],
                            }
                        )
                        await send({"type": "http.response.body", "body": body})
                    return
            if scope["type"] == "websocket":
                await self.app(scope, guarded_receive, guarded_send)
            else:
                await self.app(scope, receive, guarded_http_send)
        finally:
            CURRENT_MOBILE_REQUEST.reset(marker)
