"""Enterprise identity pairing for clients that execute on their own computer."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, Request, Response
from pydantic import BaseModel, Field, SecretStr

from octop.api.deps import current_user, extract_raw_token, get_server, resolve_user_from_token
from octop.api.routers.auth import me_payload
from octop.infra.auth.enterprise import center_for, client_for, enterprise_error
from octop.infra.auth.mfa.service import MfaService
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.users.identity import User
from octop.infra.users.permissions import user_has_permission

router = APIRouter()


class DeviceName(BaseModel):
    name: str = Field(min_length=1, max_length=80, description="Device label shown before consent.")


class NodeDeviceName(DeviceName):
    bind_current: bool = Field(
        default=False, description="Explicitly keep the signed-in local account and its data."
    )


class PairingSecret(BaseModel):
    pairing_secret: SecretStr = Field(min_length=20, max_length=100)


class PairingCode(BaseModel):
    code: str = Field(
        min_length=8, max_length=12, description="Code displayed on the local computer."
    )


class LocalLogin(BaseModel):
    login_id: SecretStr = Field(min_length=20, max_length=100)
    confirmed: bool = Field(
        default=False,
        description="Confirm the displayed company identity before linking local data.",
    )


class EnterpriseStatus(BaseModel):
    center_enabled: bool
    node_enabled: bool
    authority_url: str | None


class EnterpriseChallenge(BaseModel):
    pairing_secret: str = Field(repr=False)
    user_code: str
    expires_at: int
    interval: int
    host_fingerprint: str


class EnterpriseExchange(BaseModel):
    status: Literal["pending", "approved"]
    expires_at: int
    access_token: str | None = Field(default=None, repr=False)
    device_id: str | None = None
    scopes: list[str] | None = None
    host_fingerprint: str | None = None


class EnterpriseProfile(BaseModel):
    subject: str
    display_name: str
    permissions: list[str]
    device_id: str
    expires_at: int


class CompanyDevice(BaseModel):
    device_id: str
    name: str
    revoked_at: int | None


class DevicePreview(BaseModel):
    name: str
    platform: str
    expires_at: int
    host_fingerprint: str


class NodeChallenge(BaseModel):
    login_id: str = Field(repr=False)
    user_code: str
    verification_uri: str
    expires_at: int
    interval: int


class NodeResult(BaseModel):
    status: Literal["pending", "approved", "expired", "confirm"]
    company_name: str | None = None
    local_name: str | None = None
    access_token: str | None = Field(default=None, repr=False)
    token_type: str | None = None
    expires_in: int | None = None
    user: dict[str, Any] | None = None


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


def _network(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.get(
    "/auth/enterprise/status", response_model=EnterpriseStatus, summary="Enterprise mode status"
)
async def status(response: Response, server: Any = Depends(get_server)) -> Any:
    _no_store(response)
    cfg = server.services.config if server.services else server.config
    client = client_for(server)
    return {
        "center_enabled": bool(cfg and cfg.enterprise_center_enabled),
        "node_enabled": bool(client),
        "authority_url": client.authority if client else None,
    }


@router.post(
    "/enterprise/pairings", response_model=EnterpriseChallenge, summary="Request company sign-in"
)
async def begin_pairing(
    body: DeviceName, request: Request, response: Response, server: Any = Depends(get_server)
) -> Any:
    _no_store(response)
    return await center_for(server).begin(body.name, _network(request))


@router.post(
    "/enterprise/pairings/exchange",
    response_model=EnterpriseExchange,
    response_model_exclude_none=True,
    summary="Exchange approved company device grant",
)
async def exchange_pairing(
    body: PairingSecret, request: Request, response: Response, server: Any = Depends(get_server)
) -> Any:
    _no_store(response)
    return await center_for(server).exchange(
        body.pairing_secret.get_secret_value(), _network(request)
    )


@router.post(
    "/enterprise/pairings/inspect",
    response_model=DevicePreview,
    summary="Inspect a company device before approval",
)
async def inspect_pairing(
    body: PairingCode, user: User = Depends(current_user), server: Any = Depends(get_server)
) -> dict[str, Any]:
    return await center_for(server).inspect(user, body.code)


@router.post(
    "/enterprise/pairings/approve",
    response_model=CompanyDevice,
    summary="Approve identity-only local execution sign-in",
)
async def approve_pairing(
    body: PairingCode, user: User = Depends(current_user), server: Any = Depends(get_server)
) -> dict[str, Any]:
    return await center_for(server).approve(user, body.code)


@router.get(
    "/enterprise/session",
    response_model=EnterpriseProfile,
    summary="Verify current company permissions",
)
async def profile(
    response: Response,
    user: User = Depends(current_user),
    authorization: str | None = Header(default=None),
    server: Any = Depends(get_server),
) -> Any:
    _no_store(response)
    return await asyncio.to_thread(
        center_for(server).profile, extract_raw_token(authorization=authorization) or ""
    )


@router.post(
    "/enterprise/session/revoke", status_code=204, summary="Revoke this company device grant"
)
async def revoke_session(
    user: User = Depends(current_user),
    authorization: str | None = Header(default=None),
    server: Any = Depends(get_server),
) -> None:
    await center_for(server).revoke(extract_raw_token(authorization=authorization) or "")


def _device_owner(user: User, user_id: int | None) -> int:
    owner = user_id or user.id
    if owner != user.id and not user_has_permission(user, "users"):
        raise enterprise_error(ErrorCode.ENTERPRISE_ACCESS_DENIED)
    return owner


@router.get(
    "/enterprise/devices",
    response_model=list[CompanyDevice],
    summary="List company grants for an account",
)
async def devices(
    user_id: int | None = None,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> list[dict[str, Any]]:
    center = center_for(server)
    center.require_enabled()
    rows = await center.devices.list_devices(_device_owner(user, user_id))
    return [row for row in rows if row["scopes"] == ["enterprise"]]


@router.delete(
    "/enterprise/devices/{device_id}",
    status_code=204,
    summary="Revoke an owned or administered company device",
)
async def revoke_device(
    device_id: str,
    user_id: int | None = None,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> None:
    center = center_for(server)
    center.require_enabled()
    await center.devices.revoke(user_id=_device_owner(user, user_id), device_id=device_id)


@router.post(
    "/auth/enterprise/start",
    response_model=NodeChallenge,
    summary="Start enterprise sign-in on this computer",
)
async def begin_local(
    body: NodeDeviceName,
    response: Response,
    server: Any = Depends(get_server),
    authorization: str | None = Header(default=None),
) -> Any:
    _no_store(response)
    client = client_for(server)
    if client is None:
        raise enterprise_error(ErrorCode.ENTERPRISE_NOT_CONFIGURED)
    local_id = None
    if body.bind_current:
        try:
            local_id = resolve_user_from_token(
                server, extract_raw_token(authorization=authorization) or ""
            ).id
        except OctopError:
            raise enterprise_error(ErrorCode.ENTERPRISE_LOCAL_LOGIN_REQUIRED) from None
    return await client.begin(body.name, binding_user_id=local_id)


@router.post(
    "/auth/enterprise/poll",
    response_model=NodeResult,
    response_model_exclude_none=True,
    summary="Complete enterprise sign-in on this computer",
)
async def poll_local(
    body: LocalLogin, response: Response, server: Any = Depends(get_server)
) -> dict[str, Any]:
    _no_store(response)
    client = client_for(server)
    if client is None:
        raise enterprise_error(ErrorCode.ENTERPRISE_NOT_CONFIGURED)
    result, user = await client.poll(body.login_id.get_secret_value(), confirmed=body.confirmed)
    if user is None:
        return result
    token, ttl = MfaService(server.services).mint_access_token(user)
    return {
        **result,
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": ttl,
        "user": me_payload(user, server),
    }
