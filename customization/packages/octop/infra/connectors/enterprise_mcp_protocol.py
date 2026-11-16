"""Shared wire contract for enterprise-authenticated MCP connections."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from octop.infra.connectors.enterprise_catalog import CatalogEntry

AuthMode = Literal["none", "bearer", "basic"]
GATEWAY_PATH = "/api/enterprise/mcp/gateway/"


def gateway_url(authority: str, entry_id: str) -> str:
    return authority.rstrip("/") + GATEWAY_PATH + entry_id


def is_gateway_entry(entry: CatalogEntry, authority: str) -> bool:
    return bool(authority) and entry.url == gateway_url(authority, entry.entry_id)
