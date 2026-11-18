"""Typed publication and member-local update HTTP adapters."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from octop.api.deps import current_user, extract_raw_token, get_server
from octop.api.routers.enterprise_mcp_admin import _CatalogRoute, _no_store
from octop.infra.client_updates.catalog import ClientUpdateCatalog
from octop.infra.client_updates.models import (
    ClientPackage,
    ClientRelease,
    DeviceReport,
    Phase,
    Platform,
    SignedRelease,
)
from octop.infra.client_updates.node import updates_for
from octop.infra.enterprise_resources.models import StrictModel
from octop.infra.errors import ErrorCode
from octop.infra.users.identity import User


class ClientUpdateRoute(_CatalogRoute):
    validation_error = ErrorCode.CLIENT_UPDATE_INVALID


center_router = APIRouter(route_class=ClientUpdateRoute)
router = APIRouter(route_class=ClientUpdateRoute)


@router.get(
    "/client-updates/bootstrap",
    response_class=HTMLResponse,
    summary="Load fresh desktop UI assets while retaining sign-in and drafts",
)
async def bootstrap() -> HTMLResponse:
    # /api/ is excluded from the PWA navigation fallback, so even an old cached
    # desktop shell can reach this page. Only program caches are invalidated.
    return HTMLResponse(
        """<!doctype html><meta charset="utf-8"><title>Octop</title><p>Loading Octop…</p>
<script>(async()=>{try{
 for(const registration of await navigator.serviceWorker.getRegistrations()) await registration.unregister();
 for(const key of await caches.keys()) if(key.startsWith('workbox-precache')||key.startsWith('workbox-runtime')||key.startsWith('octop-static')) await caches.delete(key);
}catch(_){} sessionStorage.setItem('octop:desktop-session','1');location.replace('/');})();</script>""",
        headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": "default-src 'none'; script-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'",
        },
    )


class ReleaseOption(BaseModel):
    tag: str
    version: str
    source_commit: str
    notes: str


class DraftRelease(ReleaseOption):
    packages: list[ClientPackage]


class PublishedRelease(BaseModel):
    release: ClientRelease
    envelope: SignedRelease


class ReleaseHistory(BaseModel):
    release: ClientRelease
    published_by: str


class ClientDeviceReport(DeviceReport):
    device_id: str
    user_id: int
    display_name: str
    last_seen_at: int


class AdminState(BaseModel):
    etag: str
    revision: int
    signing_configured: bool
    draft: DraftRelease | None
    published: PublishedRelease | None
    history: list[ReleaseHistory]
    devices: list[ClientDeviceReport]


class VersionCheck(StrictModel):
    expected_etag: str = Field(pattern=r"^[0-9a-f]{64}$")


class ImportRelease(VersionCheck):
    tag: str = Field(
        pattern=r"^custom-[A-Za-z0-9.-]{1,90}$",
        description="Existing release in the configured custom repository.",
    )


class PublishRelease(VersionCheck):
    allowed_subjects: list[str] = Field(
        default_factory=list,
        max_length=10000,
        description="Verified company subject fingerprints; empty publishes to all members.",
    )


class MemberCatalog(BaseModel):
    revision: int
    envelope: SignedRelease | None


class UpdateJob(BaseModel):
    id: str
    phase: Phase
    downloaded_bytes: int
    total_bytes: int
    error_code: str | None
    target_version: str


class NodeStatus(BaseModel):
    supported: bool
    platform: Platform | None
    current_version: str | None
    revision: int
    available: bool
    version: str | None
    notes: str
    last_check: int | None
    busy: bool
    job: UpdateJob | None
    error_code: str | None


class ReadyTicket(BaseModel):
    job_id: str = Field(
        pattern=r"^[0-9a-f]{32}$",
        description="Opaque, short-lived native handoff; never a URL or shell command.",
    )


@center_router.get(
    "/enterprise/client-updates/admin",
    response_model=AdminState,
    summary="Read company client releases and device update status",
)
async def admin(
    response: Response, user: User = Depends(current_user), server: Any = Depends(get_server)
) -> Any:
    _no_store(response)
    return await asyncio.to_thread(ClientUpdateCatalog(server).admin, user)


@center_router.get(
    "/enterprise/client-updates/admin/releases",
    response_model=list[ReleaseOption],
    summary="Find complete releases in the custom GitHub repository",
)
async def releases(
    response: Response, user: User = Depends(current_user), server: Any = Depends(get_server)
) -> Any:
    _no_store(response)
    return await ClientUpdateCatalog(server).releases(user)


@center_router.post(
    "/enterprise/client-updates/admin/import",
    response_model=AdminState,
    summary="Import a verified repository release as a draft",
    description="No arbitrary package URLs or commands are accepted. All three platform assets and their SHA-256 digests must be present; importing does not publish.",
)
async def import_release(
    body: ImportRelease,
    response: Response,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    _no_store(response)
    return await ClientUpdateCatalog(server).import_release(user, body.tag, body.expected_etag)


@center_router.post(
    "/enterprise/client-updates/admin/publish",
    response_model=AdminState,
    summary="Sign and publish a company client version",
    description="Only a verified company web administrator can publish. Device credentials cannot publish. Existing version bytes cannot be replaced.",
)
async def publish(
    body: PublishRelease,
    response: Response,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    _no_store(response)
    return await asyncio.to_thread(
        ClientUpdateCatalog(server).publish, user, body.expected_etag, body.allowed_subjects
    )


@center_router.post(
    "/enterprise/client-updates/admin/withdraw",
    response_model=AdminState,
    summary="Withdraw an update without downgrading or deleting member data",
)
async def withdraw(
    body: VersionCheck,
    response: Response,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    _no_store(response)
    return await asyncio.to_thread(ClientUpdateCatalog(server).withdraw, user, body.expected_etag)


@center_router.get(
    "/enterprise/client-updates/catalog",
    response_model=MemberCatalog,
    summary="Read the authenticated member's signed client release",
)
async def catalog(
    response: Response, user: User = Depends(current_user), server: Any = Depends(get_server)
) -> Any:
    _no_store(response)
    return await asyncio.to_thread(ClientUpdateCatalog(server).member, user)


@center_router.post(
    "/enterprise/client-updates/report",
    summary="Report this authenticated device's update progress",
    description="The owner and device id come from the purpose-limited device credential. Reports never contain credentials, chats, filenames or local paths.",
)
async def report(
    body: DeviceReport,
    request: Request,
    response: Response,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, bool]:
    _no_store(response)
    token = extract_raw_token(authorization=request.headers.get("authorization")) or ""
    return await asyncio.to_thread(ClientUpdateCatalog(server).report, user, token, body)


@router.get(
    "/client-updates/status",
    response_model=NodeStatus,
    summary="Read this member's local client update state",
)
async def node_status(
    response: Response, user: User = Depends(current_user), server: Any = Depends(get_server)
) -> Any:
    _no_store(response)
    return await updates_for(server).status(user)


@router.post(
    "/client-updates/check",
    response_model=NodeStatus,
    summary="Refresh the signed company client release",
)
async def node_check(
    response: Response, user: User = Depends(current_user), server: Any = Depends(get_server)
) -> Any:
    _no_store(response)
    return await updates_for(server).status(user, refresh=True)


@router.post(
    "/client-updates/download",
    response_model=NodeStatus,
    summary="Download and verify the selected company update",
    description="User initiated. Downloading does not stop tasks or install software. Signature, repository URL, size and SHA-256 are checked before the native handoff.",
)
async def node_download(
    response: Response, user: User = Depends(current_user), server: Any = Depends(get_server)
) -> Any:
    _no_store(response)
    return await updates_for(server).download(user)


@router.post(
    "/client-updates/jobs/{identifier}/prepare",
    response_model=ReadyTicket,
    summary="Reserve an idle client for an explicit native update",
    description="Revalidates publication and member access, refuses active tasks or approvals, and creates a short-lived local handoff. It does not execute server-supplied commands.",
)
async def node_prepare(
    identifier: str,
    response: Response,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    _no_store(response)
    return await updates_for(server).prepare_install(user, identifier)


@router.post(
    "/client-updates/jobs/{identifier}/cancel",
    response_model=NodeStatus,
    summary="Cancel this member's update download",
)
async def node_cancel(
    identifier: str,
    response: Response,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    _no_store(response)
    return await updates_for(server).cancel(user, identifier)


@router.post(
    "/client-updates/jobs/{identifier}/abort-install",
    response_model=NodeStatus,
    summary="Release a native handoff that could not start",
)
async def node_abort(
    identifier: str,
    response: Response,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    _no_store(response)
    return await updates_for(server).abort_install(user, identifier)
