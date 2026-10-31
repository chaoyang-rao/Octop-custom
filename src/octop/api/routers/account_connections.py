"""Human account settings and single-use vault approvals (never secret reads)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field, SecretStr

from octop.api.deps import current_user, get_server, require_permission
from octop.infra.connectors.accounts import AccountConnectionError, AccountConnectionService
from octop.infra.connectors.accounts.oauth_clients import (
    delete_registered_oauth_client,
    load_registered_oauth_client,
    registered_oauth_client_preview,
    save_registered_oauth_client,
)
from octop.infra.utils.locale import resolve_request_locale


class _AccountRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await original(request)
            except AccountConnectionError as exc:
                return JSONResponse(
                    status_code=exc.status, content={"message": str(exc), "reason": exc.code}
                )
            except (RequestValidationError, ValueError):
                # Never echo invalid credential input or upstream CLI/OAuth details.
                invalid_error = AccountConnectionError(
                    "invalid_input", locale=resolve_request_locale(request)
                )
                return JSONResponse(
                    status_code=422,
                    content={"message": str(invalid_error), "reason": invalid_error.code},
                )

        return handler


router = APIRouter(
    route_class=_AccountRoute, dependencies=[Depends(require_permission("connectors"))]
)


class VaultConnectionBody(BaseModel):
    provider: Literal["onepassword", "bitwarden"]
    name: str = Field(min_length=1, max_length=100)
    allowed_hosts: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="Exact public HTTPS hosts approved for secret delivery; empty denies delivery.",
    )
    service_account_token: SecretStr | None = Field(
        default=None,
        description="1Password service-account token; encrypted at rest and never returned.",
    )


class VaultConnectionView(BaseModel):
    id: str
    provider: str
    name: str
    allowed_hosts: list[str]
    ready: bool = Field(
        description="Credentials are configured/unlocked; this does not prove vendor access."
    )
    profile_path: str | None = None


class UnlockBody(BaseModel):
    session: SecretStr = Field(
        description="Bitwarden unlock key for this isolated CLI profile; held in server memory for one hour only."
    )


class ReferenceBody(BaseModel):
    connection_id: str
    item_id: str
    vault_id: str = ""
    field_name: str = "password"
    label: str = Field(default="", max_length=200)


class ReferenceView(BaseModel):
    reference: str
    label: str
    field_name: str
    connection_id: str | None = None


class ItemView(BaseModel):
    item_id: str
    title: str
    vault_id: str


class UseRequestBody(BaseModel):
    reference: str
    url: str = Field(max_length=4096)
    purpose: str = Field(min_length=1, max_length=500)
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "GET"
    header_name: Literal["Authorization", "X-API-Key", "Api-Key"] = "Authorization"
    prefix: str = Field(default="Bearer ", max_length=32)
    body: dict[str, Any] | None = None


class UseRequestView(BaseModel):
    request_id: str
    reference: str
    url: str
    method: str
    purpose: str
    expires_at: int
    state: str
    header_name: str | None = None
    prefix: str | None = None
    body: dict[str, Any] | None = None
    created_at: int | None = None
    approval_token: str | None = Field(
        default=None, description="Human UI only; never included in agent tool output."
    )
    status_code: int | None = None


class ApprovalBody(BaseModel):
    approval_token: SecretStr


class DeliveryView(BaseModel):
    request_id: str
    state: str
    status_code: int


class OkView(BaseModel):
    ok: bool = True


class OAuthAppBody(BaseModel):
    client_id: str = Field(min_length=1, max_length=1024)
    client_secret: SecretStr | None = None
    scopes: str | None = Field(default=None, max_length=4096)


class OAuthAppView(BaseModel):
    configured: bool
    client_id: str
    secret_configured: bool
    scopes: str


def _service(request: Request, server: Any) -> AccountConnectionService:
    return AccountConnectionService(
        settings_repo=server.services.settings_repo,
        secret_repo=server.services.secret_repo,
        paths=server.services.paths,
        locale=resolve_request_locale(request),
    )


@router.get(
    "/account-connections/vaults",
    summary="List my vault connections without credentials",
    response_model=list[VaultConnectionView],
)
async def list_vaults(
    request: Request, user: Any = Depends(current_user), server: Any = Depends(get_server)
) -> Any:
    return await _service(request, server).list_connections(user.id)


@router.post(
    "/account-connections/vaults",
    summary="Add an isolated vault connection",
    response_model=VaultConnectionView,
)
async def create_vault(
    body: VaultConnectionBody,
    request: Request,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    return await _service(request, server).save_connection(
        user.id,
        provider=body.provider,
        name=body.name,
        allowed_hosts=body.allowed_hosts,
        service_account_token=body.service_account_token.get_secret_value()
        if body.service_account_token
        else "",
    )


@router.put(
    "/account-connections/vaults/{connection_id}",
    summary="Update my vault connection",
    response_model=VaultConnectionView,
)
async def update_vault(
    connection_id: str,
    body: VaultConnectionBody,
    request: Request,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    return await _service(request, server).save_connection(
        user.id,
        connection_id=connection_id,
        provider=body.provider,
        name=body.name,
        allowed_hosts=body.allowed_hosts,
        service_account_token=body.service_account_token.get_secret_value()
        if body.service_account_token
        else "",
    )


@router.delete(
    "/account-connections/vaults/{connection_id}",
    summary="Disconnect my vault without deleting vendor data",
    response_model=OkView,
)
async def delete_vault(
    connection_id: str,
    request: Request,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    await _service(request, server).delete_connection(user.id, connection_id)
    return {"ok": True}


@router.post(
    "/account-connections/vaults/{connection_id}/unlock",
    summary="Set a memory-only Bitwarden session",
    response_model=OkView,
)
async def unlock_vault(
    connection_id: str,
    body: UnlockBody,
    request: Request,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    await _service(request, server).unlock_bitwarden(
        user.id, connection_id, body.session.get_secret_value()
    )
    return {"ok": True}


@router.post(
    "/account-connections/vaults/{connection_id}/lock",
    summary="Forget this connection's Bitwarden session",
    response_model=OkView,
)
async def lock_vault(
    connection_id: str,
    request: Request,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    await _service(request, server).lock_connection(user.id, connection_id)
    return {"ok": True}


@router.get(
    "/account-connections/vaults/{connection_id}/items",
    summary="List item metadata without field values",
    response_model=list[ItemView],
)
async def list_items(
    connection_id: str,
    request: Request,
    offset: int = Query(default=0, ge=0, le=100000),
    search: str = Query(default="", max_length=200),
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    return await _service(request, server).list_items(
        user.id, connection_id, offset=offset, search=search
    )


@router.get(
    "/account-connections/references",
    summary="List my opaque vault references",
    response_model=list[ReferenceView],
)
async def list_references(
    request: Request, user: Any = Depends(current_user), server: Any = Depends(get_server)
) -> Any:
    return await _service(request, server).list_references(user.id)


@router.post(
    "/account-connections/references",
    summary="Create a reference without reading a secret",
    response_model=ReferenceView,
)
async def create_reference(
    body: ReferenceBody,
    request: Request,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    return await _service(request, server).create_reference(user.id, **body.model_dump())


@router.get(
    "/account-connections/requests",
    summary="Review secret-use requests and single-use approval tokens",
    response_model=list[UseRequestView],
)
async def list_requests(
    request: Request, user: Any = Depends(current_user), server: Any = Depends(get_server)
) -> Any:
    return await _service(request, server).list_requests(user.id)


@router.post(
    "/account-connections/requests",
    summary="Request a precisely scoped use; no secret is read",
    response_model=UseRequestView,
)
async def request_use(
    body: UseRequestBody,
    request: Request,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    return await _service(request, server).request_use(user.id, **body.model_dump())


@router.post(
    "/account-connections/requests/{request_id}/approve",
    summary="Approve and consume exactly one secret delivery",
    description="Consumes the request before reading the vault. Sends the secret only to the reviewed HTTPS action. No response body, secret, redirect target or headers are returned. A failed or interrupted request cannot be replayed.",
    response_model=DeliveryView,
)
async def approve_use(
    request_id: str,
    body: ApprovalBody,
    request: Request,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    return await _service(request, server).approve_use(
        user.id, request_id, body.approval_token.get_secret_value()
    )


@router.post(
    "/account-connections/requests/{request_id}/reject",
    summary="Reject a pending secret delivery",
    response_model=OkView,
)
async def reject_use(
    request_id: str,
    request: Request,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    await _service(request, server).reject_use(user.id, request_id)
    return {"ok": True}


@router.get(
    "/account-connections/oauth-apps/{kind}",
    summary="Inspect my OAuth app registration without its secret",
    response_model=OAuthAppView,
)
async def get_oauth_app(
    kind: str, user: Any = Depends(current_user), server: Any = Depends(get_server)
) -> Any:
    client = await asyncio.to_thread(
        load_registered_oauth_client,
        settings_repo=server.services.settings_repo,
        secret_repo=server.services.secret_repo,
        user_id=user.id,
        kind=kind,
    )
    return registered_oauth_client_preview(client)


@router.put(
    "/account-connections/oauth-apps/{kind}",
    summary="Register my own OAuth app for a connector",
    response_model=OAuthAppView,
)
async def save_oauth_app(
    kind: str,
    body: OAuthAppBody,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    existing = await asyncio.to_thread(
        load_registered_oauth_client,
        settings_repo=server.services.settings_repo,
        secret_repo=server.services.secret_repo,
        user_id=user.id,
        kind=kind,
    )
    secret = (
        body.client_secret.get_secret_value()
        if body.client_secret
        else (
            str(existing.get("client_secret") or "")
            if existing and existing.get("client_id") == body.client_id.strip()
            else ""
        )
    )
    await asyncio.to_thread(
        save_registered_oauth_client,
        settings_repo=server.services.settings_repo,
        secret_repo=server.services.secret_repo,
        user_id=user.id,
        kind=kind,
        client_id=body.client_id,
        client_secret=secret,
        scopes=body.scopes,
    )
    return registered_oauth_client_preview(
        {"client_id": body.client_id, "client_secret": secret, "scope": body.scopes or ""}
    )


@router.delete(
    "/account-connections/oauth-apps/{kind}",
    summary="Forget my registered OAuth app",
    response_model=OkView,
)
async def delete_oauth_app(
    kind: str, user: Any = Depends(current_user), server: Any = Depends(get_server)
) -> Any:
    await asyncio.to_thread(
        delete_registered_oauth_client,
        settings_repo=server.services.settings_repo,
        user_id=user.id,
        kind=kind,
    )
    return {"ok": True}
