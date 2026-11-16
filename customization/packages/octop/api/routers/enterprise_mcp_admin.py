"""Company MCP catalogue publication and credential-free member snapshots."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field

from octop.api.deps import current_user, get_server
from octop.infra.connectors.enterprise_account_auth import BusinessAccountAuth
from octop.infra.connectors.enterprise_catalog import (
    CatalogAdminState,
    CatalogEntry,
    CatalogMember,
    CatalogSnapshot,
    EnterpriseMcpCatalog,
)
from octop.infra.connectors.enterprise_mcp_gateway import gateway_for
from octop.infra.connectors.enterprise_mcp_protocol import AuthMode
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.users.identity import User
from octop.infra.utils.locale import resolve_request_locale


class _CatalogRoute(APIRoute):
    validation_error = ErrorCode.ENTERPRISE_MCP_CATALOG_INVALID

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await original(request)
            except RequestValidationError:
                # Rejected extra fields may contain credentials; never echo them.
                error = OctopError.localized(self.validation_error)
                return JSONResponse(
                    status_code=error.status,
                    content=error.to_envelope(locale=resolve_request_locale(request)),
                )

        return handler


router = APIRouter(route_class=_CatalogRoute)


class GatewayTargets(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    entries: list[CatalogEntry] = Field(max_length=3)


class GatewayGrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    auth_mode: AuthMode = Field(
        description="No-extra-input company identity, an individual Bearer token, or an MCP Basic connection credential."
    )
    account_id: str = Field(default="", max_length=64)
    expected_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class GatewayGrantReply(BaseModel):
    auth_mode: AuthMode
    expires_at: str = Field(description="Unix expiry time of this member-and-service-scoped grant.")
    token: str | None = Field(
        default=None,
        repr=False,
        description="Private MCP Bearer grant, returned only to the authenticated member node.",
    )
    username: str | None = None
    password: str | None = Field(
        default=None,
        repr=False,
        description="Private MCP connection password; not the company sign-in password.",
    )


@router.put(
    "/enterprise/mcp/admin/gateway",
    summary="Configure fixed upstreams for the enterprise MCP gateway",
)
async def configure_gateway(
    body: GatewayTargets,
    response: Response,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, bool]:
    _no_store(response)
    await asyncio.to_thread(gateway_for(server).configure, user, body.entries)
    return {"ok": True}


@router.post(
    "/enterprise/mcp/grants/{entry_id}",
    response_model=GatewayGrantReply,
    response_model_exclude_none=True,
    summary="Exchange company identity for a member-scoped MCP credential",
    description="Requires an eligible company member. The credential is bound to one member, one MCP, one authorization mode and a finite expiry. It is returned only to the authenticated client, never in a directory snapshot.",
)
async def issue_gateway_grant(
    entry_id: str,
    body: GatewayGrantRequest,
    response: Response,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, str]:
    _no_store(response)
    return await gateway_for(server).issue(
        user, entry_id, body.auth_mode, body.account_id, body.expected_fingerprint
    )


@router.get(
    "/enterprise/mcp/gateway/{entry_id}",
    operation_id="enterprise_mcp_gateway_events",
    summary="Stream member-authorized MCP events",
)
@router.delete(
    "/enterprise/mcp/gateway/{entry_id}",
    operation_id="enterprise_mcp_gateway_close",
    summary="Close this member's authorized MCP session",
)
@router.post(
    "/enterprise/mcp/gateway/{entry_id}",
    operation_id="enterprise_mcp_gateway_request",
    summary="Proxy a member-authorized MCP session",
    description="Accepts scoped Bearer or Basic MCP grants. Enterprise no-input mode exchanges the logged-in identity for a grant automatically. Anonymous requests are denied and MCP sessions cannot be reused by another grant.",
)
async def enterprise_mcp_gateway(
    entry_id: str, request: Request, server: Any = Depends(get_server)
) -> Response:
    payload = bytearray()
    async for chunk in request.stream():
        payload.extend(chunk)
        if len(payload) > 1024 * 1024:
            raise OctopError.localized(ErrorCode.ENTERPRISE_MCP_CATALOG_INVALID)
    try:
        reply = await gateway_for(server).forward(
            entry_id, request.method, dict(request.headers), bytes(payload)
        )
    except OctopError as exc:
        if exc.code == ErrorCode.ENTERPRISE_ACCESS_DENIED:
            return JSONResponse(
                status_code=401,
                content=exc.to_envelope(locale=resolve_request_locale(request)),
                headers={
                    "WWW-Authenticate": 'Bearer realm="enterprise-mcp"',
                    "Cache-Control": "no-store",
                },
            )
        raise
    return StreamingResponse(reply.body, status_code=reply.status, headers=reply.headers)


class AccountChoice(BaseModel):
    account_id: str
    label: str


class AccountChoices(BaseModel):
    identity_name: str
    accounts: list[AccountChoice]


class AccountSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: str = Field(min_length=1, max_length=64)
    expected_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


@router.get("/enterprise/mcp/accounts/{entry_id}", response_model=AccountChoices)
async def mcp_account_choices(
    entry_id: str,
    response: Response,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    _no_store(response)
    return await BusinessAccountAuth(server).choices(user, entry_id)


@router.post("/enterprise/mcp/accounts/{entry_id}")
async def mcp_account_grant(
    entry_id: str,
    body: AccountSelection,
    response: Response,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    """Issue this member's MCP-only grant after an explicit account choice.

    Credentials travel directly to the member node, never through the picker.
    """
    _no_store(response)
    return await BusinessAccountAuth(server).issue(
        user, entry_id, body.account_id, body.expected_fingerprint
    )


class CatalogExpectedVersion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    expected_etag: str = Field(
        pattern=r"^[0-9a-f]{64}$",
        description="Exact etag returned by the last administrator catalogue read.",
    )


class CatalogDraftUpdate(CatalogExpectedVersion):
    entries: list[CatalogEntry] = Field(
        max_length=1000, description="Credential-free HTTP(S) MCP definitions to save as a draft."
    )


class CatalogRollback(CatalogExpectedVersion):
    revision: int = Field(
        ge=1, description="Published revision whose definitions should be republished."
    )


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


@router.get(
    "/enterprise/mcp/catalog",
    response_model=CatalogSnapshot,
    summary="Read the eligible company MCP catalogue",
    description="Company employees and enterprise device grants receive their visible, credential-free definitions. Disabled entries remain visible as disabled.",
)
async def member_catalog(
    response: Response,
    protocols: str = Header(
        default="https",
        alias="X-Octop-MCP-Protocols",
        description="Supported MCP URL schemes. Legacy clients receive HTTPS entries only.",
    ),
    gateway: str = Header(default="", alias="X-Octop-MCP-Gateway"),
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> CatalogSnapshot:
    _no_store(response)
    from octop.infra.enterprise_resources.member_access import access_for

    if gateway != "1" and await asyncio.to_thread(lambda: access_for(server).configured):
        raise OctopError.localized(ErrorCode.ENTERPRISE_CLIENT_UPGRADE_REQUIRED)
    return await asyncio.to_thread(
        EnterpriseMcpCatalog(server).snapshot_for,
        user,
        include_http="http" in {part.strip().lower() for part in protocols.split(",")},
        include_gateway=gateway == "1",
    )


@router.get(
    "/enterprise/mcp/admin/catalog",
    response_model=CatalogAdminState,
    summary="Read company MCP draft and publication history",
    description="Requires a company administrator login. Enterprise device credentials cannot administer the catalogue.",
)
async def administrator_catalog(
    response: Response,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> CatalogAdminState:
    _no_store(response)
    return await asyncio.to_thread(EnterpriseMcpCatalog(server).get_admin, user)


@router.put(
    "/enterprise/mcp/admin/draft",
    response_model=CatalogAdminState,
    summary="Save a company MCP draft",
    description="Requires a company administrator and the current etag; stale concurrent changes return 409. Personal credentials and executable commands are rejected.",
)
async def save_catalog_draft(
    body: CatalogDraftUpdate,
    response: Response,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> CatalogAdminState:
    _no_store(response)
    return await asyncio.to_thread(
        EnterpriseMcpCatalog(server).save_draft, user, body.entries, body.expected_etag
    )


@router.get(
    "/enterprise/mcp/admin/members",
    response_model=list[CatalogMember],
    summary="List verified company members for catalogue visibility",
    description="Company administrators receive only stable enterprise subjects and display names. Disabled and unverified accounts are excluded.",
)
async def catalogue_members(
    response: Response,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> list[CatalogMember]:
    _no_store(response)
    return await asyncio.to_thread(EnterpriseMcpCatalog(server).members, user)


@router.post(
    "/enterprise/mcp/admin/publish",
    response_model=CatalogAdminState,
    summary="Publish the current company MCP draft",
    description="Creates an immutable, monotonically increasing revision. Draft publication does not send commands or credentials to member machines.",
)
async def publish_catalog(
    body: CatalogExpectedVersion,
    response: Response,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> CatalogAdminState:
    _no_store(response)
    return await asyncio.to_thread(EnterpriseMcpCatalog(server).publish, user, body.expected_etag)


@router.post(
    "/enterprise/mcp/admin/rollback",
    response_model=CatalogAdminState,
    summary="Republish a prior company MCP revision",
    description="Publishes the selected history as a new revision without deleting history or replacing the unpublished draft.",
)
async def rollback_catalog(
    body: CatalogRollback,
    response: Response,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> CatalogAdminState:
    _no_store(response)
    return await asyncio.to_thread(
        EnterpriseMcpCatalog(server).rollback, user, body.revision, body.expected_etag
    )
