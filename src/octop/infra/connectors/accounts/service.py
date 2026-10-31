"""Vault metadata and single-use, human-approved secret delivery.

Tools may obtain opaque references and request a use. Only the authenticated
human-facing API can approve. Secret values, HTTP response bodies and CLI stderr
are never returned to the caller or persisted in chat history.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit
from weakref import WeakKeyDictionary

from octop.i18n import tr
from octop.infra.connectors.accounts.vault_cli import VaultCliError, item_metadata, run_vault_cli
from octop.infra.connectors.accounts.vault_delivery import send_secret_header
from octop.infra.connectors.crypto import decrypt_credentials, encrypt_credentials
from octop.infra.utils.paths import PathLayout
from octop.infra.utils.ssrf_guard import (
    UnsafeOutboundUrl,
    validate_https_url_resolved,
)
from octop.infra.utils.ulid import new_ulid

_PROVIDERS = {"onepassword", "bitwarden"}
_REQUEST_TTL = 600
_SESSION_TTL = 3600
_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_FIELD = re.compile(r"[A-Za-z0-9_ .-]{1,128}\Z")
_HEADERS = {"Authorization", "X-API-Key", "Api-Key"}


class AccountConnectionError(Exception):
    def __init__(self, code: str, *, locale: str = "en", status: int = 400) -> None:
        self.code = code
        self.status = status
        super().__init__(tr(f"accountConnections.errors.{code}", locale))


@dataclass
class _Runtime:
    locks: dict[int, asyncio.Lock] = field(default_factory=dict)
    # Unlock keys are never stored in SQL, files, logs or returned by an API.
    sessions: dict[tuple[int, str], tuple[str, float]] = field(default_factory=dict)


_RUNTIMES: WeakKeyDictionary[Any, _Runtime] = WeakKeyDictionary()


def _runtime(repo: Any) -> _Runtime:
    result = _RUNTIMES.get(repo)
    if result is None:
        result = _Runtime()
        _RUNTIMES[repo] = result
    return result


def _hosts(values: list[str]) -> list[str]:
    cleaned = []
    for value in values:
        host = value.strip().lower().rstrip(".")
        if (
            not host
            or len(host) > 253
            or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host)
            or ".." in host
        ):
            raise ValueError("invalid hostname")
        if host not in cleaned:
            cleaned.append(host)
    if len(cleaned) > 20:
        raise ValueError("too many hosts")
    return cleaned


class AccountConnectionService:
    def __init__(
        self, *, settings_repo: Any, secret_repo: Any, paths: PathLayout, locale: str = "en"
    ) -> None:
        self.settings = settings_repo
        self.secrets = secret_repo
        self.paths = paths
        self.locale = locale
        self.runtime = _runtime(settings_repo)

    def _error(self, code: str, status: int = 400) -> AccountConnectionError:
        return AccountConnectionError(code, locale=self.locale, status=status)

    def _lock(self, user_id: int) -> asyncio.Lock:
        if user_id <= 0:
            raise self._error("not_found", 404)
        return self.runtime.locks.setdefault(user_id, asyncio.Lock())

    async def _load(self, user_id: int) -> dict[str, Any]:
        raw = await asyncio.to_thread(self.settings.get, f"account.connections.{user_id}")
        if not raw:
            return {"connections": {}, "references": {}, "requests": {}}
        return await asyncio.to_thread(
            decrypt_credentials, self.secrets, base64.b64decode(raw, validate=True)
        )

    async def _save(self, user_id: int, document: dict[str, Any]) -> None:
        def save() -> None:
            blob = encrypt_credentials(self.secrets, document)
            self.settings.set(
                f"account.connections.{user_id}", base64.b64encode(blob).decode("ascii")
            )

        await asyncio.to_thread(save)

    def _profile(self, user_id: int, connection: dict[str, Any]) -> Any:
        key = hashlib.sha256(f"{user_id}:{connection['id']}".encode()).hexdigest()
        return self.paths.connector_cli_instance_dir(str(connection["provider"]), key)

    def _credential(self, user_id: int, connection: dict[str, Any]) -> str:
        if connection["provider"] == "onepassword":
            token = str(connection.get("service_account_token") or "")
            if token:
                return token
        else:
            key = (user_id, str(connection["id"]))
            value = self.runtime.sessions.get(key)
            if value and value[1] > time.time():
                return value[0]
            self.runtime.sessions.pop(key, None)
        raise self._error("authentication_required")

    def _connection(self, document: dict[str, Any], connection_id: str) -> dict[str, Any]:
        result = document["connections"].get(connection_id)
        if not isinstance(result, dict):
            raise self._error("not_found", 404)
        return result

    def _public(self, user_id: int, connection: dict[str, Any]) -> dict[str, Any]:
        try:
            self._credential(user_id, connection)
            unlocked = True
        except AccountConnectionError:
            unlocked = False
        return {
            "id": connection["id"],
            "provider": connection["provider"],
            "name": connection["name"],
            "allowed_hosts": list(connection.get("allowed_hosts", [])),
            "ready": unlocked,
            "profile_path": str(self._profile(user_id, connection))
            if connection["provider"] == "bitwarden"
            else None,
        }

    def has_connections_sync(self, user_id: int) -> bool:
        """Synchronous config-builder gate; no credential or vault access."""
        return bool(self.settings.get(f"account.connections.{user_id}"))

    async def has_connections(self, user_id: int) -> bool:
        return bool((await self._load(user_id))["connections"])

    async def list_connections(self, user_id: int) -> list[dict[str, Any]]:
        document = await self._load(user_id)
        return [
            self._public(user_id, connection) for connection in document["connections"].values()
        ]

    async def save_connection(
        self,
        user_id: int,
        *,
        provider: str,
        name: str,
        allowed_hosts: list[str],
        service_account_token: str = "",
        connection_id: str | None = None,
    ) -> dict[str, Any]:
        if (
            provider not in _PROVIDERS
            or not name.strip()
            or len(name) > 100
            or len(service_account_token) > 20000
            or any(c in service_account_token for c in "\r\n")
        ):
            raise self._error("invalid_input")
        try:
            hosts = _hosts(allowed_hosts)
        except ValueError:
            raise self._error("invalid_target") from None
        async with self._lock(user_id):
            document = await self._load(user_id)
            old = self._connection(document, connection_id) if connection_id else {}
            if old and old["provider"] != provider:
                raise self._error("invalid_input")
            if not old and len(document["connections"]) >= 20:
                raise self._error("limit_exceeded")
            identifier = connection_id or new_ulid()
            connection = {
                "id": identifier,
                "provider": provider,
                "name": name.strip(),
                "allowed_hosts": hosts,
            }
            if provider == "onepassword":
                token = service_account_token.strip() or str(old.get("service_account_token") or "")
                if not token:
                    raise self._error("authentication_required")
                connection["service_account_token"] = token
            document["connections"][identifier] = connection
            await self._save(user_id, document)
            return self._public(user_id, connection)

    async def delete_connection(self, user_id: int, connection_id: str) -> None:
        async with self._lock(user_id):
            document = await self._load(user_id)
            self._connection(document, connection_id)
            del document["connections"][connection_id]
            removed = {
                key
                for key, value in document["references"].items()
                if value["connection_id"] == connection_id
            }
            document["references"] = {
                key: value for key, value in document["references"].items() if key not in removed
            }
            document["requests"] = {
                key: value
                for key, value in document["requests"].items()
                if value["reference"] not in removed
            }
            self.runtime.sessions.pop((user_id, connection_id), None)
            await self._save(user_id, document)

    async def unlock_bitwarden(self, user_id: int, connection_id: str, session: str) -> None:
        connection = self._connection(await self._load(user_id), connection_id)
        if (
            connection["provider"] != "bitwarden"
            or not session.strip()
            or len(session) > 10000
            or any(c in session for c in "\r\n")
        ):
            raise self._error("invalid_input")
        self.runtime.sessions[(user_id, connection_id)] = (
            session.strip(),
            time.time() + _SESSION_TTL,
        )

    async def lock_connection(self, user_id: int, connection_id: str) -> None:
        self._connection(await self._load(user_id), connection_id)
        self.runtime.sessions.pop((user_id, connection_id), None)

    async def list_items(
        self, user_id: int, connection_id: str, *, offset: int = 0, search: str = ""
    ) -> list[dict[str, str]]:
        if not 0 <= offset <= 100000 or len(search) > 200:
            raise self._error("invalid_input")
        connection = self._connection(await self._load(user_id), connection_id)
        credential = self._credential(user_id, connection)
        provider = str(connection["provider"])
        args = ["item", "list", "--format=json"] if provider == "onepassword" else ["list", "items"]
        try:
            raw = await run_vault_cli(
                provider, args, profile=self._profile(user_id, connection), credential=credential
            )
            return item_metadata(provider, raw, offset=offset, search=search)
        except VaultCliError as exc:
            raise self._error(exc.code) from None

    async def create_reference(
        self,
        user_id: int,
        *,
        connection_id: str,
        item_id: str,
        vault_id: str = "",
        field_name: str = "password",
        label: str = "",
    ) -> dict[str, str]:
        async with self._lock(user_id):
            document = await self._load(user_id)
            connection = self._connection(document, connection_id)
            if connection["provider"] == "onepassword":
                valid = bool(
                    _ID.fullmatch(item_id)
                    and _ID.fullmatch(vault_id)
                    and _FIELD.fullmatch(field_name)
                )
            else:
                try:
                    uuid.UUID(item_id)
                    valid = field_name in {"password", "username", "totp"}
                except ValueError:
                    valid = False
            if not valid or len(label) > 200:
                raise self._error("invalid_input")
            if len(document["references"]) >= 200:
                raise self._error("limit_exceeded")
            reference = "vaultref_" + new_ulid()
            value = {
                "reference": reference,
                "connection_id": connection_id,
                "item_id": item_id,
                "vault_id": vault_id,
                "field_name": field_name,
                "label": label or item_id,
            }
            document["references"][reference] = value
            await self._save(user_id, document)
            return {"reference": reference, "label": value["label"], "field_name": field_name}

    async def list_references(self, user_id: int) -> list[dict[str, str]]:
        document = await self._load(user_id)
        return [
            {key: str(value[key]) for key in ("reference", "connection_id", "label", "field_name")}
            for value in document["references"].values()
        ]

    async def _target(self, connection: dict[str, Any], url: str) -> str:
        try:
            parsed = urlsplit(url)
            host = (parsed.hostname or "").lower().rstrip(".")
            port = parsed.port
        except ValueError:
            raise self._error("invalid_target") from None
        if (
            parsed.scheme != "https"
            or parsed.username
            or parsed.password
            or parsed.fragment
            or port not in (None, 443)
            or host not in connection.get("allowed_hosts", [])
        ):
            raise self._error("invalid_target")
        cleaned = urlunsplit(("https", host, parsed.path or "/", parsed.query, ""))
        try:
            async with asyncio.timeout(10):
                return await validate_https_url_resolved(cleaned)
        except (UnsafeOutboundUrl, ValueError, TimeoutError):
            raise self._error("invalid_target") from None

    async def request_use(
        self,
        user_id: int,
        *,
        reference: str,
        url: str,
        purpose: str,
        method: str = "GET",
        header_name: str = "Authorization",
        prefix: str = "Bearer ",
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if (
            method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}
            or header_name not in _HEADERS
            or len(prefix) > 32
            or any(c in prefix for c in "\r\n")
            or not purpose.strip()
            or len(purpose) > 500
            or len(json.dumps(body)) > 16000
        ):
            raise self._error("invalid_input")
        async with self._lock(user_id):
            document = await self._load(user_id)
            ref = document["references"].get(reference)
            if not isinstance(ref, dict):
                raise self._error("not_found", 404)
            connection = self._connection(document, str(ref["connection_id"]))
            target = await self._target(connection, url)
            now = int(time.time())
            # Retain a bounded metadata-only audit, never secret values or response bodies.
            document["requests"] = {
                key: value
                for key, value in document["requests"].items()
                if value["expires_at"] > now - 86400
            }
            if len(document["requests"]) >= 100:
                raise self._error("limit_exceeded")
            request_id = new_ulid()
            value = {
                "request_id": request_id,
                "reference": reference,
                "url": target,
                "purpose": purpose.strip(),
                "method": method,
                "header_name": header_name,
                "prefix": prefix,
                "body": body,
                "state": "pending",
                "created_at": now,
                "expires_at": now + _REQUEST_TTL,
                "approval_token": secrets.token_urlsafe(32),
            }
            document["requests"][request_id] = value
            await self._save(user_id, document)
            return {
                key: value[key]
                for key in (
                    "request_id",
                    "reference",
                    "url",
                    "method",
                    "purpose",
                    "expires_at",
                    "state",
                )
            }

    async def list_requests(self, user_id: int) -> list[dict[str, Any]]:
        document = await self._load(user_id)
        now = time.time()
        return [
            {
                **value,
                "state": "expired"
                if value["state"] == "pending" and value["expires_at"] <= now
                else value["state"],
            }
            for value in document["requests"].values()
        ]

    async def reject_use(self, user_id: int, request_id: str) -> None:
        async with self._lock(user_id):
            document = await self._load(user_id)
            value = document["requests"].get(request_id)
            if not isinstance(value, dict):
                raise self._error("not_found", 404)
            if value["state"] != "pending":
                raise self._error("request_not_pending", 409)
            value["state"] = "rejected"
            value.pop("approval_token", None)
            await self._save(user_id, document)

    async def approve_use(
        self, user_id: int, request_id: str, approval_token: str
    ) -> dict[str, Any]:
        async with self._lock(user_id):
            document = await self._load(user_id)
            value = document["requests"].get(request_id)
            if not isinstance(value, dict):
                raise self._error("not_found", 404)
            if value["state"] != "pending":
                raise self._error("request_not_pending", 409)
            if value["expires_at"] <= time.time():
                raise self._error("expired_request", 409)
            if (
                not secrets.compare_digest(str(value.get("approval_token") or ""), approval_token)
                or not approval_token
            ):
                raise self._error("approval_required", 403)
            reference = document["references"].get(value["reference"])
            if not isinstance(reference, dict):
                raise self._error("not_found", 404)
            connection = self._connection(document, str(reference["connection_id"]))
            target = await self._target(connection, str(value["url"]))
            credential = self._credential(user_id, connection)
            # Consume before touching the vault/network. A crash cannot replay a mutation.
            value["state"] = "consumed"
            value.pop("approval_token", None)
            await self._save(user_id, document)
        try:
            secret = await self._read_secret(user_id, connection, reference, credential)
            if not secret or len(secret) > 65536 or any(char in secret for char in "\r\n"):
                raise self._error("unsupported_secret")
            status_code = await send_secret_header(
                str(value["method"]),
                target,
                headers={str(value["header_name"]): str(value["prefix"]) + secret},
                body=value.get("body"),
            )
            # Never expose a body, Location, headers or exception: an echo endpoint
            # can reflect the secret, including encoded or transformed variants.
            result = {
                "request_id": request_id,
                "state": "completed",
                "status_code": status_code,
            }
        except AccountConnectionError:
            await self._finish_request(user_id, request_id, "failed")
            raise
        except VaultCliError as exc:
            await self._finish_request(user_id, request_id, "failed")
            raise self._error(exc.code) from None
        except Exception:
            await self._finish_request(user_id, request_id, "failed")
            raise self._error("delivery_failed") from None
        await self._finish_request(user_id, request_id, "completed", status_code)
        return result

    async def _finish_request(
        self, user_id: int, request_id: str, state: str, status_code: int | None = None
    ) -> None:
        async with self._lock(user_id):
            document = await self._load(user_id)
            value = document["requests"].get(request_id)
            if isinstance(value, dict):
                value["state"] = state
                if status_code is not None:
                    value["status_code"] = status_code
                await self._save(user_id, document)

    async def _read_secret(
        self, user_id: int, connection: dict[str, Any], reference: dict[str, Any], credential: str
    ) -> str:
        provider = str(connection["provider"])
        if provider == "onepassword":
            uri = "op://" + "/".join(
                quote(str(reference[key]), safe="") for key in ("vault_id", "item_id", "field_name")
            )
            args = ["read", uri, "--no-newline"]
        else:
            args = ["get", str(reference["field_name"]), str(reference["item_id"]), "--raw"]
        raw = await run_vault_cli(
            provider, args, profile=self._profile(user_id, connection), credential=credential
        )
        return raw.decode("utf-8").rstrip("\r\n")
