"""Local company MCP synchronization status and member-owned authorization."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from octop.api.deps import current_user, get_server
from octop.infra.connectors.enterprise_catalog import CatalogEntry
from octop.infra.connectors.enterprise_mcp_sync import sync_for
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.users.identity import User
from octop.infra.users.permissions import user_has_permission
from octop.infra.utils.locale import resolve_request_locale


class _CredentialRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await original(request)
            except RequestValidationError:
                error = OctopError.localized(ErrorCode.CONNECTOR_INVALID_CREDENTIALS)
                return JSONResponse(
                    status_code=error.status,
                    content=error.to_envelope(locale=resolve_request_locale(request)),
                )

        return handler


router = APIRouter(route_class=_CredentialRoute)


class EnterpriseMcpEntryState(CatalogEntry):
    server_name: str
    fingerprint: str
    authorized: bool
    local_disabled: bool
    needs_reauthorization: bool
    configuration_error: str | None = None


class EnterpriseMcpNodeState(BaseModel):
    enabled: bool
    authority_url: str | None
    revision: int
    last_synced_at: int | None
    sync_error: str | None
    pending_apply: bool
    entries: list[EnterpriseMcpEntryState]


class EnterpriseMcpCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    expected_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    token: SecretStr | None = Field(default=None, max_length=16384, repr=False)
    username: SecretStr | None = Field(default=None, max_length=4096, repr=False)
    password: SecretStr | None = Field(default=None, max_length=12288, repr=False)


def _member(user: User, response: Response) -> None:
    if not user_has_permission(user, "connector_enabled"):
        raise OctopError.localized(ErrorCode.FORBIDDEN, user.locale)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


@router.get(
    "/connectors/enterprise-mcp",
    response_model=EnterpriseMcpNodeState,
    summary="Read the local company MCP synchronization status",
    description="Returns cached definitions and authorization flags, never member credentials. Requires permission to use enabled connectors.",
)
async def company_mcp_status(
    response: Response,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    _member(user, response)
    return await asyncio.to_thread(sync_for(server).status, user)


@router.post(
    "/connectors/enterprise-mcp/sync",
    response_model=EnterpriseMcpNodeState,
    summary="Synchronize the current member's company MCP definitions",
    description="Reads a credential-free company snapshot. Busy experts retain their active configuration until a safe application boundary.",
)
async def synchronize_company_mcp(
    response: Response,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    _member(user, response)
    return await sync_for(server).sync(user)


@router.put(
    "/connectors/enterprise-mcp/entries/{entry_id}/credentials",
    response_model=EnterpriseMcpNodeState,
    summary="Validate and store this member's company MCP authorization",
    description="Probes initialization and tool listing, then encrypts credentials locally. The directory center never receives them.",
)
async def authorize_company_mcp(
    entry_id: str,
    body: EnterpriseMcpCredentials,
    response: Response,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    _member(user, response)
    credentials = {
        key: value.get_secret_value()
        for key in ("token", "username", "password")
        if (value := getattr(body, key)) is not None
    }
    return await sync_for(server).save_credentials(
        user, entry_id, credentials, body.expected_fingerprint
    )


@router.delete(
    "/connectors/enterprise-mcp/entries/{entry_id}/credentials",
    response_model=EnterpriseMcpNodeState,
    summary="Disconnect this member's company MCP authorization",
    description="Removes only the current member's local credentials. Subsequent managed tool calls are denied even if an expert still holds an older cached tool.",
)
async def disconnect_company_mcp(
    entry_id: str,
    response: Response,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    _member(user, response)
    return await sync_for(server).revoke_credentials(user, entry_id)
