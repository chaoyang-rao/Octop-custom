"""Member-scoped MCP grants and streaming proxy for company-managed services."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx

from octop.infra.auth.enterprise import center_for
from octop.infra.connectors.enterprise_account_auth import BusinessAccountAuth
from octop.infra.connectors.enterprise_catalog import (
    CatalogEntry,
    EnterpriseMcpCatalog,
    entry_fingerprint,
)
from octop.infra.connectors.enterprise_mcp_protocol import GATEWAY_PATH, AuthMode, is_gateway_entry
from octop.infra.connectors.enterprise_mcp_store import authorization_headers
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.users.identity import User
from octop.infra.users.permissions import user_has_permission
from octop.infra.utils.ssrf_guard import public_http_transport

TARGETS_KEY = "enterprise.mcp.gateway.targets.v1"
SUPPORTED = frozenset({"aftersales-quality", "quota-workbench", "negative-profit"})
_GRANT_PREFIX = "enterprise.mcp.gateway.grant."
_TTL = 30 * 86400


def _denied() -> OctopError:
    return OctopError.localized(ErrorCode.ENTERPRISE_ACCESS_DENIED)


@dataclass
class GatewayReply:
    status: int
    headers: dict[str, str]
    body: AsyncIterator[bytes]


@dataclass
class _Session:
    grant: str
    entry_id: str
    upstream_id: str
    headers: dict[str, str]
    touched: float
    connection: str = ""


class EnterpriseMcpGateway:
    def __init__(self, server: Any) -> None:
        self.server = server
        self.settings = server.services.settings_repo
        self.secrets = server.services.secret_repo
        self.catalog = EnterpriseMcpCatalog(server)
        self._sessions: dict[str, _Session] = {}
        self._delegates: dict[tuple[int, str, str], tuple[float, dict[str, str]]] = {}
        self._locks: dict[tuple[int, str, str], asyncio.Lock] = {}

    def targets(self) -> dict[str, CatalogEntry]:
        raw = self.settings.get(TARGETS_KEY)
        return {
            entry.entry_id: entry
            for value in json.loads(raw or "[]")
            if (entry := CatalogEntry.model_validate(value))
        }

    def configure(self, user: User, entries: list[CatalogEntry]) -> None:
        self.catalog._admin(user)
        if len({e.entry_id for e in entries}) != len(entries):
            raise _denied()
        origin = os.environ.get("OCTOP_MCP_ACCOUNT_ORIGIN", "").rstrip("/")
        if not origin.startswith("https://"):
            raise _denied()
        for entry in entries:
            expected = {
                "aftersales-quality": "bearer",
                "quota-workbench": "basic",
                "negative-profit": "none",
            }
            if entry.entry_id not in SUPPORTED or entry.auth_kind != expected[entry.entry_id]:
                raise _denied()
            if GATEWAY_PATH in entry.url:
                raise _denied()
            if entry.entry_id != "negative-profit":
                path = "aftersales" if entry.entry_id == "aftersales-quality" else "workbench"
                if entry.url != origin + "/team-mcp/" + path:
                    raise _denied()
        self.settings.set(TARGETS_KEY, json.dumps([e.model_dump(mode="json") for e in entries]))
        self.server.services.audit_repo.write(
            actor=user.username,
            action="enterprise.mcp.gateway.configure",
            target=TARGETS_KEY,
            payload=json.dumps([e.entry_id for e in entries]),
        )

    def _visible(self, user: User, entry_id: str) -> tuple[str, CatalogEntry, CatalogEntry]:
        row = self.server.services.user_repo.get(user.id)
        owner = self.server.user_manager.get_by_id(user.id)
        from octop.infra.enterprise_resources.member_access import access_for

        access = access_for(self.server)
        permitted = (
            access.allows_mcp(user, entry_id)
            if access.configured
            else bool(owner and user_has_permission(owner, "connector_enabled"))
        )
        if row is None or row.disabled or owner is None or not permitted:
            raise _denied()
        subject = center_for(self.server).require_employee(user)
        entry = next(
            (
                e
                for e in self.catalog.snapshot_for(user).entries
                if e.entry_id == entry_id and e.enabled
            ),
            None,
        )
        origin = os.environ.get("OCTOP_MCP_ACCOUNT_ORIGIN", "")
        target = self.targets().get(entry_id)
        if (
            entry is None
            or not is_gateway_entry(entry, origin)
            or target is None
            or not target.enabled
        ):
            raise _denied()
        return subject, target, entry

    async def choices(self, user: User, entry_id: str) -> dict[str, Any]:
        await asyncio.to_thread(self._visible, user, entry_id)
        if entry_id == "negative-profit":
            return {"identity_name": user.label, "accounts": []}
        result = await BusinessAccountAuth(self.server)._helper(user, entry_id, "list")
        return {
            "identity_name": user.label,
            "accounts": [
                {"account_id": str(r["account_id"]), "label": str(r["label"])}
                for r in result.get("accounts", [])
            ],
        }

    async def issue(
        self,
        user: User,
        entry_id: str,
        auth_mode: AuthMode,
        account_id: str = "",
        expected_fingerprint: str | None = None,
    ) -> dict[str, str]:
        subject, target, entry = await asyncio.to_thread(self._visible, user, entry_id)
        if expected_fingerprint is not None and expected_fingerprint != entry_fingerprint(entry):
            raise OctopError.localized(ErrorCode.ENTERPRISE_MCP_CATALOG_CONFLICT)
        if auth_mode not in {"none", "bearer", "basic"}:
            raise _denied()
        from octop.infra.enterprise_resources.member_access import access_for

        managed = await asyncio.to_thread(lambda: access_for(self.server).configured)
        if managed:
            account_id = ""
        if entry_id != "negative-profit" and not managed:
            choices = (await self.choices(user, entry_id))["accounts"]
            if not account_id and len(choices) == 1:
                account_id = choices[0]["account_id"]
            if not any(r["account_id"] == account_id for r in choices):
                raise _denied()
        token = "ocm_" + secrets.token_urlsafe(32)
        username = "mcp_" + str(user.id)
        expiry = int(time.time()) + _TTL
        record = {
            "user_id": user.id,
            "entry_id": entry_id,
            "auth_mode": auth_mode,
            "username": username,
            "expires_at": expiry,
            "subject": subject,
            "target": entry_fingerprint(target),
            "definition": entry_fingerprint(entry),
            "account_id": account_id,
        }
        await asyncio.to_thread(
            self.secrets.set,
            _GRANT_PREFIX + hashlib.sha256(token.encode()).hexdigest(),
            json.dumps(record).encode(),
        )
        await asyncio.to_thread(
            self.server.services.audit_repo.write,
            actor=user.username,
            action="enterprise.mcp.gateway.authorize",
            target=entry_id,
            payload=auth_mode,
        )
        return {
            "auth_mode": auth_mode,
            "expires_at": str(expiry),
            **(
                {"username": username, "password": token}
                if auth_mode == "basic"
                else {"token": token}
            ),
        }

    def authenticate(
        self, entry_id: str, authorization: str
    ) -> tuple[User, CatalogEntry, dict[str, Any], str]:
        if len(authorization) > 20000:
            raise _denied()
        scheme, _, value = authorization.partition(" ")
        username = ""
        if scheme.lower() == "bearer":
            token = value
        elif scheme.lower() == "basic":
            try:
                username, token = base64.b64decode(value, validate=True).decode().split(":", 1)
            except (ValueError, UnicodeError):
                raise _denied() from None
        else:
            raise _denied()
        digest = hashlib.sha256(token.encode()).hexdigest()
        raw = self.secrets.get(_GRANT_PREFIX + digest)
        if raw is None:
            raise _denied()
        record = json.loads(raw)
        if record["entry_id"] != entry_id or record["expires_at"] <= time.time():
            raise _denied()
        basic = record["auth_mode"] == "basic"
        if (
            basic != (scheme.lower() == "basic")
            or basic
            and not hmac.compare_digest(username, record["username"])
        ):
            raise _denied()
        user = self.server.user_manager.get_by_id(record["user_id"])
        if user is None:
            raise _denied()
        subject, target, entry = self._visible(user, entry_id)
        if (
            subject != record["subject"]
            or entry_fingerprint(target) != record["target"]
            or entry_fingerprint(entry) != record["definition"]
        ):
            raise _denied()
        return user, target, record, digest

    async def _upstream_headers(
        self, user: User, target: CatalogEntry, record: dict[str, Any]
    ) -> dict[str, str]:
        from octop.infra.enterprise_resources.member_access import access_for

        access = access_for(self.server)
        if await asyncio.to_thread(lambda: access.configured):
            return await access.upstream_headers(target)
        if target.auth_kind == "none":
            return {}
        key = (user.id, target.entry_id, record["account_id"])
        async with self._locks.setdefault(key, asyncio.Lock()):
            cached = self._delegates.get(key)
            if cached and cached[0] > time.monotonic():
                return cached[1]
            credentials = await BusinessAccountAuth(self.server)._helper(
                user, target.entry_id, "issue", record["account_id"]
            )
            headers = authorization_headers(target, credentials)
            self._delegates[key] = (time.monotonic() + 300, headers)
            return headers

    async def forward(
        self, entry_id: str, method: str, headers: dict[str, str], body: bytes
    ) -> GatewayReply:
        user, target, record, digest = await asyncio.to_thread(
            self.authenticate, entry_id, headers.get("authorization", "")
        )
        now = time.monotonic()
        self._sessions = {
            key: value for key, value in self._sessions.items() if now - value.touched < 1800
        }
        session_id = headers.get("mcp-session-id")
        session = self._sessions.get(session_id or "")
        from octop.infra.enterprise_resources.member_access import access_for

        access = access_for(self.server)
        connection = (
            await asyncio.to_thread(access.connection_fingerprint, entry_id)
            if await asyncio.to_thread(lambda: access.configured)
            else ""
        )
        if session_id and session is None:
            raise OctopError.localized(ErrorCode.NOT_FOUND)
        if session is not None and (session.grant != digest or session.entry_id != entry_id):
            raise _denied()
        if session is not None and session.connection != connection:
            self._sessions.pop(str(session_id), None)
            raise OctopError.localized(ErrorCode.NOT_FOUND)
        if session is not None:
            session.touched = now
            upstream_headers = dict(session.headers)
            upstream_headers["Mcp-Session-Id"] = session.upstream_id
        else:
            upstream_headers = dict(await self._upstream_headers(user, target, record))
        for name in ("accept", "content-type", "mcp-protocol-version", "last-event-id"):
            if name in headers:
                upstream_headers[name] = headers[name]
        transport = await public_http_transport(target.url)
        client = httpx.AsyncClient(
            transport=transport,
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(120, connect=10),
        )
        try:
            response = await client.send(
                client.build_request(method, target.url, headers=upstream_headers, content=body),
                stream=True,
            )
        except httpx.HTTPError:
            await client.aclose()
            raise OctopError.localized(ErrorCode.ENTERPRISE_UNAVAILABLE) from None
        try:
            payload = json.loads(body) if body else None
        except ValueError:
            payload = None
        calls = payload if isinstance(payload, list) else [payload]
        tool_names = []
        for call in calls:
            if not isinstance(call, dict) or call.get("method") != "tools/call":
                continue
            params = call.get("params")
            tool_name = params.get("name") if isinstance(params, dict) else None
            tool_names.append(
                tool_name
                if isinstance(tool_name, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", tool_name)
                else "invalid-tool-name"
            )
        if tool_names:
            await asyncio.to_thread(
                self.server.services.audit_repo.write,
                actor=user.username,
                action="enterprise.mcp.gateway.call",
                target=entry_id,
                payload=json.dumps(
                    {
                        "tools": tool_names[:32],
                        "count": len(tool_names),
                        "transport_status": response.status_code,
                    }
                ),
            )
        if response.status_code in {401, 403} or 300 <= response.status_code < 400:
            self._delegates.pop((user.id, target.entry_id, record["account_id"]), None)
            if await asyncio.to_thread(lambda: access.configured):
                await asyncio.to_thread(self.secrets.delete, "enterprise.mcp.service." + entry_id)
            if session_id:
                self._sessions.pop(session_id, None)
            await response.aclose()
            await client.aclose()
            raise OctopError.localized(ErrorCode.ENTERPRISE_UNAVAILABLE)
        outgoing = {
            name: response.headers[name]
            for name in ("content-type", "mcp-protocol-version")
            if name in response.headers
        }
        outgoing["Cache-Control"] = "no-store"
        upstream_id = response.headers.get("mcp-session-id")
        if upstream_id:
            if session is None:
                if len(self._sessions) >= 10000:
                    await response.aclose()
                    await client.aclose()
                    raise OctopError.localized(ErrorCode.ENTERPRISE_UNAVAILABLE)
                session_id = secrets.token_urlsafe(32)
                self._sessions[session_id] = _Session(
                    digest, entry_id, upstream_id, upstream_headers, now, connection
                )
            outgoing["Mcp-Session-Id"] = str(session_id)
        if method == "DELETE" and session_id and response.is_success:
            self._sessions.pop(session_id, None)

        async def stream() -> AsyncIterator[bytes]:
            try:
                async for chunk in response.aiter_bytes():
                    yield chunk
            finally:
                await response.aclose()
                await client.aclose()

        return GatewayReply(response.status_code, outgoing, stream())


def gateway_for(server: Any) -> EnterpriseMcpGateway:
    service = getattr(server, "_enterprise_mcp_gateway", None)
    if service is None:
        service = EnterpriseMcpGateway(server)
        server._enterprise_mcp_gateway = service
    return service
