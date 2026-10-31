"""Actual HTTP contracts never return credentials or cross-account vault data."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from tests.unit.connectors.accounts.test_vault_service import Secrets, Settings

from octop.api.deps import current_user, get_server
from octop.api.routers.account_connections import router
from octop.infra.errors import OctopError
from octop.infra.users.identity import User
from octop.infra.utils.paths import PathLayout


def app_for(tmp_path):
    settings, secrets = Settings(), Secrets()
    server = SimpleNamespace(
        services=SimpleNamespace(
            settings_repo=settings, secret_repo=secrets, paths=PathLayout(tmp_path)
        )
    )
    app = FastAPI()
    app.include_router(router, prefix="/api")

    def user(request: Request):
        identifier = int(request.headers.get("X-Test-User", "1"))
        return User(
            id=identifier,
            username=f"user{identifier}",
            role="user",
            display_name=None,
            permissions=[] if identifier == 3 else ["connectors"],
        )

    app.dependency_overrides[current_user] = user
    app.dependency_overrides[get_server] = lambda: server

    @app.exception_handler(OctopError)
    async def domain_error(request, exc):
        return JSONResponse(status_code=exc.status, content={"code": exc.code.value})

    return app, settings


@pytest.mark.asyncio
async def test_http_credential_preview_is_redacted_and_owner_scoped(tmp_path):
    app, settings = app_for(tmp_path)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        created = await client.post(
            "/api/account-connections/vaults",
            json={
                "provider": "onepassword",
                "name": "owned",
                "allowed_hosts": ["api.example.com"],
                "service_account_token": "synthetic-private-token",
            },
        )
        assert created.status_code == 200
        connection = created.json()
        assert "synthetic-private-token" not in created.text
        assert "service_account_token" not in created.text
        assert "synthetic-private-token" not in str(settings.values)
        other = await client.get("/api/account-connections/vaults", headers={"X-Test-User": "2"})
        assert other.json() == []
        mutate = await client.delete(
            f"/api/account-connections/vaults/{connection['id']}", headers={"X-Test-User": "2"}
        )
        assert mutate.status_code == 404
        denied = await client.get("/api/account-connections/vaults", headers={"X-Test-User": "3"})
        assert denied.status_code == 403


@pytest.mark.asyncio
async def test_invalid_secret_body_does_not_echo_credential_or_input(tmp_path):
    app, _ = app_for(tmp_path)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        result = await client.post(
            "/api/account-connections/vaults",
            json={
                "provider": "invalid",
                "name": "test",
                "service_account_token": "synthetic-never-echo",
            },
        )
        assert result.status_code == 422
        assert "synthetic-never-echo" not in result.text
        assert "input" not in result.json()


@pytest.mark.asyncio
async def test_oauth_app_secret_is_never_read_back_and_other_user_has_no_client(tmp_path):
    app, settings = app_for(tmp_path)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        result = await client.put(
            "/api/account-connections/oauth-apps/slack",
            json={
                "client_id": "our-client",
                "client_secret": "synthetic-client-secret",
                "scopes": "search:read.public",
            },
        )
        assert result.status_code == 200 and result.json()["secret_configured"]
        assert "synthetic-client-secret" not in result.text
        assert "synthetic-client-secret" not in str(settings.values)
        read = await client.get("/api/account-connections/oauth-apps/slack")
        assert read.json()["client_id"] == "our-client"
        assert "synthetic-client-secret" not in read.text
        other = await client.get(
            "/api/account-connections/oauth-apps/slack", headers={"X-Test-User": "2"}
        )
        assert not other.json()["configured"]
        # A different Client ID must not silently inherit the previous app's secret.
        changed = await client.put(
            "/api/account-connections/oauth-apps/slack", json={"client_id": "different-client"}
        )
        assert changed.status_code == 200 and not changed.json()["secret_configured"]
