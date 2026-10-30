"""Public-vendor MCP presets use independent, validated connection metadata."""

from __future__ import annotations

import sys

import pytest

from octop.config import OctopConfig
from octop.infra.connectors.builder import build_http_mcp_spec, validate_create_credentials
from octop.infra.connectors.catalog import get_catalog_entry, list_catalog
from octop.infra.errors import OctopError


@pytest.mark.parametrize(
    "kind",
    [
        "github",
        "linear",
        "canva",
        "cloudflare",
        "neon",
        "netlify",
        "prisma",
        "railway",
        "resend",
        "sentry",
        "stripe",
        "supabase",
        "todoist",
        "trello",
        "vercel",
        "airtable",
        "aave",
        "cobrain",
        "huggingface",
    ],
)
def test_vendor_presets_build_real_http_connections(kind):
    entry = get_catalog_entry(kind)
    assert entry is not None and entry.mcp_config
    creds = {"token": "private-token", "access_token": "private-token"}
    spec = build_http_mcp_spec(entry=entry, instance_id="owned", creds=creds, config=OctopConfig())
    assert spec["transport"] == "http" and spec["url"].startswith("https://")
    assert "private-token" not in spec["url"]
    if kind in {"github", "linear", "stripe", "resend"}:
        assert spec["headers"]["Authorization"] == "Bearer private-token"


def test_stdio_secret_is_in_environment_not_process_arguments():
    entry = get_catalog_entry("brave-search")
    assert entry is not None
    creds = validate_create_credentials("brave-search", {"api_key": "private-key"})
    spec = build_http_mcp_spec(entry=entry, instance_id="owned", creds=creds, config=OctopConfig())
    assert spec["command"] == "npx"
    assert spec["env"] == {"BRAVE_API_KEY": "private-key"}
    assert all("private-key" not in arg for arg in spec["args"])
    with pytest.raises(ValueError):
        validate_create_credentials("brave-search", {})


def test_optional_public_key_is_not_an_empty_authorization_header():
    entry = get_catalog_entry("context7")
    assert entry is not None
    assert validate_create_credentials("context7", {}) == {}
    spec = build_http_mcp_spec(entry=entry, instance_id="owned", creds={}, config=OctopConfig())
    assert "CONTEXT7_API_KEY" not in spec["headers"]


def test_user_endpoint_is_validated_and_credentials_do_not_enter_url():
    entry = get_catalog_entry("composio")
    assert entry is not None
    creds = validate_create_credentials(
        "composio", {"mcp_url": "https://example.com/mcp", "api_key": "private-key"}
    )
    spec = build_http_mcp_spec(entry=entry, instance_id="owned", creds=creds, config=OctopConfig())
    assert spec["url"] == "https://example.com/mcp"
    assert spec["headers"]["x-consumer-api-key"] == "private-key"
    for value in ["file:///tmp/secret", "https://example.com/mcp\nX-Fake: injected"]:
        with pytest.raises((ValueError, OctopError)):
            validate_create_credentials("composio", {"mcp_url": value, "api_key": "private"})


def test_incompatible_host_is_rejected_before_starting_local_process(monkeypatch):
    entry = get_catalog_entry("apple-apps")
    assert entry is not None
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(ValueError):
        build_http_mcp_spec(entry=entry, instance_id="owned", creds={}, config=OctopConfig())


def test_all_new_catalog_connections_have_documented_auth_and_no_static_secrets():
    for entry in list_catalog():
        if entry.mcp_config is None:
            continue
        assert entry.doc_url.startswith("https://")
        for template in entry.mcp_config.get("headers", {}).values():
            assert "{" in template
        if entry.mcp_mode == "stdio":
            assert entry.mcp_config.get("command")
