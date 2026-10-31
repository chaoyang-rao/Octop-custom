"""Real ASGI auth integration: constrained HTTP and first-frame WebSockets."""

from types import SimpleNamespace
from typing import Annotated

import httpx
import pytest
from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from tests.unit.mobile_access.test_mobile_access_service import paired
from tests.unit.mobile_access.test_mobile_access_service import service as service

from octop.api.deps import current_user, resolve_user_from_token, sign_token
from octop.api.middleware import jwt_auth
from octop.api.middleware.mobile_device import MobileDeviceAccessMiddleware
from octop.api.routers.mobile_access import router
from octop.infra.errors import OctopError
from octop.infra.users.identity import User


@pytest.fixture
def app_server(service):
    owner = User(id=1, username="owner", role="admin", display_name="Owner")
    secret = service._secrets.get_or_create(
        "jwt", lambda: b"local-test-signing-key-not-a-real-secret"
    )
    server = SimpleNamespace(
        _started=True,
        _mobile_access_service=service,
        services=SimpleNamespace(
            settings_repo=service._settings,
            secret_repo=service._secrets,
            config=SimpleNamespace(access_token_ttl_seconds=86400),
        ),
        user_manager=SimpleNamespace(get_by_id=lambda uid: owner if uid == 1 else None),
    )
    app = FastAPI()
    app.state.octop_server = server
    app.include_router(router, prefix="/api/mobile-access")

    @app.exception_handler(OctopError)
    async def handle_error(request, error):
        return JSONResponse(status_code=error.status, content=error.to_envelope())

    @app.get("/api/auth/me")
    async def profile(user: Annotated[User, Depends(current_user)]):
        return {"id": user.id, "role": user.role, "permissions": user.permissions}

    @app.get("/api/agents")
    async def agents(user: Annotated[User, Depends(current_user)]):
        return []

    @app.get("/api/models")
    async def private_models(user: Annotated[User, Depends(current_user)]):
        return {"private": "must not reach a device"}

    @app.websocket("/api/notifications/ws")
    async def notifications(websocket: WebSocket):
        raw = websocket.headers.get("authorization", "")[7:]
        user = resolve_user_from_token(server, raw)
        await websocket.accept()
        await websocket.send_json({"type": "ready", "user_id": user.id})
        try:
            while True:
                await websocket.receive_text()
                await websocket.send_json({"type": "pong"})
        except WebSocketDisconnect:
            pass

    @app.websocket("/api/desktop/stream")
    async def first_frame(websocket: WebSocket):
        await websocket.accept()
        frame = await websocket.receive_json()
        try:
            resolve_user_from_token(server, frame["token"])
        except OctopError:
            await websocket.close(code=4403)
            return
        await websocket.send_json({"private": "desktop"})

    jwt_auth.install(app, server)
    app.add_middleware(MobileDeviceAccessMiddleware, server=server, recheck_seconds=0.02)
    account_token = sign_token(secret, sub=1, uname="owner", role="admin")
    return app, server, owner, account_token


@pytest.mark.asyncio
async def test_device_uses_existing_auth_without_jwt_upgrade_and_denies_config(app_server, service):
    app, _, _, account_token = app_server
    _, result = await paired(service)
    headers = {"Authorization": "Bearer " + result["access_token"]}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://octop.test"
    ) as client:
        profile = await client.get("/api/auth/me", headers=headers)
        assert profile.status_code == 200 and profile.json()["role"] == "user"
        assert "X-Octop-Access-Token" not in profile.headers
        assert (await client.get("/api/agents", headers=headers)).status_code == 200
        assert (await client.get("/api/models", headers=headers)).status_code == 403
        assert (await client.get("/api/mobile-access/devices", headers=headers)).status_code == 403
        assert (
            await client.post("/api/auth/change-password", headers=headers, json={})
        ).status_code == 403
        assert (
            await client.get("/api/models", headers={"Authorization": "Bearer " + account_token})
        ).status_code == 200


@pytest.mark.asyncio
async def test_pairing_endpoints_are_exactly_public_and_secrets_are_not_cached(app_server):
    app, _, _, account_token = app_server
    headers = {"Authorization": "Bearer " + account_token}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://octop.test"
    ) as client:
        request = await client.post(
            "/api/mobile-access/pairings/request", json={"name": "Phone", "platform": "ios"}
        )
        assert request.status_code == 200
        assert request.headers["Cache-Control"] == "no-store"
        assert (await client.get("/api/mobile-access/devices")).status_code == 401
        challenge = request.json()
        assert (
            await client.post(
                "/api/mobile-access/pairings/inspect", json={"code": challenge["user_code"]}
            )
        ).status_code == 401
        approved = await client.post(
            "/api/mobile-access/pairings/approve",
            headers=headers,
            json={"code": challenge["user_code"], "scopes": ["chat"]},
        )
        assert approved.status_code == 200 and "access_token" not in approved.text
        exchange = await client.post(
            "/api/mobile-access/pairings/exchange",
            json={"pairing_secret": challenge["pairing_secret"]},
        )
        assert exchange.status_code == 200 and exchange.json()["status"] == "approved"


@pytest.mark.asyncio
async def test_insecure_public_pairing_cannot_spoof_forwarded_https(app_server):
    app, *_ = app_server
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("198.51.100.23", 1234)),
        base_url="http://octop.test",
    ) as client:
        response = await client.post(
            "/api/mobile-access/pairings/request",
            headers={"X-Forwarded-Proto": "https"},
            json={"name": "Phone", "platform": "ios"},
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_idle_websocket_is_closed_after_server_side_revoke(app_server, service):
    app, _, _, account_token = app_server
    _, result = await paired(service)
    with (
        TestClient(app) as client,
        client.websocket_connect(
            "wss://octop.test/api/notifications/ws",
            headers={"Authorization": "Bearer " + result["access_token"]},
        ) as socket,
    ):
        assert socket.receive_json()["user_id"] == 1
        response = client.delete(
            "/api/mobile-access/devices/" + result["device_id"],
            headers={"Authorization": "Bearer " + account_token},
        )
        assert response.status_code == 204
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_json()
        assert closed.value.code == 4401


@pytest.mark.asyncio
async def test_first_frame_control_auth_cannot_bypass_mobile_scope(app_server, service):
    app, *_ = app_server
    _, result = await paired(service)
    with (
        TestClient(app) as client,
        client.websocket_connect("wss://octop.test/api/desktop/stream") as socket,
    ):
        socket.send_json({"token": result["access_token"]})
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_json()
        assert closed.value.code == 4403


@pytest.mark.asyncio
async def test_chat_device_can_read_voice_capability_and_transcribe_but_not_manage(
    app_server, service, monkeypatch
):
    from unittest.mock import AsyncMock

    from octop.api.routers import voice

    app, *_ = app_server
    fake = SimpleNamespace(
        get_active=lambda: {"stt": "fixture", "tts": "fixture"},
        realtime_stt_config=lambda: None,
        transcribe=AsyncMock(
            return_value=SimpleNamespace(text="fixture transcript", confidence=1.0)
        ),
    )
    monkeypatch.setattr(voice, "_voice_manager", lambda server: fake)
    app.include_router(voice.router, prefix="/api/voice")
    app.include_router(voice.admin_router, prefix="/api/admin/voice/providers")
    _, result = await paired(service, ["chat"])
    headers = {"Authorization": "Bearer " + result["access_token"]}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://octop.test"
    ) as client:
        capability = await client.get("/api/voice/active", headers=headers)
        assert capability.status_code == 200 and capability.json()["stt"] == "fixture"
        transcription = await client.post(
            "/api/voice/stt",
            headers=headers,
            files={
                "audio": (
                    "fixture.webm",
                    b"fictional test bytes, not microphone audio",
                    "audio/webm",
                )
            },
        )
        assert (
            transcription.status_code == 200
            and transcription.json()["text"] == "fixture transcript"
        )
        fake.transcribe.assert_awaited_once()
        assert (await client.get("/api/voice/providers", headers=headers)).status_code == 403
        assert (
            await client.put("/api/voice/active", headers=headers, json={"stt": "other"})
        ).status_code == 403
        assert (
            await client.post("/api/admin/voice/providers", headers=headers, json={})
        ).status_code == 403


@pytest.mark.asyncio
async def test_task_widget_get_never_mutates_and_post_requires_current_device(app_server, service):
    from tests.unit.mobile_access.test_task_actions import Tasks

    app, server, _, account_token = app_server
    server.task_manager = Tasks()
    _, device = await paired(service, ["tasks"])
    headers = {"Authorization": "Bearer " + device["access_token"]}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://octop.test"
    ) as client:
        url = "/api/mobile-access/task-actions/"
        nav = await client.post(
            url + "navigation", headers=headers, json={"task_id": "TASK", "attempt": 1}
        )
        assert nav.status_code == 200 and nav.headers["cache-control"] == "no-store"
        assert (await client.get(url + "execute", headers=headers)).status_code == 403
        prepared = await client.post(url + "prepare", headers=headers, json=nav.json())
        assert prepared.status_code == 200 and server.task_manager.calls == 0
        proof = {"confirmation": prepared.json()["confirmation"]}
        assert (await client.post(url + "execute", json=proof)).status_code == 401
        # A full account JWT is not the bound originating mobile device.
        assert (
            await client.post(
                url + "execute", headers={"Authorization": "Bearer " + account_token}, json=proof
            )
        ).status_code == 403
        await service.revoke(user_id=1, device_id=device["device_id"])
        assert (await client.post(url + "execute", headers=headers, json=proof)).status_code == 401
        assert server.task_manager.calls == 0


@pytest.mark.asyncio
async def test_device_middleware_errors_follow_account_locale_before_header(app_server, service):
    from octop.i18n.domains.errors import error_message

    app, _, owner, _ = app_server
    _, device = await paired(service, ["chat"])
    headers = {"Authorization": "Bearer " + device["access_token"], "Accept-Language": "en"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://octop.test"
    ) as client:
        for locale in ["zh", "en"]:
            owner.locale = locale
            response = await client.get("/api/models", headers=headers)
            assert response.status_code == 403
            assert response.json()["error"]["message"] == error_message("FORBIDDEN", locale)
