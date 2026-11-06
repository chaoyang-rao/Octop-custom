"""Lock down all non-/setup endpoints while no users exist.

Returns ``503 {"setup_required": true}`` so the SPA can hard-redirect
to ``/setup``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from octop.infra.errors import ErrorCode, OctopError
from octop.infra.utils.locale import resolve_request_locale

_OPEN_PREFIXES = (
    "/api/setup/",
    "/api/health/",
)


def install(app: Any, server: Any) -> None:
    @app.middleware("http")  # type: ignore[untyped-decorator]
    async def _lockdown(
        request: Request,
        call_next: Callable[[Request], Awaitable[Any]],
    ) -> Any:
        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)
        cfg = server.services.config if server.services else getattr(server, "config", None)
        if (
            cfg
            and getattr(cfg, "enterprise_authority_url", "")
            and path.startswith("/api/setup/")
            and path != "/api/setup/status"
        ):
            error = OctopError.localized(
                ErrorCode.ENTERPRISE_ACCESS_DENIED, resolve_request_locale(request)
            )
            return JSONResponse(status_code=403, content=error.to_envelope())
        open_exact = ["/api/health", "/api/auth/enterprise/status"]
        if cfg and getattr(cfg, "enterprise_authority_url", ""):
            open_exact.extend(("/api/auth/enterprise/start", "/api/auth/enterprise/poll"))
        if cfg and cfg.enable_api_docs:
            open_exact.extend(("/api/docs", "/api/openapi.json"))
        if path in open_exact or any(path.startswith(p) for p in _OPEN_PREFIXES):
            return await call_next(request)
        if server.user_manager is None or server.user_manager.count() == 0:
            return JSONResponse(
                status_code=503,
                content={"setup_required": True},
            )
        return await call_next(request)
