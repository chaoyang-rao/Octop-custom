"""Apply explicit device capabilities to existing HTTP and WebSocket routes."""

from __future__ import annotations

import re
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from octop.infra.errors import ErrorCode, OctopError
from octop.infra.mobile_access.service import TOKEN_PREFIX, DeviceSession, service_for
from octop.infra.users.identity import User


@dataclass
class MobileRequestContext:
    path: str
    method: str
    secure_transport: bool = True
    token: str | None = field(default=None, repr=False)
    locale: str | None = None


CURRENT_MOBILE_REQUEST: ContextVar[MobileRequestContext | None] = ContextVar(
    "mobile_request", default=None
)


@dataclass
class MobileUser(User):
    device_id: str = ""
    device_scopes: tuple[str, ...] = ()
    device_kind: str = "device"


def authorize_device_path(session: DeviceSession, path: str, method: str) -> None:
    """Deny management by default, including raw Bridge peer and config surfaces."""
    scopes = set(session.scopes)
    read = method in {"GET", "HEAD"}
    allowed = False
    if session.kind == "share":
        allowed = read and path in {
            "/api/auth/me",
            "/api/settings/timezone",
            "/api/settings/upload",
            "/api/mobile-access/share/experts",
        }
        allowed = allowed or (
            method == "POST"
            and "files" in scopes
            and bool(re.fullmatch(r"/api/agents/[^/]+/upload", path))
        )
        allowed = allowed or (method == "POST" and "tasks" in scopes and path == "/api/tasks")
        if not allowed:
            raise OctopError(
                ErrorCode.FORBIDDEN, "share credential permits only explicit one-shot sharing"
            )
        return
    if (
        path
        in {
            "/api/auth/me",
            "/api/settings/timezone",
            "/api/settings/upload",
            "/api/settings/hitl",
            "/api/settings/capabilities",
            "/api/mobile-access/self",
        }
        or path == f"/api/users/{session.user_id}/avatar"
    ):
        allowed = read
    elif path == "/api/preferences":
        allowed = method in {"GET", "HEAD", "PATCH"} and "chat" in scopes
    elif path == "/api/auth/logout":
        allowed = method == "POST"
    elif path in {
        "/api/mobile-access/self/push",
        "/api/mobile-access/self/activity",
        "/api/mobile-access/self/notifications",
    }:
        allowed = method in {"PUT", "DELETE"} and "notifications" in scopes
    elif path in {"/api/mobile-access/self/share-grant", "/api/mobile-access/share/experts"}:
        allowed = (method == "POST" if path.endswith("share-grant") else read) and "chat" in scopes
    elif path.startswith("/api/mobile-access/task-actions/"):
        allowed = method == "POST" and "tasks" in scopes
    elif path == "/api/mobile-access/presence":
        allowed = method == "POST" and bool(scopes & {"chat", "notifications"})
    elif path == "/api/mobile-access/self/revoke":
        allowed = method == "POST"
    elif re.fullmatch(r"/api/agents/[^/]+/native-cli/models", path):
        allowed = method == "GET" and "chat" in scopes
    elif path.startswith("/api/slash/"):
        allowed = read and "chat" in scopes
    elif path.startswith("/api/i18n/"):
        allowed = read
    elif path == "/api/notifications/ws":
        allowed = "notifications" in scopes
    elif path in {"/api/voice/stt", "/api/voice/tts", "/api/voice/stt-stream"}:
        allowed = "chat" in scopes
    elif path in {"/api/voice/active", "/api/voice/presets"}:
        allowed = read and "chat" in scopes
    elif re.match(r"^/api/(?:agents/[^/]+/)?terminal(?:/|$)", path):
        allowed = "terminal" in scopes
    elif re.match(r"^/api/(?:agents/[^/]+/)?(?:desktop)(?:/|$)", path):
        allowed = "desktop" in scopes
    elif re.match(r"^/api/(?:agents/[^/]+/)?mobile(?:/|$)", path):
        allowed = "phone" in scopes
    elif re.match(
        r"^/api/(?:browser(?:/|$)|browser-stream/|bridge/connections/[^/]+/browser)", path
    ):
        allowed = "browser" in scopes
    elif path == "/api/bridge/connections" or re.match(
        r"^/api/bridge/connections/[^/]+/(?:agents|providers/resolved|providers/active-model)$",
        path,
    ):
        allowed = read and "chat" in scopes
    elif (
        path in {"/api/knowledge-bases", "/api/knowledge-bases/capability"}
        or re.match(r"^/api/bridge/connections/[^/]+/knowledge-bases(?:/capability)?$", path)
        or re.match(r"^/api/agents/[^/]+/(?:skills|knowledge-bases)(?:/|$)", path)
    ):
        allowed = read and "files" in scopes
    elif re.match(r"^/api/(?:tasks|workflows|task-queue|tasks-calendar)(?:/|$)", path):
        allowed = "tasks" in scopes
    elif re.match(
        r"^/api/agents/[^/]+/(?:workspace|download|upload|files|media)(?:/|$)", path
    ) or re.match(r"^/api/(?:downloads|uploads)(?:/|$)", path):
        allowed = "files" in scopes
    elif re.match(r"^/api/agents(?:/[^/]+)?$", path):
        allowed = (read and "chat" in scopes) or "manage_agents" in scopes
    elif re.match(
        r"^/api/agents/[^/]+/(?:chat|threads|session|projects|read|status|avatar|trajectory)(?:/|$)",
        path,
    ):
        allowed = "chat" in scopes
    elif re.match(r"^/api/(?:experts|teams)(?:/|$)", path):
        allowed = (read and "chat" in scopes) or "manage_agents" in scopes
    elif re.match(
        r"^/api/agents/[^/]+/(?:start|stop|reload|config|settings|copy|clone|cli)(?:/|$)", path
    ):
        allowed = "manage_agents" in scopes
    elif path in {
        "/api/models/catalog",
        "/api/models/active",
        "/api/providers/models",
        "/api/providers/resolved",
        "/api/providers/active-model",
        "/api/connectors/instances",
        "/api/connectors/catalog",
    }:
        allowed = read and "chat" in scopes
    if not allowed:
        raise OctopError(ErrorCode.FORBIDDEN, "mobile device capability required")


def effective_device_scopes(owner: User, scopes: tuple[str, ...] | list[str]) -> list[str]:
    required = {
        "browser": "browser",
        "desktop": "desktop",
        "terminal": "terminal",
        "phone": "mobile",
        "tasks": "tasks",
        "manage_agents": "experts",
    }
    return [
        scope
        for scope in scopes
        if owner.is_admin or scope not in required or required[scope] in owner.permissions
    ]


def resolve_mobile_user(
    server: Any, token: str, *, path: str | None = None, method: str | None = None
) -> MobileUser:
    context = CURRENT_MOBILE_REQUEST.get()
    if context is None and (path is None or method is None):
        # Unscoped integrations must not accidentally accept device sessions.
        raise OctopError(ErrorCode.AUTH_FAILED, "mobile request context missing")
    if context is not None and not context.secure_transport:
        raise OctopError(ErrorCode.FORBIDDEN, "mobile device transport requires HTTPS")
    session = service_for(server).authenticate(token)
    assert server.user_manager is not None
    owner = server.user_manager.get_by_id(session.user_id)
    if owner is None:
        raise OctopError(ErrorCode.USER_DISABLED, "user not active")
    if context is not None:
        context.locale = owner.locale
    effective = effective_device_scopes(owner, session.scopes)
    session = DeviceSession(
        session.user_id, session.device_id, tuple(effective), session.expires_at, session.kind
    )
    authorize_device_path(session, path or context.path, method or context.method)  # type: ignore[union-attr]
    granted = {"experts", "token_usage"}
    for scope, permission in {
        "tasks": "tasks",
        "browser": "browser",
        "desktop": "desktop",
        "terminal": "terminal",
        "phone": "mobile",
    }.items():
        if scope in session.scopes:
            granted.add(permission)
    if not owner.is_admin:
        granted &= set(owner.permissions)
    if context is not None:
        context.token = token
    return MobileUser(
        id=owner.id,
        username=owner.username,
        role="user",
        display_name=owner.display_name,
        locale=owner.locale,
        permissions=sorted(granted),
        device_id=session.device_id,
        device_scopes=session.scopes,
        device_kind=session.kind,
    )


def is_mobile_token(token: str) -> bool:
    return token.startswith(TOKEN_PREFIX)
