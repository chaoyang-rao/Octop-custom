"""HTTP adapters for company expert and Skill publication."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Response
from pydantic import Field

from octop.api.deps import current_user, get_server
from octop.api.routers.enterprise_mcp_admin import _CatalogRoute, _no_store
from octop.infra.connectors.enterprise_catalog import CatalogMember
from octop.infra.enterprise_resources.catalog import ResourceAdminState, ResourceCatalog
from octop.infra.enterprise_resources.models import (
    ResourceDefinition,
    ResourceSnapshot,
    StrictModel,
)
from octop.infra.errors import ErrorCode
from octop.infra.users.identity import User


class ResourceRoute(_CatalogRoute):
    validation_error = ErrorCode.ENTERPRISE_RESOURCE_INVALID


router = APIRouter(route_class=ResourceRoute)


class ExpectedVersion(StrictModel):
    expected_etag: str = Field(pattern=r"^[0-9a-f]{64}$", description="Current administrator etag.")


class EntryUpdate(ExpectedVersion):
    resource: ResourceDefinition


class EntryRemoval(ExpectedVersion):
    resource_id: str


class VersionRollback(ExpectedVersion):
    revision: int = Field(ge=1)


@router.get(
    "/enterprise/resources/admin/catalog",
    response_model=ResourceAdminState,
    summary="Read company expert and Skill drafts and history",
)
async def admin_catalog(
    response: Response, user: User = Depends(current_user), server: Any = Depends(get_server)
) -> ResourceAdminState:
    _no_store(response)
    return await asyncio.to_thread(ResourceCatalog(server).admin, user)


@router.put(
    "/enterprise/resources/admin/entry",
    response_model=ResourceAdminState,
    summary="Save a portable expert or Skill draft",
    description="Requires a company web administrator and current etag. Runtime credentials, chats, memory and local paths are excluded. Saving does not publish.",
)
async def save_entry(
    body: EntryUpdate,
    response: Response,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> ResourceAdminState:
    _no_store(response)
    return await asyncio.to_thread(
        ResourceCatalog(server).save_entry, user, body.resource, body.expected_etag
    )


@router.post(
    "/enterprise/resources/admin/remove",
    response_model=ResourceAdminState,
    summary="Remove a resource from the draft",
    description="Publishing the removal stops updates while retaining member-local copies and private data.",
)
async def remove_entry(
    body: EntryRemoval,
    response: Response,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> ResourceAdminState:
    _no_store(response)
    return await asyncio.to_thread(
        ResourceCatalog(server).remove_entry, user, body.resource_id, body.expected_etag
    )


@router.post(
    "/enterprise/resources/admin/publish",
    response_model=ResourceAdminState,
    summary="Publish expert and Skill versions",
    description="Creates an immutable revision. Members pull it and apply to independent copies when affected experts are idle; local conflicts require member review.",
)
async def publish(
    body: ExpectedVersion,
    response: Response,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> ResourceAdminState:
    _no_store(response)
    return await asyncio.to_thread(ResourceCatalog(server).publish, user, body.expected_etag)


@router.post(
    "/enterprise/resources/admin/rollback",
    response_model=ResourceAdminState,
    summary="Republish a prior expert and Skill version",
    description="Creates a new revision from history and preserves the current draft. Member conflict checks still apply.",
)
async def rollback(
    body: VersionRollback,
    response: Response,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> ResourceAdminState:
    _no_store(response)
    return await asyncio.to_thread(
        ResourceCatalog(server).rollback, user, body.revision, body.expected_etag
    )


@router.get(
    "/enterprise/resources/admin/members",
    response_model=list[CatalogMember],
    summary="List verified company members for resource visibility",
)
async def members(
    response: Response, user: User = Depends(current_user), server: Any = Depends(get_server)
) -> list[CatalogMember]:
    _no_store(response)
    return await asyncio.to_thread(ResourceCatalog(server).members, user)


@router.get(
    "/enterprise/resources/catalog",
    response_model=ResourceSnapshot,
    summary="Read eligible company expert and Skill versions",
)
async def member_catalog(
    response: Response, user: User = Depends(current_user), server: Any = Depends(get_server)
) -> ResourceSnapshot:
    _no_store(response)
    return await asyncio.to_thread(ResourceCatalog(server).member, user)


@router.get(
    "/enterprise/resources/bundles/{content_digest}",
    response_model=ResourceDefinition,
    summary="Download an authorized immutable resource bundle",
    description="Members can download only currently published enabled resources visible to them. Device grants cannot edit or publish.",
)
async def bundle(
    content_digest: str,
    response: Response,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> ResourceDefinition:
    _no_store(response)
    return await asyncio.to_thread(ResourceCatalog(server).bundle, user, content_digest)
