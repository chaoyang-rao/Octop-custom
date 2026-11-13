"""Member-local resource sync and explicit conflict resolution."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field

from octop.api.deps import current_user, get_server
from octop.api.routers.enterprise_mcp_admin import _no_store
from octop.api.routers.enterprise_resources_admin import ResourceRoute
from octop.infra.enterprise_resources.export import export_options, export_resource
from octop.infra.enterprise_resources.models import ResourceDefinition, StrictModel
from octop.infra.enterprise_resources.node import resources_for
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.users.identity import User
from octop.infra.users.permissions import user_has_permission

router = APIRouter(route_class=ResourceRoute)


class ResourceLocalState(BaseModel):
    resource_id: str
    kind: Literal["expert", "skill"]
    display_name: str
    enabled: bool
    digest: str | None
    target_id: str | None
    applied_digest: str | None
    status: str
    paused: bool
    local_modified: bool = False
    conflicts: list[str]
    error: str | None


class ResourceNodeState(BaseModel):
    enabled: bool
    revision: int
    last_synced_at: int | None
    error: str | None
    resources: list[ResourceLocalState]


class ResourceConflict(BaseModel):
    path: str
    base: str | None = Field(description="Base64 content, or null for an absent file.")
    local: str | None
    remote: str | None


class ResourceDetail(BaseModel):
    resource_id: str
    ticket: str
    local_files: dict[str, str]
    conflicts: list[ResourceConflict]


class ResourceResolution(StrictModel):
    ticket: str = Field(pattern=r"^[0-9a-f]{64}$")
    decisions: dict[str, Literal["local", "remote"]] = Field(max_length=600)


class ResourcePause(StrictModel):
    paused: bool


class ResourceExportOption(BaseModel):
    kind: Literal["expert", "skill"]
    id: str
    name: str
    slug: str


def _allowed(user: User) -> None:
    if not any(user_has_permission(user, key) for key in ("experts", "skills")):
        raise OctopError.localized(ErrorCode.FORBIDDEN)


@router.get(
    "/enterprise-resources",
    response_model=ResourceNodeState,
    summary="Read this member's local company resources",
)
async def status(
    response: Response, user: User = Depends(current_user), server: Any = Depends(get_server)
) -> dict[str, Any]:
    _allowed(user)
    _no_store(response)
    return await asyncio.to_thread(resources_for(server).status, user)


@router.post(
    "/enterprise-resources/sync",
    response_model=ResourceNodeState,
    summary="Pull company expert and Skill updates",
    description="Authenticates the member, validates immutable bundles, and applies when affected experts are idle. Local edits are merged or surfaced as conflicts.",
)
async def sync(
    response: Response, user: User = Depends(current_user), server: Any = Depends(get_server)
) -> dict[str, Any]:
    _allowed(user)
    _no_store(response)
    return await resources_for(server).sync(user)


@router.get(
    "/enterprise-resources/exports",
    response_model=list[ResourceExportOption],
    summary="List owned experts and Skills available for portable export",
)
async def exports(
    response: Response, user: User = Depends(current_user), server: Any = Depends(get_server)
) -> list[dict[str, str]]:
    _allowed(user)
    _no_store(response)
    return await asyncio.to_thread(export_options, server, user)


@router.get(
    "/enterprise-resources/export/{kind}/{target_id}",
    response_model=ResourceDefinition,
    summary="Export owned expert prompts or Skill content",
    description="Excludes chats, memory, USER.md, model credentials, CLI configuration and project paths. Review the content before publishing; arbitrary source text is not scanned for embedded secrets.",
)
async def export(
    kind: str,
    target_id: str,
    response: Response,
    slug: str = "",
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> ResourceDefinition:
    _allowed(user)
    _no_store(response)
    return await export_resource(server, user, kind, target_id, slug)


@router.get(
    "/enterprise-resources/{resource_id}",
    response_model=ResourceDetail,
    summary="Inspect local resource conflicts",
)
async def detail(
    resource_id: str,
    response: Response,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    _allowed(user)
    _no_store(response)
    return await resources_for(server).detail(user, resource_id)


@router.post(
    "/enterprise-resources/{resource_id}/resolve",
    response_model=ResourceNodeState,
    summary="Resolve observed local resource conflicts",
    description="Requires a fresh comparison ticket and one explicit decision per conflicting path. Changed local content or a newer publication rejects stale decisions.",
)
async def resolve(
    resource_id: str,
    body: ResourceResolution,
    response: Response,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    _allowed(user)
    _no_store(response)
    return await resources_for(server).resolve(user, resource_id, body.ticket, body.decisions)


@router.patch(
    "/enterprise-resources/{resource_id}",
    response_model=ResourceNodeState,
    summary="Pause or resume following a company resource",
)
async def pause(
    resource_id: str,
    body: ResourcePause,
    response: Response,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    _allowed(user)
    _no_store(response)
    return await resources_for(server).pause(user, resource_id, body.paused)
