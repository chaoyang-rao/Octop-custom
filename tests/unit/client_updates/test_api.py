"""Update reservations cover HTTP saves and WebSocket task admission."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from octop.api.deps import current_user, get_server, resolve_websocket_user
from octop.api.middleware import jwt_auth
from octop.api.routers.client_updates import center_router, router
from octop.infra.errors import OctopError
from tests.unit.client_updates.test_protocol import company as company


async def test_admin_http_surface_is_typed_and_contains_no_signing_secret(company):
    catalog, user, _ = company
    app = FastAPI()
    app.include_router(center_router, prefix="/api")
    app.include_router(router, prefix="/api")
    app.dependency_overrides[current_user] = lambda: user
    app.dependency_overrides[get_server] = lambda: catalog.server
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        result = await client.get("/api/enterprise/client-updates/admin")
        assert result.status_code == 200
        assert result.json()["signing_configured"]
        assert not any(word in result.text for word in ["private", "signature", "token"])
        bootstrap = await client.get("/api/client-updates/bootstrap")
        assert bootstrap.headers["cache-control"] == "no-store"
        assert "localStorage.clear" not in bootstrap.text
        assert "sessionStorage.clear" not in bootstrap.text
        assert app.openapi()["paths"]["/api/enterprise/client-updates/admin"]["get"]["responses"][
            "200"
        ]["content"]["application/json"]["schema"]["$ref"].endswith("AdminState")


async def test_update_approved_during_remote_authorization_rejects_late_save(company, monkeypatch):
    catalog, user, _ = company
    server = catalog.server
    registry = SimpleNamespace(application_update_pending=False)
    server.app_runtime = SimpleNamespace(agent_registry=registry)
    entered = asyncio.Event()
    proceed = asyncio.Event()

    async def authorize(_):
        entered.set()
        await proceed.wait()
        return user

    monkeypatch.setattr(jwt_auth, "client_for", lambda _: SimpleNamespace(authorize=authorize))
    monkeypatch.setattr(jwt_auth, "authenticate_request", lambda request, server: user)
    app = FastAPI()
    jwt_auth.install(app, server)
    saved = []

    @app.post("/api/save")
    async def save():
        saved.append(True)
        return {"ok": True}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        pending = asyncio.create_task(client.post("/api/save"))
        await entered.wait()
        registry.application_update_pending = True
        proceed.set()
        result = await pending
        assert result.status_code == 503
        assert result.json()["error"]["code"] == "CLIENT_UPDATE_IN_PROGRESS"
        assert not saved


async def test_reserved_upgrade_rejects_new_websocket_task(company, monkeypatch):
    catalog, user, _ = company
    server = catalog.server
    server.app_runtime = SimpleNamespace(
        agent_registry=SimpleNamespace(application_update_pending=True)
    )
    monkeypatch.setattr("octop.api.deps.resolve_user_from_token", lambda *args: user)
    monkeypatch.setattr(
        "octop.infra.auth.enterprise.client_for",
        lambda _: SimpleNamespace(authorize=AsyncMock(return_value=user)),
    )
    with pytest.raises(OctopError) as error:
        await resolve_websocket_user(server, "test-credential")
    assert error.value.code.value == "CLIENT_UPDATE_IN_PROGRESS"
