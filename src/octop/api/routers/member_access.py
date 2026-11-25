"""Super-administrator access to catalog MCPs and the desktop pet."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import Field

from octop.api.deps import current_user, get_server
from octop.api.routers.enterprise_mcp_admin import _CatalogRoute, _no_store
from octop.infra.enterprise_resources.member_access import MemberSelection, access_for
from octop.infra.enterprise_resources.models import StrictModel
from octop.infra.errors import ErrorCode
from octop.infra.users.identity import User


class AccessRoute(_CatalogRoute):
    validation_error = ErrorCode.ENTERPRISE_ACCESS_POLICY_INVALID


router = APIRouter(route_class=AccessRoute)


class MemberRow(MemberSelection):
    username: str
    display_name: str
    disabled: bool
    verified: bool


class ServiceState(StrictModel):
    entry_id: str
    configured: bool
    owner_name: str | None = None


class McpOption(StrictModel):
    entry_id: str
    display_name: str
    enabled: bool


class AccessAdminState(StrictModel):
    etag: str
    configured: bool
    revision: int
    members: list[MemberRow]
    services: list[ServiceState]
    mcp_options: list[McpOption]


class AccessUpdate(StrictModel):
    expected_etag: str = Field(pattern=r"^[0-9a-f]{64}$")
    members: list[MemberSelection] = Field(max_length=10000)


class ServiceUpdate(StrictModel):
    expected_etag: str = Field(pattern=r"^[0-9a-f]{64}$")
    account_id: str = Field(min_length=1, max_length=64)


@router.get(
    "/enterprise/access/admin",
    response_model=AccessAdminState,
    summary="List logged-in members and centrally enabled MCP/pet access",
)
async def members(
    response: Response, user: User = Depends(current_user), server: Any = Depends(get_server)
) -> Any:
    _no_store(response)
    return await asyncio.to_thread(access_for(server).admin, user)


@router.put(
    "/enterprise/access/admin",
    response_model=AccessAdminState,
    summary="Enable or revoke member access to company MCPs and the desktop pet",
    description="Super-administrators only. New members are denied by default. Every MCP call and new companion turn rechecks server authorization; local chats and files are retained.",
)
async def save(
    body: AccessUpdate,
    response: Response,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    _no_store(response)
    return await asyncio.to_thread(access_for(server).save, user, body.members, body.expected_etag)


@router.get(
    "/enterprise/access/admin/services/{entry_id}/accounts",
    summary="Read this super-administrator's verified read-only service connection choices",
)
async def choices(
    entry_id: Literal["aftersales-quality", "quota-workbench"],
    response: Response,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    _no_store(response)
    return await access_for(server).connection_choices(user, entry_id)


@router.put(
    "/enterprise/access/admin/services/{entry_id}",
    response_model=AccessAdminState,
    summary="Configure a server-owned read-only MCP connection",
    description="Credentials remain encrypted at the authority. Member access is granted separately in the member list; business credentials are never distributed to clients.",
)
async def connect(
    entry_id: Literal["aftersales-quality", "quota-workbench"],
    body: ServiceUpdate,
    response: Response,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    _no_store(response)
    return await access_for(server).connect_service(
        user, entry_id, body.account_id, body.expected_etag
    )
