"""Require JWT for all /api/* routes except an explicit allowlist.

Validated users are cached on ``request.state.octop_user`` so route-level
``Depends(current_user)`` can reuse the result without re-decoding.

When the access token is past the sliding-renew threshold, a fresh token is
attached as ``X-Octop-Access-Token`` on the response.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from octop.api.deps import (
    ACCESS_TOKEN_RESPONSE_HEADER,
    authenticate_request,
    extract_raw_token,
    is_jwt_exempt_request,
    maybe_sliding_renew_token,
)
from octop.infra.auth.enterprise import client_for
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.utils.locale import resolve_request_locale

_INSTALL_ATTR = "_octop_jwt_auth_installed"
logger = logging.getLogger(__name__)


def install(app: Any, server: Any) -> None:
    if getattr(app, _INSTALL_ATTR, False):
        return
    setattr(app, _INSTALL_ATTR, True)

    @app.middleware("http")  # type: ignore[untyped-decorator]
    async def _jwt_auth(
        request: Request,
        call_next: Callable[[Request], Awaitable[Any]],
    ) -> Any:
        path = request.url.path
        registry = getattr(getattr(server, "app_runtime", None), "agent_registry", None)
        if (
            path.startswith("/api/")
            and getattr(registry, "application_update_pending", False)
            and not (path.startswith("/api/health") or path.startswith("/api/client-updates/"))
        ):
            error = OctopError.localized(ErrorCode.CLIENT_UPDATE_IN_PROGRESS)
            return JSONResponse(
                status_code=error.status,
                content=error.to_envelope(locale=resolve_request_locale(request)),
            )
        if not path.startswith("/api/") or is_jwt_exempt_request(request):
            return await call_next(request)

        raw = extract_raw_token(
            authorization=request.headers.get("authorization"),
            access_token=request.query_params.get("access_token"),
        )
        try:
            request.state.octop_user = authenticate_request(request, server)
            enterprise = client_for(server)
            if enterprise is not None and path != "/api/auth/logout":
                request.state.octop_user = await enterprise.authorize(request.state.octop_user)
        except OctopError as exc:
            # Middleware returns directly (skips FastAPI exception handlers).
            if exc.status >= 500:
                logger.error(
                    "OctopError %s in %s: %s",
                    exc.code.value,
                    request.url.path,
                    exc.message,
                    exc_info=exc,
                )
            locale = resolve_request_locale(request)
            return JSONResponse(status_code=exc.status, content=exc.to_envelope(locale=locale))

        # Authorization can await the company server while an update is approved.
        if getattr(registry, "application_update_pending", False) and not path.startswith(
            "/api/client-updates/"
        ):
            error = OctopError.localized(ErrorCode.CLIENT_UPDATE_IN_PROGRESS)
            return JSONResponse(
                status_code=error.status,
                content=error.to_envelope(locale=resolve_request_locale(request)),
            )
        mutation = request.method not in {"GET", "HEAD", "OPTIONS"} and not path.startswith(
            "/api/client-updates/"
        )
        if mutation:
            server._client_update_mutations = getattr(server, "_client_update_mutations", 0) + 1
        try:
            response = await call_next(request)
        finally:
            if mutation:
                server._client_update_mutations -= 1
        if raw is not None:
            try:
                renewed = maybe_sliding_renew_token(server, raw, request.state.octop_user)
            except OctopError:
                renewed = None
            if renewed:
                response.headers[ACCESS_TOKEN_RESPONSE_HEADER] = renewed
        return response
