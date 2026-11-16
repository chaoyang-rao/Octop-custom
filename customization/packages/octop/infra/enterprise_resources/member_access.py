"""Super-administrator member entitlements and server-owned read-only MCP connections."""

from __future__ import annotations

import asyncio
import time
from contextlib import suppress
from typing import Any, Literal, cast

from pydantic import Field

from octop.infra.auth.enterprise import center_for
from octop.infra.crypto.fernet import decrypt_json, encrypt_json
from octop.infra.enterprise_resources.models import StrictModel, canonical, digest
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.users.identity import User

ACCESS_KEY = "enterprise.member_access.v1"
McpId = Literal["aftersales-quality", "quota-workbench", "negative-profit"]
MCP_IDS: tuple[McpId, ...] = ("aftersales-quality", "quota-workbench", "negative-profit")
_PURPOSE = "enterprise_managed_mcp_fernet"


class MemberSelection(StrictModel):
    user_id: int = Field(gt=0)
    mcp_ids: list[McpId] = Field(default_factory=list, max_length=3)
    companion: bool = False


class MemberAccessStatus(StrictModel):
    configured: bool
    revision: int = Field(ge=0)
    mcp_ids: list[McpId]
    companion: bool


class MemberGrant(MemberSelection):
    identity: str = Field(pattern=r"^[0-9a-f]{64}$")


class ServiceConnection(StrictModel):
    owner_user_id: int = Field(gt=0)
    owner_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    account_id: str = Field(min_length=1, max_length=64)


class AccessDocument(StrictModel):
    schema_version: Literal[1] = 1
    revision: int = Field(default=0, ge=0)
    members: list[MemberGrant] = Field(default_factory=list, max_length=10000)
    connections: dict[McpId, ServiceConnection] = Field(default_factory=dict)


class MemberAccess:
    def __init__(self, server: Any) -> None:
        self.server = server
        self.settings = server.services.settings_repo
        self.secrets = server.services.secret_repo
        self._locks: dict[str, asyncio.Lock] = {}

    @property
    def configured(self) -> bool:
        return self.settings.get(ACCESS_KEY) is not None

    def ensure_default(self) -> None:
        self.settings.compare_and_set(
            ACCESS_KEY, None, canonical(AccessDocument().model_dump(mode="json"))
        )

    def _read(self) -> tuple[str | None, AccessDocument]:
        raw = self.settings.get(ACCESS_KEY)
        try:
            return raw, AccessDocument.model_validate_json(raw) if raw else AccessDocument()
        except ValueError:
            raise OctopError.localized(ErrorCode.ENTERPRISE_ACCESS_POLICY_INVALID) from None

    def _admin(self, user: User) -> None:
        from octop.infra.connectors.enterprise_catalog import EnterpriseMcpCatalog

        EnterpriseMcpCatalog(self.server)._admin(user)

    def _identity(self, user: User) -> str:
        row = self.server.services.user_repo.get(user.id)
        if row is None or row.disabled:
            raise OctopError.localized(ErrorCode.ENTERPRISE_ACCESS_DENIED)
        return center_for(self.server).require_employee(user)

    def status(self, user: User) -> dict[str, Any]:
        identity = self._identity(user)
        raw, document = self._read()
        if raw is None:
            return {"configured": False, "revision": 0, "mcp_ids": list(MCP_IDS), "companion": True}
        grant = next(
            (g for g in document.members if g.user_id == user.id and g.identity == identity), None
        )
        return {
            "configured": True,
            "revision": document.revision,
            "mcp_ids": list(grant.mcp_ids) if grant else [],
            "companion": bool(grant and grant.companion),
        }

    def allows_mcp(self, user: User, entry_id: str) -> bool:
        return entry_id in self.status(user)["mcp_ids"]

    def allows_companion(self, user: User) -> bool:
        return bool(self.status(user)["companion"])

    def connection_fingerprint(self, entry_id: str) -> str:
        _, document = self._read()
        reference = document.connections.get(cast(McpId, entry_id))
        return digest(canonical(reference.model_dump() if reference else {"entry_id": entry_id}))

    def admin(self, user: User) -> dict[str, Any]:
        self._admin(user)
        raw, document = self._read()
        grants = {g.user_id: g for g in document.members}
        members = []
        for row in self.server.services.user_repo.list(include_disabled=True):
            member = self.server.user_manager.get_by_id(row.id)
            identity = None
            if member is not None:
                with suppress(OctopError):
                    identity = self._identity(member)
            grant = grants.get(row.id)
            current = bool(grant and identity == grant.identity)
            members.append(
                {
                    "user_id": row.id,
                    "username": row.username,
                    "display_name": row.display_name or row.username,
                    "disabled": row.disabled,
                    "verified": bool(identity),
                    "mcp_ids": list(grant.mcp_ids) if current and grant else [],
                    "companion": bool(current and grant and grant.companion),
                }
            )
        services = []
        for entry_id in MCP_IDS:
            connection = document.connections.get(entry_id)
            owner = (
                self.server.user_manager.get_by_id(connection.owner_user_id) if connection else None
            )
            services.append(
                {
                    "entry_id": entry_id,
                    "configured": entry_id == "negative-profit" or bool(connection and owner),
                    "owner_name": owner.label if owner else None,
                }
            )
        return {
            "etag": digest(raw or ""),
            "configured": raw is not None,
            "revision": document.revision,
            "members": members,
            "services": services,
        }

    def save(
        self, user: User, selections: list[MemberSelection], expected_etag: str
    ) -> dict[str, Any]:
        self._admin(user)
        raw, document = self._read()
        if digest(raw or "") != expected_etag:
            raise OctopError.localized(ErrorCode.ENTERPRISE_ACCESS_POLICY_CONFLICT)
        if len({row.user_id for row in selections}) != len(selections):
            raise OctopError.localized(ErrorCode.ENTERPRISE_ACCESS_POLICY_INVALID)
        grants = []
        for row in selections:
            if not row.mcp_ids and not row.companion:
                continue
            member = self.server.user_manager.get_by_id(row.user_id)
            if member is None:
                raise OctopError.localized(ErrorCode.ENTERPRISE_ACCESS_POLICY_INVALID)
            identity = self._identity(member)
            grants.append(MemberGrant(**row.model_dump(), identity=identity))
        updated = document.model_copy(update={"members": grants, "revision": document.revision + 1})
        serialized = canonical(updated.model_dump(mode="json"))
        if not self.settings.compare_and_set(ACCESS_KEY, raw, serialized):
            raise OctopError.localized(ErrorCode.ENTERPRISE_ACCESS_POLICY_CONFLICT)
        self.server.services.audit_repo.write(
            actor=user.username,
            action="enterprise.member_access.save",
            target=ACCESS_KEY,
            payload=canonical(
                {
                    "before": [g.model_dump(exclude={"identity"}) for g in document.members],
                    "after": [g.model_dump(exclude={"identity"}) for g in grants],
                }
            ),
        )
        return self.admin(user)

    async def connection_choices(self, user: User, entry_id: str) -> dict[str, Any]:
        await asyncio.to_thread(self._admin, user)
        if entry_id not in {"aftersales-quality", "quota-workbench"}:
            raise OctopError.localized(ErrorCode.ENTERPRISE_ACCESS_POLICY_INVALID)
        from octop.infra.connectors.enterprise_account_auth import BusinessAccountAuth

        result = await BusinessAccountAuth(self.server)._helper(user, entry_id, "list")
        return {
            "identity_name": user.label,
            "accounts": [
                {"account_id": str(r["account_id"]), "label": str(r["label"])}
                for r in result.get("accounts", [])
            ],
        }

    async def connect_service(
        self, user: User, entry_id: str, account_id: str, expected_etag: str
    ) -> dict[str, Any]:
        choices = await self.connection_choices(user, entry_id)
        if not any(r["account_id"] == account_id for r in choices["accounts"]):
            raise OctopError.localized(ErrorCode.ENTERPRISE_ACCESS_DENIED)
        identity = await asyncio.to_thread(self._identity, user)

        def save_reference() -> dict[str, Any]:
            raw, document = self._read()
            if digest(raw or "") != expected_etag:
                raise OctopError.localized(ErrorCode.ENTERPRISE_ACCESS_POLICY_CONFLICT)
            connections = {
                **document.connections,
                cast(McpId, entry_id): ServiceConnection(
                    owner_user_id=user.id, owner_identity=identity, account_id=account_id
                ),
            }
            updated = document.model_copy(
                update={"connections": connections, "revision": document.revision + 1}
            )
            if not self.settings.compare_and_set(
                ACCESS_KEY, raw, canonical(updated.model_dump(mode="json"))
            ):
                raise OctopError.localized(ErrorCode.ENTERPRISE_ACCESS_POLICY_CONFLICT)
            self.secrets.delete("enterprise.mcp.service." + entry_id)
            self.server.services.audit_repo.write(
                actor=user.username,
                action="enterprise.member_access.service",
                target=entry_id,
                payload=canonical({"owner_user_id": user.id, "account_id": account_id}),
            )
            return self.admin(user)

        return await asyncio.to_thread(save_reference)

    async def upstream_headers(self, entry: Any) -> dict[str, str]:
        if entry.auth_kind == "none":
            return {}
        from octop.infra.connectors.enterprise_account_auth import BusinessAccountAuth
        from octop.infra.connectors.enterprise_catalog import entry_fingerprint
        from octop.infra.connectors.enterprise_mcp_store import authorization_headers

        async with self._locks.setdefault(entry.entry_id, asyncio.Lock()):
            _, document = await asyncio.to_thread(self._read)
            reference = document.connections.get(entry.entry_id)
            if reference is None:
                raise OctopError.localized(ErrorCode.ENTERPRISE_UNAVAILABLE)
            owner = await asyncio.to_thread(
                self.server.user_manager.get_by_id, reference.owner_user_id
            )
            if (
                owner is None
                or await asyncio.to_thread(self._identity, owner) != reference.owner_identity
            ):
                raise OctopError.localized(ErrorCode.ENTERPRISE_UNAVAILABLE)
            key = "enterprise.mcp.service." + entry.entry_id

            def cached() -> dict[str, str] | None:
                blob = self.secrets.get(key)
                if blob is None:
                    return None
                value = decrypt_json(self.secrets, _PURPOSE, blob)
                if (
                    value.get("reference") == reference.model_dump()
                    and value.get("target") == entry_fingerprint(entry)
                    and value.get("cached_at", 0) > time.time() - 300
                ):
                    return authorization_headers(entry, value["credentials"])
                return None

            headers = await asyncio.to_thread(cached)
            if headers is not None:
                return headers
            credentials = await BusinessAccountAuth(self.server)._helper(
                owner, entry.entry_id, "issue", reference.account_id
            )
            headers = authorization_headers(entry, credentials)
            await asyncio.to_thread(
                self.secrets.set,
                key,
                await asyncio.to_thread(
                    encrypt_json,
                    self.secrets,
                    _PURPOSE,
                    {
                        "reference": reference.model_dump(),
                        "target": entry_fingerprint(entry),
                        "cached_at": int(time.time()),
                        "credentials": credentials,
                    },
                ),
            )
            return headers

    async def initialize_owner(self, user: User, connections: dict[str, str]) -> dict[str, Any]:
        await asyncio.to_thread(self._admin, user)
        identity = await asyncio.to_thread(self._identity, user)
        references: dict[McpId, ServiceConnection] = {}
        for entry_id, account_id in connections.items():
            choices = await self.connection_choices(user, entry_id)
            if not any(row["account_id"] == account_id for row in choices["accounts"]):
                raise OctopError.localized(ErrorCode.ENTERPRISE_ACCESS_DENIED)
            references[cast(McpId, entry_id)] = ServiceConnection(
                owner_user_id=user.id, owner_identity=identity, account_id=account_id
            )
        document = AccessDocument(
            revision=1,
            members=[
                MemberGrant(
                    user_id=user.id, identity=identity, mcp_ids=list(MCP_IDS), companion=True
                )
            ],
            connections=references,
        )

        def commit() -> dict[str, Any]:
            raw, current = self._read()
            if (
                current.revision
                or current.members
                or current.connections
                or not self.settings.compare_and_set(
                    ACCESS_KEY, raw, canonical(document.model_dump(mode="json"))
                )
            ):
                raise OctopError.localized(ErrorCode.ENTERPRISE_ACCESS_POLICY_CONFLICT)
            self.server.services.audit_repo.write(
                actor=user.username,
                action="enterprise.member_access.initialize",
                target=ACCESS_KEY,
                payload=str(user.id),
            )
            return self.admin(user)

        return await asyncio.to_thread(commit)


def access_for(server: Any) -> MemberAccess:
    value = getattr(server, "_enterprise_member_access", None)
    if value is None or value.settings is not server.services.settings_repo:
        value = MemberAccess(server)
        server._enterprise_member_access = value
    return value
