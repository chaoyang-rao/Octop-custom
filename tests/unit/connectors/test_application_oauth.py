"""Preset OAuth follows the MCP resource's discovered authorization server."""

from unittest.mock import AsyncMock

import pytest

from octop.infra.connectors.oauth import registry


@pytest.mark.asyncio
async def test_preset_uses_discovered_issuer_for_start_exchange_and_refresh(monkeypatch):
    metadata = {
        "issuer": "https://auth.example.com",
        "authorization_endpoint": "https://auth.example.com/authorize",
        "token_endpoint": "https://auth.example.com/token",
        "registration_endpoint": "https://auth.example.com/register",
    }
    discover = AsyncMock(
        return_value={
            "available": True,
            "issuer": "https://auth.example.com",
            "resource": "https://resource.example.com/mcp",
            "metadata": metadata,
        }
    )
    monkeypatch.setattr(registry, "discover_oauth_from_mcp_url", discover)
    monkeypatch.setattr(
        registry, "register_dynamic_client", AsyncMock(return_value={"client_id": "ours"})
    )
    _, verifier, ctx = await registry.start_oauth(
        kind="linear",
        redirect_uri="http://127.0.0.1/callback",
        state="state",
        settings_repo=None,
    )
    assert ctx["issuer"] == "https://auth.example.com"
    assert ctx["resource"] == "https://resource.example.com/mcp"
    monkeypatch.setattr(registry, "load_oauth_ctx", lambda *_: ctx)
    exchange = AsyncMock(return_value={"access_token": "redacted"})
    monkeypatch.setattr(registry, "exchange_authorization_code", exchange)
    await registry.exchange_oauth_code(
        kind="linear",
        code="code",
        redirect_uri="http://127.0.0.1/callback",
        code_verifier=verifier,
        settings_repo=None,
        state_id="state",
    )
    assert exchange.call_args.kwargs["issuer"] == ctx["issuer"]
    fetch = AsyncMock(return_value=metadata)
    refresh = AsyncMock(return_value={"access_token": "rotated"})
    monkeypatch.setattr(registry, "fetch_authorization_metadata", fetch)
    monkeypatch.setattr(registry, "refresh_access_token", refresh)
    await registry.refresh_oauth_credentials(
        kind="linear",
        settings_repo=None,
        creds={
            "refresh_token": "private",
            "oauth_client_id": "ours",
            "oauth_issuer": ctx["issuer"],
            "oauth_resource": ctx["resource"],
        },
    )
    fetch.assert_awaited_once_with(ctx["issuer"])
    assert refresh.call_args.kwargs["resource"] == ctx["resource"]


@pytest.mark.asyncio
async def test_unregistered_provider_fails_before_registration(monkeypatch):
    monkeypatch.setattr(
        registry,
        "discover_oauth_from_mcp_url",
        AsyncMock(
            return_value={
                "available": False,
                "error": "client registration required",
            }
        ),
    )
    register = AsyncMock()
    monkeypatch.setattr(registry, "register_dynamic_client", register)
    with pytest.raises(ValueError, match="client registration required"):
        await registry.start_oauth(
            kind="canva",
            redirect_uri="http://127.0.0.1/callback",
            state="state",
            settings_repo=None,
        )
    register.assert_not_awaited()
