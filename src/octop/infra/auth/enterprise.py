"""Enterprise identity grants; local files and agent execution never leave the node."""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import time
from contextlib import suppress
from contextvars import ContextVar
from dataclasses import dataclass, replace
from typing import Any

import httpx
from cryptography.fernet import InvalidToken

from octop.infra.crypto.fernet import decrypt_json, encrypt_json
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.mobile_access.service import MobileAccessService, service_for, validate_server_url
from octop.infra.users.identity import Role, User
from octop.infra.users.permissions import PERMISSIONS, user_has_permission

CLIENT_PATH = "/api/auth/enterprise"
CENTER_PATH = "/api/enterprise"
_SECRET_PURPOSE = "enterprise_identity_fernet"
_CACHE_SECONDS = 30


@dataclass
class EnterpriseSocketContext:
    user: User | None = None


CURRENT_ENTERPRISE_SOCKET: ContextVar[EnterpriseSocketContext | None] = ContextVar(
    "enterprise_socket", default=None
)


def enterprise_error(code: ErrorCode) -> OctopError:
    return OctopError.localized(code)


def verify_company_tenant(
    services: Any, users: Any, claims: dict[str, Any], binding_user_id: int | None
) -> str:
    """An authenticated installation admin pins the company through their Feishu bind."""
    tenant = claims.get("tenant_key")
    if not isinstance(tenant, str) or not tenant:
        raise enterprise_error(ErrorCode.ENTERPRISE_FEISHU_REQUIRED)
    expected = services.settings_repo.get("enterprise.tenant_key")
    if expected is None:
        actor = users.get_by_id(binding_user_id) if binding_user_id is not None else None
        if actor is None or not actor.is_admin:
            raise enterprise_error(ErrorCode.ENTERPRISE_FEISHU_REQUIRED)
        expected = services.settings_repo.set_if_missing("enterprise.tenant_key", tenant)
    if tenant != expected:
        raise enterprise_error(ErrorCode.ENTERPRISE_ACCESS_DENIED)
    return tenant


def record_company_identity(
    services: Any, user_id: int, client_id: str, subject: str, tenant: str
) -> None:
    services.settings_repo.set(
        f"enterprise.feishu.{user_id}",
        json.dumps({"client_id": client_id, "subject": subject, "tenant_key": tenant}),
    )


class EnterpriseCenter:
    """Use the existing revocable device store with an identity-only grant kind."""

    def __init__(self, server: Any) -> None:
        self.server = server

    def require_enabled(self) -> None:
        if not self.server.services.config.enterprise_center_enabled:
            raise enterprise_error(ErrorCode.ENTERPRISE_NOT_CONFIGURED)

    def require_employee(self, user: User) -> str:
        self.require_enabled()
        provider = self.server.services.sso_repo.get_by_kind("feishu")
        linked = self.server.user_manager.list_sso_identities(user.id)
        identity = next(
            (
                item
                for item in linked
                if item.kind == "feishu"
                and provider is not None
                and item.provider_id == provider.id
            ),
            None,
        )
        if (
            provider is None
            or not provider.enabled
            or not provider.client_id.strip()
            or not provider.client_secret_enc
            or identity is None
        ):
            raise enterprise_error(ErrorCode.ENTERPRISE_FEISHU_REQUIRED)
        try:
            verified = json.loads(
                self.server.services.settings_repo.get(f"enterprise.feishu.{user.id}") or "null"
            )
            tenant = self.server.services.settings_repo.get("enterprise.tenant_key")
            if not tenant or verified != {
                "client_id": provider.client_id,
                "subject": identity.subject,
                "tenant_key": tenant,
            }:
                raise ValueError
        except (ValueError, TypeError):
            raise enterprise_error(ErrorCode.ENTERPRISE_FEISHU_REQUIRED) from None
        return hashlib.sha256(f"{provider.client_id}:{identity.subject}".encode()).hexdigest()

    @property
    def devices(self) -> MobileAccessService:
        return service_for(self.server)

    async def begin(self, name: str, network_key: str) -> dict[str, Any]:
        self.require_enabled()
        return await self.devices.begin_pairing(
            name=name, platform="web", network_key=network_key, kind="enterprise"
        )

    async def inspect(self, user: User, code: str) -> dict[str, Any]:
        await asyncio.to_thread(self.require_employee, user)
        return await self.devices.inspect_pairing(user_id=user.id, code=code, kind="enterprise")

    async def approve(self, user: User, code: str) -> dict[str, Any]:
        await asyncio.to_thread(self.require_employee, user)
        return await self.devices.approve_pairing(
            user_id=user.id, code=code, scopes=["enterprise"], kind="enterprise"
        )

    async def exchange(self, secret: str, network_key: str) -> dict[str, Any]:
        self.require_enabled()
        return await self.devices.exchange_pairing(
            pairing_secret=secret, network_key=network_key, kind="enterprise"
        )

    def profile(self, token: str) -> dict[str, Any]:
        self.require_enabled()
        session = self.devices.authenticate(token)
        if session.scopes != ("enterprise",):
            raise enterprise_error(ErrorCode.ENTERPRISE_ACCESS_DENIED)
        user = self.server.user_manager.get_by_id(session.user_id)
        if user is None:
            raise enterprise_error(ErrorCode.ENTERPRISE_ACCESS_DENIED)
        subject = self.require_employee(user)
        return {
            "subject": subject,
            "display_name": user.label,
            "permissions": sorted(key for key in PERMISSIONS if user_has_permission(user, key)),
            "device_id": session.device_id,
            "expires_at": session.expires_at,
        }

    async def revoke(self, token: str) -> None:
        await asyncio.to_thread(self.profile, token)
        session = await asyncio.to_thread(self.devices.authenticate, token)
        await self.devices.revoke(user_id=session.user_id, device_id=session.device_id)


class EnterpriseClient:
    """Pull only identity and permissions. The center cannot send commands to this node."""

    def __init__(self, server: Any) -> None:
        self.server = server
        config = server.services.config
        self.services = server.services
        self.authority = validate_server_url(config.enterprise_authority_url)
        if config.enterprise_center_enabled or config.bind_host not in {
            "127.0.0.1",
            "::1",
            "localhost",
        }:
            raise ValueError(
                "enterprise clients must be separate from the center and bind to loopback"
            )
        self._pending: dict[str, dict[str, Any]] = {}
        self._cache: dict[int, tuple[float, dict[str, Any]]] = {}
        self._lock = asyncio.Lock()
        self._login_lock = asyncio.Lock()

    async def _remote(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
                response = await client.request(
                    method,
                    self.authority + path,
                    headers={"Authorization": f"Bearer {token}"} if token else {},
                    json=body,
                )
            if response.status_code in {401, 403}:
                raise enterprise_error(ErrorCode.ENTERPRISE_ACCESS_DENIED)
            response.raise_for_status()
            if response.status_code == 204:
                return {}
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError("invalid enterprise response")
            return result
        except OctopError:
            raise
        except (httpx.HTTPError, ValueError):
            # Do not include response text, credentials or private network details in errors.
            raise enterprise_error(ErrorCode.ENTERPRISE_UNAVAILABLE) from None

    async def begin(self, name: str, *, binding_user_id: int | None = None) -> dict[str, Any]:
        now = time.time()
        self._pending = {key: row for key, row in self._pending.items() if row["expires_at"] > now}
        if len(self._pending) >= 32:
            raise enterprise_error(ErrorCode.ENTERPRISE_ACCESS_DENIED)
        challenge = await self._remote("POST", CENTER_PATH + "/pairings", body={"name": name})
        try:
            credential = str(challenge["pairing_secret"])
            code = str(challenge["user_code"])
            expires = min(int(challenge["expires_at"]), int(now) + 300)
            if not 20 <= len(credential) <= 100 or expires <= now:
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise enterprise_error(ErrorCode.ENTERPRISE_UNAVAILABLE) from None
        login_id = secrets.token_urlsafe(32)
        self._pending[login_id] = {
            "secret": credential,
            "expires_at": expires,
            "next_poll": 0.0,
            "binding_user_id": binding_user_id,
        }
        return {
            "login_id": login_id,
            "user_code": code,
            "verification_uri": self.authority + "/enterprise/approve",
            "expires_at": expires,
            "interval": 3,
        }

    def _state(self, user_id: int) -> dict[str, Any]:
        raw = self.server.services.secret_repo.get(f"enterprise.identity.{user_id}")
        if raw is None:
            raise enterprise_error(ErrorCode.ENTERPRISE_LOGIN_REQUIRED)
        try:
            state = decrypt_json(self.server.services.secret_repo, _SECRET_PURPOSE, raw)
            if state.get("authority") != self.authority or not state.get("token"):
                raise ValueError
            return state
        except (InvalidToken, ValueError, TypeError):
            raise enterprise_error(ErrorCode.ENTERPRISE_LOGIN_REQUIRED) from None

    def _store_state(self, user_id: int, state: dict[str, Any]) -> None:
        from octop.infra.utils.json_file import read_json_object, write_json_atomic

        # Keep the explicitly approved company mode when a later installer has no preset.
        path = self.server.paths.config
        config = read_json_object(path) or {}
        if config.get("enterprise_authority_url") != self.authority:
            config["enterprise_authority_url"] = self.authority
            write_json_atomic(path, config)
        repo = self.services.secret_repo
        repo.set(f"enterprise.identity.{user_id}", encrypt_json(repo, _SECRET_PURPOSE, state))

    @staticmethod
    def _profile(raw: dict[str, Any], subject: str | None = None) -> dict[str, Any]:
        try:
            actual = raw["subject"]
            permissions = raw["permissions"]
            if (
                not isinstance(actual, str)
                or not actual
                or (subject is not None and subject != actual)
                or not isinstance(permissions, list)
                or not all(isinstance(key, str) for key in permissions)
                or int(raw["expires_at"]) <= time.time()
            ):
                raise ValueError
            return {**raw, "permissions": sorted(set(permissions) & PERMISSIONS.keys())}
        except (KeyError, TypeError, ValueError):
            raise enterprise_error(ErrorCode.ENTERPRISE_ACCESS_DENIED) from None

    async def poll(
        self, login_id: str, *, confirmed: bool = False
    ) -> tuple[dict[str, Any], User | None]:
        async with self._login_lock:
            row = self._pending.get(login_id)
            if row is None or row["expires_at"] <= time.time():
                self._pending.pop(login_id, None)
                return {"status": "expired"}, None
            if row["next_poll"] > time.monotonic() and not (confirmed and row.get("grant")):
                return {"status": "pending"}, None
            row["next_poll"] = time.monotonic() + 3
            result = row.get("grant")
            if result is None:
                result = await self._remote(
                    "POST",
                    CENTER_PATH + "/pairings/exchange",
                    body={"pairing_secret": row["secret"]},
                )
            if result.get("status") == "pending":
                return {"status": "pending"}, None
            token = result.get("access_token")
            if result.get("status") != "approved" or not isinstance(token, str):
                raise enterprise_error(ErrorCode.ENTERPRISE_UNAVAILABLE)
            row["grant"] = result
            profile = self._profile(
                await self._remote("GET", CENTER_PATH + "/session", token=token),
                row.get("company_subject"),
            )
            row["company_subject"] = profile["subject"]
            if row["binding_user_id"] is not None and not confirmed:
                local_user = self.server.user_manager.get_by_id(row["binding_user_id"])
                if local_user is None:
                    raise enterprise_error(ErrorCode.ENTERPRISE_LOCAL_LOGIN_REQUIRED)
                return {
                    "status": "confirm",
                    "company_name": profile.get("display_name", ""),
                    "local_name": local_user.label,
                }, None
            services = self.server.services
            provider = await asyncio.to_thread(
                services.sso_repo.upsert_by_kind,
                "enterprise",
                enabled=False,
                display_name="Enterprise",
                issuer=self.authority,
                client_id="octop-desktop",
                client_secret_enc=None,
                scopes="",
                dashboard_origin=None,
            )
            subject = hashlib.sha256(self.authority.encode()).hexdigest() + ":" + profile["subject"]
            if row["binding_user_id"] is not None:
                user = await self.server.user_manager.bind_sso_identity(
                    user_id=row["binding_user_id"],
                    provider_id=provider.id,
                    subject=subject,
                    claims={"name": profile.get("display_name")},
                )
            else:
                user = await self.server.user_manager.resolve_or_create_sso_user(
                    provider_id=provider.id,
                    subject=subject,
                    claims={"name": profile.get("display_name")},
                )
            state = {"authority": self.authority, "token": token, "subject": profile["subject"]}
            async with self._lock:
                previous_token = None
                with suppress(OctopError):
                    previous_token = (await asyncio.to_thread(self._state, user.id))["token"]
                await asyncio.to_thread(self._store_state, user.id, state)
                self._pending.pop(login_id, None)
                self._cache[user.id] = (
                    time.monotonic() + min(_CACHE_SECONDS, profile["expires_at"] - time.time()),
                    profile,
                )
            if previous_token and previous_token != token:
                with suppress(OctopError):
                    await self._remote(
                        "POST", CENTER_PATH + "/session/revoke", token=previous_token
                    )
            return {"status": "approved"}, replace(
                user, role=Role.USER, permissions=profile["permissions"]
            )

    async def authorize(self, user: User, *, force: bool = False) -> User:
        async with self._lock:
            cached = self._cache.get(user.id)
            if not force and cached is not None and cached[0] > time.monotonic():
                profile = cached[1]
            else:
                state = await asyncio.to_thread(self._state, user.id)
                try:
                    profile = self._profile(
                        await self._remote("GET", CENTER_PATH + "/session", token=state["token"]),
                        state["subject"],
                    )
                except OctopError:
                    self._cache.pop(user.id, None)
                    raise
                deadline = min(_CACHE_SECONDS, max(0, profile["expires_at"] - time.time()))
                self._cache[user.id] = (time.monotonic() + deadline, profile)
            return replace(user, role=Role.USER, permissions=list(profile["permissions"]))

    async def authorize_id(self, user_id: int) -> None:
        manager = self.server.user_manager
        user = manager.get_by_id(user_id) if manager is not None else None
        if user is None:
            raise enterprise_error(ErrorCode.ENTERPRISE_ACCESS_DENIED)
        await self.authorize(user, force=True)

    async def logout(self, user_id: int) -> None:
        async with self._lock:
            try:
                state = await asyncio.to_thread(self._state, user_id)
                await self._remote("POST", CENTER_PATH + "/session/revoke", token=state["token"])
            except OctopError:
                pass
            finally:
                self._cache.pop(user_id, None)
                await asyncio.to_thread(
                    self.services.secret_repo.delete, f"enterprise.identity.{user_id}"
                )


def center_for(server: Any) -> EnterpriseCenter:
    return EnterpriseCenter(server)


def client_for(server: Any) -> EnterpriseClient | None:
    services = getattr(server, "services", None)
    if services is None or not getattr(
        getattr(services, "config", None), "enterprise_authority_url", ""
    ):
        return None
    client = getattr(server, "_enterprise_client", None)
    if client is None or client.services is not services:
        client = EnterpriseClient(server)
        server._enterprise_client = client
    return client


def has_local_password_account(server: Any) -> bool:
    return any(row.password_hash for row in server.services.user_repo.list(include_disabled=False))
