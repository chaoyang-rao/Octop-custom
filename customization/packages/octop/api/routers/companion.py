"""Thin companion policy and local expert discovery adapters."""

from __future__ import annotations

import asyncio
import ipaddress
import os
from typing import Any, Literal

from fastapi import APIRouter, Body, Depends, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, SecretStr

from octop.api.deps import current_user, get_server
from octop.api.routers.enterprise_mcp_admin import _no_store
from octop.api.routers.enterprise_resources_admin import ResourceRoute
from octop.infra.enterprise_resources.companion import (
    CompanionAdminState,
    CompanionAgent,
    CompanionCatalog,
    CompanionPolicy,
    companion_agents,
    companion_mode,
)
from octop.infra.enterprise_resources.companion_installers import installer_for
from octop.infra.enterprise_resources.inference import InferenceConfig, inference_for
from octop.infra.enterprise_resources.inference_node import company_model_usage
from octop.infra.enterprise_resources.models import StrictModel
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.setup.companion import companion_access, launcher_for
from octop.infra.setup.companion_package import CompanionInstaller
from octop.infra.users.identity import User

router = APIRouter(route_class=ResourceRoute)
center_router = APIRouter(route_class=ResourceRoute)


class PolicyUpdate(StrictModel):
    policy: CompanionPolicy
    expected_etag: str = Field(pattern=r"^[0-9a-f]{64}$")


class EngineHealth(BaseModel):
    companion: bool
    instance: str
    companion_version: str = ""
    client_update_pending: bool = False


class LaunchRequest(StrictModel):
    action: Literal["open", "size"] = "open"


class CompanionAccessState(StrictModel):
    allowed: bool
    managed: bool
    supported: bool


@router.get(
    "/companion/access",
    response_model=CompanionAccessState,
    summary="Read this member's server-controlled desktop pet access",
)
async def access(
    user: User = Depends(current_user), server: Any = Depends(get_server)
) -> dict[str, Any]:
    return await companion_access(server, user)


@router.post(
    "/companion/launch",
    summary="Prepare and open the independent desktop pet",
    description="Requires the logged-in member to have server-granted pet access. Available only on the local computer's own loopback interface. A pinned publisher signature and SHA-256 are verified before installing a missing component; user data is retained.",
)
async def launch(
    body: LaunchRequest,
    request: Request,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    try:
        local = request.client is not None and ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        local = False
    if (
        not local
        or request.url.hostname not in {"127.0.0.1", "localhost", "::1"}
        or any(name in request.headers for name in ("forwarded", "x-forwarded-for"))
    ):
        raise OctopError.localized(ErrorCode.FORBIDDEN)
    return await launcher_for(server).launch(user, body.action)


@center_router.get(
    "/enterprise/companion/installer",
    response_model=CompanionInstaller,
    summary="Read the signed private desktop-pet component manifest",
)
async def installer_manifest(
    response: Response,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
    platform: Literal["macos", "windows-amd64"] = "macos",
) -> CompanionInstaller:
    _no_store(response)
    metadata, _ = await asyncio.to_thread(installer_for, server, user, platform)
    return metadata


@center_router.get(
    "/enterprise/companion/installer/file",
    response_class=FileResponse,
    summary="Download the private desktop-pet component for an enabled member",
)
async def installer_file(
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
    platform: Literal["macos", "windows-amd64"] = "macos",
) -> FileResponse:
    metadata, path = await asyncio.to_thread(installer_for, server, user, platform)
    return FileResponse(
        path,
        filename=metadata.filename,
        media_type="application/zip",
        headers={"Cache-Control": "no-store"},
    )


@center_router.get(
    "/enterprise/companion/artwork",
    response_model=CompanionInstaller,
    summary="Read signed internal pet artwork for an authorized member",
)
async def artwork_manifest(
    response: Response, user: User = Depends(current_user), server: Any = Depends(get_server)
) -> CompanionInstaller:
    _no_store(response)
    metadata, _ = await asyncio.to_thread(installer_for, server, user, "artwork")
    return metadata


@center_router.get(
    "/enterprise/companion/artwork/file",
    response_class=FileResponse,
    summary="Download internal pet artwork after member authorization",
)
async def artwork_file(
    user: User = Depends(current_user), server: Any = Depends(get_server)
) -> FileResponse:
    metadata, path = await asyncio.to_thread(installer_for, server, user, "artwork")
    return FileResponse(
        path,
        filename=metadata.filename,
        media_type="application/zip",
        headers={"Cache-Control": "no-store"},
    )


@router.get(
    "/companion/artwork",
    response_model=CompanionInstaller,
    summary="Prepare authorized, signed artwork through the local engine",
)
async def local_artwork_manifest(
    response: Response, user: User = Depends(current_user), server: Any = Depends(get_server)
) -> CompanionInstaller:
    _no_store(response)
    metadata, _ = await launcher_for(server).artwork(user)
    return metadata


@router.get(
    "/companion/artwork/file",
    response_class=FileResponse,
    summary="Read verified artwork without exposing enterprise device credentials",
)
async def local_artwork_file(
    user: User = Depends(current_user), server: Any = Depends(get_server)
) -> FileResponse:
    metadata, path = await launcher_for(server).artwork(user)
    return FileResponse(
        path,
        filename=metadata.filename,
        media_type="application/zip",
        headers={"Cache-Control": "no-store"},
    )


@router.get(
    "/health/companion",
    response_model=EngineHealth,
    summary="Identify the companion-owned local engine",
)
async def health(server: Any = Depends(get_server)) -> dict[str, Any]:
    return {
        "companion": companion_mode(),
        "instance": os.environ.get("OCTOP_COMPANION_INSTANCE", ""),
        "companion_version": os.environ.get("OCTOP_DESKTOP_CLIENT_VERSION", "")
        if companion_mode()
        else "",
        "client_update_pending": bool(
            os.environ.get("OCTOP_CLIENT_UPDATE_PENDING")
            and getattr(server, "_client_updates", None)
            and server._client_updates.pending_activation()
        ),
    }


@center_router.get(
    "/enterprise/companion/admin/experts",
    response_model=CompanionAdminState,
    summary="Read companion expert controls",
)
async def admin(
    response: Response, user: User = Depends(current_user), server: Any = Depends(get_server)
) -> dict[str, Any]:
    _no_store(response)
    return await asyncio.to_thread(CompanionCatalog(server).admin, user)


@center_router.put(
    "/enterprise/companion/admin/experts",
    response_model=CompanionAdminState,
    summary="Set experts open to desktop companions",
)
async def save(
    body: PolicyUpdate,
    response: Response,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    _no_store(response)
    return await asyncio.to_thread(
        CompanionCatalog(server).save, user, body.policy, body.expected_etag
    )


@center_router.get(
    "/enterprise/companion/experts",
    response_model=CompanionPolicy,
    summary="Read eligible open companion experts",
)
async def eligible(
    response: Response, user: User = Depends(current_user), server: Any = Depends(get_server)
) -> dict[str, Any]:
    _no_store(response)
    return await asyncio.to_thread(CompanionCatalog(server).member, user)


@router.get(
    "/companion/agents",
    response_model=list[CompanionAgent],
    summary="List this member's available companion expert copies",
)
async def agents(
    response: Response, user: User = Depends(current_user), server: Any = Depends(get_server)
) -> list[CompanionAgent]:
    _no_store(response)
    return await companion_agents(server, user)


class ModelServiceProfile(BaseModel):
    revision: str
    default_model: str
    models: list[dict[str, Any]]
    stream_usage: bool


class CompanyUsageRow(BaseModel):
    user_id: int
    member_name: str
    model: str
    requests: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_requests: int
    last_used: int


class CompanyUsageSummary(BaseModel):
    scope: str
    range_start: int
    range_end: int
    totals: dict[str, int]
    rows: list[CompanyUsageRow]


@center_router.get("/enterprise/companion/inference/usage", response_model=CompanyUsageSummary)
@center_router.get("/enterprise/models/usage", response_model=CompanyUsageSummary)
async def model_usage(
    response: Response,
    days: int = Query(default=30, ge=1, le=366),
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    """Company admins see every member; employees see only their own model usage."""
    _no_store(response)
    return await company_model_usage(server, user, days)


class ModelServiceAdmin(BaseModel):
    etag: str
    enabled: bool
    base_url: str
    default_model: str
    models: list[dict[str, Any]]
    stream_usage: bool
    max_output_tokens: int
    requests_per_minute: int
    concurrent_per_user: int
    key_configured: bool


class ModelServiceUpdate(StrictModel):
    expected_etag: str
    enabled: bool
    base_url: str
    default_model: str
    models: list[dict[str, Any]]
    stream_usage: bool = False
    max_output_tokens: int = 8192
    requests_per_minute: int = 20
    concurrent_per_user: int = 2
    api_key: SecretStr | None = None


@center_router.get(
    "/enterprise/companion/admin/inference",
    response_model=ModelServiceAdmin,
    summary="Read company model service settings without credentials",
)
async def model_admin(
    response: Response, user: User = Depends(current_user), server: Any = Depends(get_server)
) -> dict[str, Any]:
    _no_store(response)
    return await asyncio.to_thread(inference_for(server).admin, user)


@center_router.put(
    "/enterprise/companion/admin/inference",
    response_model=ModelServiceAdmin,
    summary="Configure the company-managed model connection",
)
async def model_admin_save(
    body: ModelServiceUpdate,
    response: Response,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    _no_store(response)
    service = inference_for(server)
    await asyncio.to_thread(service.catalog.catalog._admin, user)
    _, old = await asyncio.to_thread(service.config)
    values = body.model_dump(exclude={"expected_etag", "api_key"})
    values.update(
        api_key=body.api_key.get_secret_value() if body.api_key is not None else old.api_key,
        headers=old.headers,
    )
    try:
        config = InferenceConfig.model_validate(values)
    except ValueError:
        raise OctopError.localized(ErrorCode.DORA_MODEL_INVALID_REQUEST) from None
    return await asyncio.to_thread(service.configure, user, config, body.expected_etag)


@center_router.get(
    "/enterprise/companion/inference/profile",
    response_model=ModelServiceProfile,
    summary="Read the built-in model catalog available to this employee",
)
async def model_profile(
    response: Response, user: User = Depends(current_user), server: Any = Depends(get_server)
) -> dict[str, Any]:
    _no_store(response)
    return await asyncio.to_thread(inference_for(server).profile, user)


@center_router.get(
    "/enterprise/companion/inference/v1/models", summary="OpenAI-compatible company model catalog"
)
async def model_list(
    response: Response, user: User = Depends(current_user), server: Any = Depends(get_server)
) -> dict[str, Any]:
    _no_store(response)
    profile = await asyncio.to_thread(inference_for(server).profile, user)
    return {
        "object": "list",
        "data": [
            {"id": m["id"], "object": "model", "created": 0, "owned_by": "company"}
            for m in profile["models"]
        ],
    }


async def _model_reply(server: Any, user: User, endpoint: str, payload: dict[str, Any]) -> Response:
    reply = await inference_for(server).open(user, endpoint, payload)
    if reply.streaming:
        return StreamingResponse(
            reply.events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )
    return JSONResponse(await reply.json(), headers={"Cache-Control": "no-store"})


@center_router.post(
    "/enterprise/companion/inference/v1/chat/completions",
    summary="Run an authorized, metered company chat-model request",
    description="Forwards model requests to the configured provider. The center stores usage metadata, not chat bodies; it never runs the requested tools.",
)
async def model_chat(
    payload: dict[str, Any] = Body(...),
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> Response:
    return await _model_reply(server, user, "chat/completions", payload)


@center_router.post(
    "/enterprise/companion/inference/v1/responses",
    summary="Run an authorized OpenAI Responses request",
)
async def model_responses(
    payload: dict[str, Any] = Body(...),
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> Response:
    return await _model_reply(server, user, "responses", payload)
