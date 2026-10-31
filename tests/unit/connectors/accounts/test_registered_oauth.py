"""User-owned OAuth app registration without borrowing another client's identity."""

from __future__ import annotations

from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import pytest
from tests.unit.connectors.accounts.test_vault_service import Secrets, Settings

from octop.infra.connectors.accounts.oauth_clients import (
    load_registered_oauth_client,
    registered_oauth_client_preview,
    save_registered_oauth_client,
)
from octop.infra.connectors.oauth import registry


def test_registration_is_encrypted_per_user_and_redacted():
    settings, secrets = Settings(), Secrets()
    save_registered_oauth_client(
        settings_repo=settings,
        secret_repo=secrets,
        user_id=1,
        kind="slack",
        client_id="our-client",
        client_secret="fake-private-client-secret",
        scopes="search:read.public",
    )
    assert "fake-private-client-secret" not in str(settings.values)
    client = load_registered_oauth_client(
        settings_repo=settings, secret_repo=secrets, user_id=1, kind="slack"
    )
    assert client["client_secret"] == "fake-private-client-secret"
    assert (
        load_registered_oauth_client(
            settings_repo=settings, secret_repo=secrets, user_id=2, kind="slack"
        )
        is None
    )
    preview = registered_oauth_client_preview(client)
    assert preview["client_id"] == "our-client" and preview["secret_configured"]
    assert "fake-private-client-secret" not in str(preview)


def test_oauth_context_encrypted_and_legacy_readable():
    settings, secrets = Settings(), Secrets()
    registry.save_oauth_ctx(
        settings,
        "state",
        {"client_secret": "private-test", "issuer": "https://example.com"},
        secret_repo=secrets,
    )
    assert "private-test" not in str(settings.values)
    with pytest.raises(ValueError):
        registry.load_oauth_ctx(settings, "state")
    assert (
        registry.load_oauth_ctx(settings, "state", secret_repo=secrets)["client_secret"]
        == "private-test"
    )
    registry.save_oauth_ctx(settings, "legacy", {"flow": "mcp"})
    assert registry.load_oauth_ctx(settings, "legacy", secret_repo=secrets) == {"flow": "mcp"}


@pytest.mark.asyncio
async def test_registered_client_supports_metadata_without_dynamic_registration(monkeypatch):
    metadata = {
        "authorization_endpoint": "https://slack.com/oauth/v2_user/authorize",
        "token_endpoint": "https://slack.com/api/oauth.v2.user.access",
    }
    discover = AsyncMock(
        return_value={
            "available": False,
            "issuer": "https://mcp.slack.com",
            "resource": "https://mcp.slack.com",
            "metadata": metadata,
            "registration_required": True,
        }
    )
    register = AsyncMock()
    monkeypatch.setattr(registry, "discover_oauth_from_mcp_url", discover)
    monkeypatch.setattr(registry, "register_dynamic_client", register)
    url, verifier, context = await registry.start_oauth_for_target(
        target={"type": "catalog", "kind": "slack"},
        redirect_uri="http://127.0.0.1/api/connectors/oauth/callback",
        state="state",
        settings_repo=None,
        registered_client={
            "client_id": "our-client",
            "client_secret": "our-private-test",
            "scope": "search:read.public",
        },
    )
    query = parse_qs(urlsplit(url).query)
    assert query["client_id"] == ["our-client"]
    assert query["scope"] == ["search:read.public"]
    assert query["code_challenge_method"] == ["S256"] and verifier
    assert "our-private-test" not in url
    assert context["client_secret"] == "our-private-test"
    register.assert_not_awaited()
