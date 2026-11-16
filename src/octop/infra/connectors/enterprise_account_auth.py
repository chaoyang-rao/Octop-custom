"""Member-selected business grants bound to a verified company SSO identity."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from octop.infra.auth.enterprise import center_for, client_for
from octop.infra.connectors.enterprise_catalog import EnterpriseMcpCatalog, entry_fingerprint
from octop.infra.connectors.enterprise_mcp_sync import sync_for
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.users.identity import User

SUPPORTED = frozenset({"aftersales-quality", "quota-workbench"})


def _denied() -> OctopError:
    return OctopError.localized(ErrorCode.ENTERPRISE_ACCESS_DENIED)


class BusinessAccountAuth:
    def __init__(self, server: Any) -> None:
        self.server = server

    def _entry(self, user: User, entry_id: str) -> Any:
        if entry_id not in SUPPORTED:
            raise _denied()
        entry = next(
            (
                e
                for e in EnterpriseMcpCatalog(self.server).snapshot_for(user).entries
                if e.entry_id == entry_id and e.enabled
            ),
            None,
        )
        if entry is None:
            raise _denied()
        origin = os.environ.get("OCTOP_MCP_ACCOUNT_ORIGIN", "").rstrip("/")
        path = "aftersales" if entry_id == "aftersales-quality" else "workbench"
        expected_auth = "bearer" if entry_id == "aftersales-quality" else "basic"
        if (
            not origin
            or entry.url != origin + "/team-mcp/" + path
            or entry.auth_kind != expected_auth
        ):
            raise _denied()
        return entry

    async def _helper(
        self, user: User, entry_id: str, action: str, account_id: str = ""
    ) -> dict[str, Any]:
        center_for(self.server).require_employee(user)
        provider = self.server.services.sso_repo.get_by_kind("feishu")
        identity = next(
            (
                i
                for i in self.server.user_manager.list_sso_identities(user.id)
                if i.kind == "feishu" and provider is not None and i.provider_id == provider.id
            ),
            None,
        )
        if identity is None:
            raise _denied()
        helper = os.environ.get("OCTOP_MCP_ACCOUNT_HELPER", "")
        if helper != "/usr/local/libexec/octop-mcp-account-helper":
            if action == "list":
                return {"accounts": []}
            raise _denied()
        process = await asyncio.create_subprocess_exec(
            "/usr/bin/sudo",
            "-n",
            helper,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        payload = json.dumps(
            {
                "action": action,
                "entry_id": entry_id,
                "subject": identity.subject,
                "company_user_id": user.id,
                "account_id": account_id,
            }
        ).encode()
        try:
            output, _ = await asyncio.wait_for(process.communicate(payload), 20)
            if process.returncode or len(output) > 65536:
                raise ValueError
            result = json.loads(output)
            if not isinstance(result, dict):
                raise ValueError
            return result
        except (ValueError, TimeoutError):
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise OctopError.localized(ErrorCode.ENTERPRISE_UNAVAILABLE) from None

    async def choices(self, user: User, entry_id: str) -> dict[str, Any]:
        self._entry(user, entry_id)
        result = await self._helper(user, entry_id, "list")
        # Never return helper extras, session cookies, or credentials to a picker.
        return {
            "identity_name": user.label,
            "accounts": [
                {"account_id": str(row["account_id"]), "label": str(row["label"])}
                for row in result.get("accounts", [])
            ],
        }

    async def issue(
        self, user: User, entry_id: str, account_id: str, fingerprint: str
    ) -> dict[str, Any]:
        entry = self._entry(user, entry_id)
        if entry_fingerprint(entry) != fingerprint:
            raise OctopError.localized(ErrorCode.ENTERPRISE_MCP_CATALOG_CONFLICT)
        choices = await self.choices(user, entry_id)
        if account_id not in {row["account_id"] for row in choices["accounts"]}:
            raise _denied()
        result = await self._helper(user, entry_id, "issue", account_id)
        fields = ("token",) if entry.auth_kind == "bearer" else ("username", "password")
        if not all(isinstance(result.get(k), str) and result[k] for k in fields):
            raise OctopError.localized(ErrorCode.CONNECTOR_INVALID_CREDENTIALS)
        self.server.services.audit_repo.write(
            actor=user.username,
            action="enterprise.mcp.account.authorize",
            target=entry_id,
            payload=json.dumps({"account_id": account_id}),
        )
        return {k: result[k] for k in fields}


async def member_account_request(
    server: Any, user: User, entry_id: str, selection: dict[str, Any] | None = None
) -> dict[str, Any]:
    if entry_id not in SUPPORTED:
        if selection is None:
            return {"identity_name": user.label, "accounts": []}
        raise _denied()
    client = client_for(server)
    if client is None:
        raise _denied()
    state = await asyncio.to_thread(client._state, user.id)
    path = f"/api/enterprise/mcp/accounts/{entry_id}"
    if selection is None:
        return await client._remote("GET", path, token=state["token"])
    credentials = await client._remote("POST", path, token=state["token"], body=selection)
    return await sync_for(server).save_credentials(
        user, entry_id, credentials, selection["expected_fingerprint"]
    )
