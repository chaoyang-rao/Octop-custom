"""Company MCP catalogue publication and credential-free member snapshots."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field

from octop.api.deps import current_user, get_server
from octop.infra.connectors.enterprise_catalog import (
    CatalogAdminState,
    CatalogEntry,
    CatalogMember,
    CatalogSnapshot,
    EnterpriseMcpCatalog,
)
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.users.identity import User
from octop.infra.utils.locale import resolve_request_locale


class _CatalogRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await original(request)
            except RequestValidationError:
                # Rejected extra fields may contain credentials; never echo them.
                error = OctopError.localized(ErrorCode.ENTERPRISE_MCP_CATALOG_INVALID)
                return JSONResponse(
                    status_code=error.status,
                    content=error.to_envelope(locale=resolve_request_locale(request)),
                )

        return handler


router = APIRouter(route_class=_CatalogRoute)


class CatalogExpectedVersion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    expected_etag: str = Field(
        pattern=r"^[0-9a-f]{64}$",
        description="Exact etag returned by the last administrator catalogue read.",
    )


class CatalogDraftUpdate(CatalogExpectedVersion):
    entries: list[CatalogEntry] = Field(
        max_length=1000, description="Credential-free HTTPS MCP definitions to save as a draft."
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
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> CatalogSnapshot:
    _no_store(response)
    return await asyncio.to_thread(EnterpriseMcpCatalog(server).snapshot_for, user)


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
