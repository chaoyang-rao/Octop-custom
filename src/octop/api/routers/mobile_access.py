"""Owner-approved pairing and device-session management for mobile clients."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field, SecretStr

from octop.api.deps import current_user, extract_raw_token, get_server
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.mobile_access.access import MobileUser, effective_device_scopes
from octop.infra.mobile_access.service import DEFAULT_SCOPES, service_for, validate_server_url
from octop.infra.users.identity import User

router = APIRouter()


class PairingRequest(BaseModel):
    name: str = Field(
        min_length=1, max_length=80, description="Device name shown on the approving computer."
    )
    platform: Literal["ios", "android", "web"]


class PairingChallenge(BaseModel):
    pairing_secret: str = Field(
        repr=False, description="Keep on the requesting device; never put in a URL."
    )
    user_code: str = Field(
        description="Enter on an already signed-in computer and inspect the device before approval."
    )
    expires_at: int
    host_fingerprint: str
    interval: int


class PairingExchange(BaseModel):
    pairing_secret: SecretStr = Field(min_length=20, max_length=100)


class PairingResult(BaseModel):
    status: Literal["pending", "approved"]
    expires_at: int
    access_token: str | None = Field(
        default=None,
        repr=False,
        description="Device-scoped opaque credential, not a general account JWT.",
    )
    device_id: str | None = None
    scopes: list[str] | None = None
    host_fingerprint: str | None = None


class PairingCode(BaseModel):
    code: str = Field(min_length=8, max_length=20)


class PairingApproval(PairingCode):
    scopes: list[str] = Field(default_factory=lambda: list(DEFAULT_SCOPES))


class PairingPreview(BaseModel):
    name: str
    platform: str
    expires_at: int
    host_fingerprint: str


class NotificationPreferences(BaseModel):
    level: Literal["all", "needs-me", "none"] = "all"
    muted_until: int | None = None
    sound: bool = True
    preview: bool = False
    muted_agent_ids: list[str] = Field(default_factory=list)
    foreground: bool = False


class PatchNotificationPreferences(BaseModel):
    level: Literal["all", "needs-me", "none"] | None = None
    muted_until: int | None = Field(default=None, ge=0)
    sound: bool | None = None
    preview: bool | None = None
    muted_agent_ids: list[str] | None = Field(default=None, max_length=200)
    foreground: bool | None = None


class DeviceView(BaseModel):
    device_id: str
    name: str
    platform: str
    scopes: list[str]
    created_at: int
    expires_at: int
    revoked_at: int | None
    push_enabled: bool
    notification_preferences: NotificationPreferences = Field(
        default_factory=NotificationPreferences
    )


class PushRegistration(BaseModel):
    platform: Literal["apns", "fcm"]
    token: SecretStr = Field(min_length=16, max_length=4096)


def _full_session(user: User) -> None:
    if isinstance(user, MobileUser):
        raise OctopError(ErrorCode.FORBIDDEN, "pairing management requires an account session")


def _raw_device_token(request: Request, user: User) -> str:
    if not isinstance(user, MobileUser):
        raise OctopError(ErrorCode.FORBIDDEN, "device session required")
    raw = extract_raw_token(
        authorization=request.headers.get("authorization"),
        access_token=request.query_params.get("access_token"),
    )
    if not raw:
        raise OctopError(ErrorCode.AUTH_FAILED, "missing device credential")
    return raw


def _secure_response(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


def _secure_origin(request: Request) -> None:
    try:
        validate_server_url(str(request.base_url))
        if request.url.scheme == "http" and (
            request.client is None or request.client.host not in {"127.0.0.1", "::1", "localhost"}
        ):
            raise ValueError("mobile_access.https_required")
    except ValueError as exc:
        raise OctopError(ErrorCode.FORBIDDEN, str(exc)) from None


@router.post(
    "/pairings/request",
    response_model=PairingChallenge,
    summary="Request an owner-approved device pairing",
    description="Unauthenticated, rate-limited and valid for five minutes. Requires HTTPS except loopback development. No account access until an existing account session approves the displayed code.",
)
async def request_pairing(
    body: PairingRequest, request: Request, response: Response, server: Any = Depends(get_server)
) -> PairingChallenge:
    _secure_origin(request)
    _secure_response(response)
    result = await service_for(server).begin_pairing(
        name=body.name,
        platform=body.platform,
        network_key=request.client.host if request.client else "unknown",
    )
    return PairingChallenge(**result)


@router.post(
    "/pairings/exchange",
    response_model=PairingResult,
    response_model_exclude_none=True,
    summary="Poll and receive the approved device credential",
    description="Requires the requesting device's high-entropy secret. Retrying a successful exchange is safe until the challenge expires; revoked devices cannot be resurrected.",
)
async def exchange_pairing(
    body: PairingExchange, request: Request, response: Response, server: Any = Depends(get_server)
) -> PairingResult:
    _secure_origin(request)
    _secure_response(response)
    result = await service_for(server).exchange_pairing(
        pairing_secret=body.pairing_secret.get_secret_value(),
        network_key=request.client.host if request.client else "unknown",
    )
    return PairingResult(**result)


@router.post(
    "/pairings/inspect",
    response_model=PairingPreview,
    summary="Inspect the requesting device before approval",
)
async def inspect_pairing(
    body: PairingCode,
    response: Response,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> PairingPreview:
    _full_session(user)
    _secure_response(response)
    return PairingPreview(
        **await service_for(server).inspect_pairing(user_id=user.id, code=body.code)
    )


@router.post(
    "/pairings/approve",
    response_model=DeviceView,
    summary="Approve a device with explicit capabilities",
)
async def approve_pairing(
    body: PairingApproval,
    response: Response,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> DeviceView:
    _full_session(user)
    _secure_response(response)
    if set(effective_device_scopes(user, body.scopes)) != set(body.scopes):
        raise OctopError(
            ErrorCode.FORBIDDEN, "cannot grant device capabilities unavailable to the account"
        )
    try:
        result = await service_for(server).approve_pairing(
            user_id=user.id, code=body.code, scopes=body.scopes
        )
    except ValueError:
        raise OctopError(ErrorCode.FORBIDDEN, "invalid device capabilities") from None
    return DeviceView(**result)


@router.get(
    "/devices", response_model=list[DeviceView], summary="List this account's paired devices"
)
async def list_devices(
    response: Response, user: User = Depends(current_user), server: Any = Depends(get_server)
) -> list[DeviceView]:
    _full_session(user)
    _secure_response(response)
    return [DeviceView(**row) for row in await service_for(server).list_devices(user.id)]


@router.delete(
    "/devices/{device_id}", status_code=204, summary="Revoke a paired device immediately"
)
async def revoke_device(
    device_id: str, user: User = Depends(current_user), server: Any = Depends(get_server)
) -> None:
    _full_session(user)
    await service_for(server).revoke(user_id=user.id, device_id=device_id)


@router.get("/self", response_model=DeviceView, summary="Read the current device grant")
async def device_self(
    request: Request,
    response: Response,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> DeviceView:
    _raw_device_token(request, user)
    _secure_response(response)
    rows = await service_for(server).list_devices(user.id)
    return DeviceView(**next(row for row in rows if row["device_id"] == user.device_id))  # type: ignore[attr-defined]


@router.post("/self/revoke", status_code=204, summary="Sign out and revoke this device")
async def revoke_self(
    request: Request, user: User = Depends(current_user), server: Any = Depends(get_server)
) -> None:
    _raw_device_token(request, user)
    await service_for(server).revoke(user_id=user.id, device_id=user.device_id)  # type: ignore[attr-defined]


@router.put(
    "/self/push", status_code=204, summary="Register this device's encrypted push delivery token"
)
async def register_push(
    body: PushRegistration,
    request: Request,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> None:
    token = _raw_device_token(request, user)
    try:
        await service_for(server).register_push(
            token=token, platform=body.platform, push_token=body.token.get_secret_value()
        )
    except ValueError:
        raise OctopError(ErrorCode.FORBIDDEN, "invalid push token") from None


class PushConfiguration(BaseModel):
    enabled: bool = True
    team_id: str | None = None
    key_id: str | None = None
    topic: str | None = None
    sandbox: bool = True
    project_id: str | None = None
    client_email: str | None = None
    private_key: SecretStr | None = Field(default=None, repr=False)


@router.get(
    "/push/config",
    response_model=dict[str, bool],
    summary="Read push provider readiness without credentials",
)
async def push_status(
    user: User = Depends(current_user), server: Any = Depends(get_server)
) -> dict[str, bool]:
    from octop.infra.mobile_access.push import push_for

    _full_session(user)
    return await push_for(server).configuration_status()


@router.put(
    "/push/config/{provider}",
    response_model=dict[str, bool],
    summary="Configure an owned APNS or FCM project",
    description="Administrator account session only. Keys are encrypted and never returned. No notification is sent by configuring a provider.",
)
async def configure_push(
    provider: Literal["apns", "fcm"],
    body: PushConfiguration,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, bool]:
    from octop.infra.mobile_access.push import push_for

    _full_session(user)
    if not user.is_admin:
        raise OctopError(ErrorCode.FORBIDDEN, "admin required")
    config = body.model_dump(exclude={"private_key", "enabled"}, exclude_none=True)
    if body.private_key is not None:
        config["private_key"] = body.private_key.get_secret_value()
    try:
        await push_for(server).configure(provider, config if body.enabled else None)
    except ValueError:
        raise OctopError(ErrorCode.FORBIDDEN, "invalid push provider configuration") from None
    return await push_for(server).configuration_status()


class ActivityRegistration(BaseModel):
    activity_id: str = Field(min_length=1, max_length=128)
    thread_id: str = Field(min_length=1, max_length=256)
    token: SecretStr = Field(min_length=32, max_length=256)


@router.put(
    "/self/activity",
    status_code=204,
    summary="Register a thread's encrypted Live Activity push token",
)
async def register_activity(
    body: ActivityRegistration,
    request: Request,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> None:
    token = _raw_device_token(request, user)
    try:
        await service_for(server).register_activity(
            token=token,
            activity_id=body.activity_id,
            thread_id=body.thread_id,
            push_token=body.token.get_secret_value(),
        )
    except ValueError:
        raise OctopError(ErrorCode.FORBIDDEN, "invalid live activity registration") from None


class ServerIdentity(BaseModel):
    protocol: str = "octop-mobile-v1"
    host_fingerprint: str


@router.get(
    "/identity",
    response_model=ServerIdentity,
    summary="Read the public mobile host identity",
    description="Public fingerprint only; exposes no account, session or provider information.",
)
async def public_identity(server: Any = Depends(get_server)) -> ServerIdentity:
    import asyncio

    return ServerIdentity(
        host_fingerprint=await asyncio.to_thread(service_for(server)._host_fingerprint)
    )


class RemoteCheckResult(BaseModel):
    url: str
    checked_at: int
    dns: bool
    tls: bool
    http_status: int | None
    identity_matches: bool
    ok: bool
    reason: Literal[
        "ready",
        "identity_mismatch",
        "dns",
        "connection_or_certificate",
        "route_or_proxy",
        "unreachable",
    ]


class RemoteStatusView(BaseModel):
    public_url: str | None
    request_origin: str
    listener: str
    native_tls: bool
    tailscale_installed: bool
    last_check: RemoteCheckResult | None


class RemoteAddressView(BaseModel):
    url: str


class TailscaleStatusView(BaseModel):
    authenticated: bool
    url: str | None
    owned: bool


class RemoteEnabledView(BaseModel):
    url: str
    enabled: bool
    network: Literal["tailnet"]


class RemoteDisabledView(BaseModel):
    enabled: bool


class RemoteUrl(BaseModel):
    url: str = Field(min_length=8, max_length=512)


def _remote_operator(user: User) -> None:
    from octop.infra.users.permissions import user_has_permission

    _full_session(user)
    if not user_has_permission(user, "tls"):
        raise OctopError(ErrorCode.FORBIDDEN, "TLS management permission required")


@router.get(
    "/remote/status",
    response_model=RemoteStatusView,
    summary="Read the configured remote address and listener state",
)
async def remote_status(
    request: Request, user: User = Depends(current_user), server: Any = Depends(get_server)
) -> RemoteStatusView:
    from octop.infra.mobile_access.remote import remote_for

    _full_session(user)
    return RemoteStatusView(**await remote_for(server).status(str(request.base_url).rstrip("/")))


@router.put(
    "/remote/url", response_model=RemoteAddressView, summary="Save this host's remote HTTPS address"
)
async def configure_remote(
    body: RemoteUrl, user: User = Depends(current_user), server: Any = Depends(get_server)
) -> RemoteAddressView:
    from octop.infra.mobile_access.remote import remote_for

    _remote_operator(user)
    try:
        return RemoteAddressView(url=await remote_for(server).configure(body.url))
    except ValueError:
        raise OctopError(ErrorCode.FORBIDDEN, "a valid HTTPS origin is required") from None


@router.post(
    "/remote/check",
    response_model=RemoteCheckResult,
    summary="Check DNS, TLS, routing and the host identity",
    description="TLS operator account only. Fetches only the fixed public identity endpoint without credentials, follows no redirects, and returns no remote response body.",
)
async def check_remote(
    body: RemoteUrl, user: User = Depends(current_user), server: Any = Depends(get_server)
) -> RemoteCheckResult:
    from octop.infra.mobile_access.remote import remote_for

    _remote_operator(user)
    try:
        return RemoteCheckResult(**await remote_for(server).diagnose(body.url))
    except ValueError:
        raise OctopError(ErrorCode.FORBIDDEN, "a valid HTTPS origin is required") from None


@router.get(
    "/remote/tailscale",
    response_model=TailscaleStatusView,
    summary="Read the local Tailscale setup state without account details",
)
async def tailscale_status(
    user: User = Depends(current_user), server: Any = Depends(get_server)
) -> TailscaleStatusView:
    from octop.infra.mobile_access.remote import remote_for

    _remote_operator(user)
    return TailscaleStatusView(**await remote_for(server).tailscale_status())


@router.post(
    "/remote/tailscale/enable",
    response_model=RemoteEnabledView,
    summary="Enable an owned private HTTPS Tailscale Serve mapping",
    description="Explicit operator action. Does not install or sign in to Tailscale, does not enable Funnel, and refuses to overwrite existing mappings belonging to another service.",
)
async def enable_tailscale(
    user: User = Depends(current_user), server: Any = Depends(get_server)
) -> RemoteEnabledView:
    from octop.infra.mobile_access.remote import remote_for

    _remote_operator(user)
    return RemoteEnabledView(**await remote_for(server).enable_tailscale())


@router.post(
    "/remote/tailscale/disable",
    response_model=RemoteDisabledView,
    summary="Remove only an unchanged Octop-owned Tailscale Serve mapping",
)
async def disable_tailscale(
    user: User = Depends(current_user), server: Any = Depends(get_server)
) -> RemoteDisabledView:
    from octop.infra.mobile_access.remote import remote_for

    _remote_operator(user)
    return RemoteDisabledView(**await remote_for(server).disable_tailscale())


@router.delete(
    "/self/activity", status_code=204, summary="Remove this device's registered Live Activities"
)
async def remove_activities(
    request: Request, user: User = Depends(current_user), server: Any = Depends(get_server)
) -> None:
    await service_for(server).remove_activities(token=_raw_device_token(request, user))


@router.put(
    "/self/notifications",
    response_model=NotificationPreferences,
    summary="Update this device's notification choices and foreground heartbeat",
    description="Preview is disabled by default. Foreground presence is short-lived and memory-only. Device-specific level, mute, sound, preview and expert switches survive server restarts.",
)
async def update_notification_preferences(
    body: PatchNotificationPreferences,
    request: Request,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> NotificationPreferences:
    token = _raw_device_token(request, user)
    try:
        return NotificationPreferences(
            **await service_for(server).update_notification_preferences(
                token=token, changes=body.model_dump(exclude_unset=True)
            )
        )
    except ValueError:
        raise OctopError(ErrorCode.FORBIDDEN, "invalid device notification preferences") from None


class ClientPresence(BaseModel):
    client_id: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    active: bool


@router.post(
    "/presence", status_code=204, summary="Report recent activity without recording input content"
)
async def client_presence(
    body: ClientPresence, user: User = Depends(current_user), server: Any = Depends(get_server)
) -> None:
    service_for(server).note_presence(
        user_id=user.id,
        client_id=body.client_id,
        device_id=user.device_id if isinstance(user, MobileUser) else None,
        active=body.active,
    )


class ShareGrantView(BaseModel):
    access_token: str = Field(repr=False)
    scopes: list[str]
    expires_at: int


@router.post(
    "/self/share-grant",
    response_model=ShareGrantView,
    summary="Create a constrained, revocable share-extension credential",
    description="Primary device session only. The derived share credential cannot manage workflows, schedules, providers, controls or notification configuration. It expires/revokes with the original device; only its hash is persisted.",
)
async def share_grant(
    request: Request,
    response: Response,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> ShareGrantView:
    token = _raw_device_token(request, user)
    _secure_response(response)
    return ShareGrantView(**await service_for(server).share_grant(token))


class ShareExpertLabel(BaseModel):
    agent_id: str
    name: str


@router.get(
    "/share/experts",
    response_model=list[ShareExpertLabel],
    summary="List owned enabled expert labels for the share sheet",
)
async def share_experts(
    user: User = Depends(current_user), server: Any = Depends(get_server)
) -> list[ShareExpertLabel]:
    from octop.infra.mobile_access.shares import share_expert_labels

    return [ShareExpertLabel(**row) for row in await share_expert_labels(server, user.id)]


class TaskNavigationRequest(BaseModel):
    task_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_:-]+$")
    attempt: int = Field(ge=0)


class TaskNavigationView(BaseModel):
    navigation: str = Field(
        description="Signed read-only navigation descriptor; cannot execute an action."
    )


class PrepareTaskAction(BaseModel):
    navigation: str = Field(min_length=40, max_length=2048)


class TaskConfirmation(BaseModel):
    task_id: str
    attempt: int
    operation: Literal["cancel"]
    title: str
    agent_id: str
    confirmation: str = Field(
        repr=False, description="One-use device-bound proof, valid for 120 seconds."
    )
    expires_at: int


class ExecuteTaskAction(BaseModel):
    confirmation: SecretStr = Field(min_length=40, max_length=100)


class TaskActionReceipt(BaseModel):
    status: Literal["cancelled"]


@router.post(
    "/task-actions/navigation",
    response_model=TaskNavigationView,
    summary="Sign read-only navigation for a particular task attempt",
    description="Primary task-scoped device only. Opening the resulting link never executes an action. Approvals must still be reviewed in the conversation.",
)
async def task_navigation(
    body: TaskNavigationRequest,
    request: Request,
    response: Response,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> TaskNavigationView:
    from octop.infra.mobile_access.actions import actions_for

    _secure_response(response)
    return TaskNavigationView(
        navigation=await actions_for(server).navigation(
            _raw_device_token(request, user), body.task_id, body.attempt
        )
    )


@router.post(
    "/task-actions/prepare",
    response_model=TaskConfirmation,
    summary="Review a current task before confirming cancellation",
    description="Checks signature, server, device, current owner permission and task attempt. Returns the real task title plus a short one-use confirmation; no task is changed.",
)
async def prepare_task_action(
    body: PrepareTaskAction,
    request: Request,
    response: Response,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> TaskConfirmation:
    from octop.infra.mobile_access.actions import actions_for

    _secure_response(response)
    return TaskConfirmation(
        **await actions_for(server).prepare(_raw_device_token(request, user), body.navigation)
    )


@router.post(
    "/task-actions/execute",
    response_model=TaskActionReceipt,
    summary="Confirm cancellation of exactly the reviewed task attempt",
    description="Requires the same unrevoked task-scoped device and a fresh one-use confirmation. Execution consumes the proof before mutating the task; never automatically retry an unknown response.",
)
async def execute_task_action(
    body: ExecuteTaskAction,
    request: Request,
    response: Response,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> TaskActionReceipt:
    from octop.infra.mobile_access.actions import actions_for

    _secure_response(response)
    await actions_for(server).execute(
        _raw_device_token(request, user), body.confirmation.get_secret_value()
    )
    return TaskActionReceipt(status="cancelled")
