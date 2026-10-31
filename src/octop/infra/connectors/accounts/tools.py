"""Agent tools expose metadata and requests, never approval tokens or secrets."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from langgraph.config import get_config
from pydantic import BaseModel, Field

from octop.i18n import tr
from octop.infra.connectors.accounts.actor import current_vault_actor
from octop.infra.connectors.accounts.service import AccountConnectionError, AccountConnectionService


class _NoArguments(BaseModel):
    pass


class _Items(BaseModel):
    connection_id: str
    offset: int = Field(default=0, ge=0, le=100000)
    search: str = Field(default="", max_length=200)


class _Reference(BaseModel):
    connection_id: str
    item_id: str
    vault_id: str = ""
    field_name: str = "password"
    label: str = ""


class _Use(BaseModel):
    reference: str
    url: str
    purpose: str
    method: str = "GET"
    header_name: str = "Authorization"
    prefix: str = "Bearer "
    body: dict[str, Any] | None = None


class _Status(BaseModel):
    request_id: str = Field(min_length=1, max_length=100)


def build_account_tools(
    service: AccountConnectionService, *, user_id: int, user_repo: Any | None = None
) -> list[Any]:
    """The acting user is bound by Octop, never accepted from model arguments."""
    from langchain_core.tools import StructuredTool

    async def connections() -> Any:
        rows = await service.list_connections(user_id)
        return [{key: row[key] for key in ("id", "provider", "name", "ready")} for row in rows]

    async def items(connection_id: str, offset: int = 0, search: str = "") -> Any:
        return await service.list_items(user_id, connection_id, offset=offset, search=search)

    async def references() -> Any:
        return await service.list_references(user_id)

    async def reference(**kwargs: Any) -> Any:
        return await service.create_reference(user_id, **kwargs)

    async def request(**kwargs: Any) -> Any:
        return await service.request_use(user_id, **kwargs)

    async def status(request_id: str) -> Any:
        for value in await service.list_requests(user_id):
            if value["request_id"] == request_id:
                return {
                    key: value[key]
                    for key in ("request_id", "state", "status_code", "expires_at")
                    if key in value
                }
        raise AccountConnectionError("not_found", locale=service.locale, status=404)

    def protected(function: Any) -> Any:
        async def invoke(**kwargs: Any) -> str:
            try:
                scoped, actor = current_vault_actor()
                if not scoped:
                    try:
                        config = get_config()
                        actor = (config.get("configurable") or {}).get(
                            "octop_authenticated_user_id"
                        )
                    except RuntimeError:
                        actor = None
                if (
                    isinstance(actor, bool)
                    or not isinstance(actor, int)
                    or actor != user_id
                    or user_repo is None
                ):
                    raise AccountConnectionError("access_denied", locale=service.locale, status=403)
                row = await asyncio.to_thread(user_repo.get, user_id)
                if (
                    row is None
                    or row.disabled
                    or (row.role != "admin" and "connectors" not in row.permissions)
                ):
                    raise AccountConnectionError("access_denied", locale=service.locale, status=403)
                result = await function(**kwargs)
                return json.dumps(result, ensure_ascii=False)
            except AccountConnectionError as exc:
                return json.dumps({"error": exc.code, "message": str(exc)}, ensure_ascii=False)

        return invoke

    definitions: list[tuple[str, Any, type[BaseModel]]] = [
        ("vault_connections", connections, _NoArguments),
        ("vault_list_items", items, _Items),
        ("vault_references", references, _NoArguments),
        ("vault_create_reference", reference, _Reference),
        ("vault_request_use", request, _Use),
        ("vault_use_status", status, _Status),
    ]
    return [
        StructuredTool.from_function(
            name=name,
            coroutine=protected(function),
            args_schema=model,
            description=tr(f"accountConnections.tools.{name}", service.locale),
        )
        for name, function, model in definitions
    ]
