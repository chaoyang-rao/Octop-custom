"""Encrypted, user-owned OAuth app registrations for MCP services without DCR."""

from __future__ import annotations

import base64
from typing import Any

from octop.infra.connectors.catalog import get_mcp_oauth_remote
from octop.infra.connectors.crypto import decrypt_credentials, encrypt_credentials


def _key(user_id: int, kind: str) -> str:
    if user_id <= 0 or get_mcp_oauth_remote(kind) is None:
        raise ValueError("unsupported OAuth application")
    return f"connector.oauth.client.{user_id}.{kind}"


def save_registered_oauth_client(
    *,
    settings_repo: Any,
    secret_repo: Any,
    user_id: int,
    kind: str,
    client_id: str,
    client_secret: str | None,
    scopes: str | None = None,
) -> None:
    identifier = client_id.strip()
    if not identifier or len(identifier) > 1024 or any(char in identifier for char in "\r\n"):
        raise ValueError("invalid OAuth client identifier")
    payload = {"client_id": identifier, "client_secret": client_secret or "", "scope": scopes or ""}
    blob = encrypt_credentials(secret_repo, payload)
    settings_repo.set(_key(user_id, kind), base64.b64encode(blob).decode("ascii"))


def load_registered_oauth_client(
    *,
    settings_repo: Any,
    secret_repo: Any,
    user_id: int,
    kind: str,
) -> dict[str, Any] | None:
    raw = settings_repo.get(_key(user_id, kind))
    if not raw:
        return None
    return decrypt_credentials(secret_repo, base64.b64decode(raw, validate=True))


def delete_registered_oauth_client(*, settings_repo: Any, user_id: int, kind: str) -> None:
    settings_repo.delete(_key(user_id, kind))


def registered_oauth_client_preview(client: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "configured": bool(client),
        "client_id": str(client.get("client_id") or "") if client else "",
        "secret_configured": bool(client and client.get("client_secret")),
        "scopes": str(client.get("scope") or "") if client else "",
    }
