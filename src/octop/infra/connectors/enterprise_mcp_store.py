"""Local company definitions and member credentials, separate from personal MCPs."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import time
import uuid
from typing import Any

from cryptography.fernet import InvalidToken

from octop.infra.connectors.enterprise_catalog import (
    CatalogEntry,
    CatalogSnapshot,
    build_snapshot,
    entry_fingerprint,
    validate_snapshot,
)
from octop.infra.crypto.fernet import decrypt_json, encrypt_json
from octop.infra.db.repos.secrets import SecretRepo
from octop.infra.db.repos.settings import SettingsRepo
from octop.infra.errors import ErrorCode, OctopError

_PURPOSE = "enterprise_mcp_member_fernet"


def authorization_headers(entry: CatalogEntry, credentials: dict[str, str]) -> dict[str, str]:
    if entry.auth_kind == "none":
        return {}
    if entry.auth_kind == "bearer":
        token = credentials.get("token", "").strip()
        if not token or len(token) > 16384 or any(c in token for c in "\r\n\0"):
            raise OctopError.localized(ErrorCode.CONNECTOR_INVALID_CREDENTIALS)
        return {"Authorization": f"Bearer {token}"}
    username, password = credentials.get("username", ""), credentials.get("password", "")
    if not username or not password or ":" in username or len(username) + len(password) > 16384:
        raise OctopError.localized(ErrorCode.CONNECTOR_INVALID_CREDENTIALS)
    encoded = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    return {"Authorization": f"Basic {encoded}"}


class EnterpriseMcpStore:
    def __init__(self, settings: SettingsRepo, secrets: SecretRepo, authority: str) -> None:
        self.settings = settings
        self.secrets = secrets
        self.authority = authority.rstrip("/")
        self.source_id = hashlib.sha256(self.authority.encode()).hexdigest()[:16]

    def server_name(self, entry_id: str, *, user_id: int, subject: str | None = None) -> str:
        if subject is None:
            subject = str(self.state(user_id)["subject"])
        scope = json.dumps([self.authority, user_id, subject, entry_id], separators=(",", ":"))
        return "corp_" + hashlib.sha256(scope.encode()).hexdigest()[:16]

    def known_names(self, user_id: int) -> set[str]:
        if not self.authority:
            return set()
        state = self.state(user_id)
        ids = set(self._entries(state, "desired")) | set(self._entries(state, "applied"))
        return {
            self.server_name(entry_id, user_id=user_id, subject=str(state["subject"]))
            for entry_id in ids
        }

    def entry_id_for_name(self, name: str, *, user_id: int) -> str | None:
        return self._entry_id_for_name(self.state(user_id), name, user_id=user_id)

    def _entry_id_for_name(self, state: dict[str, Any], name: str, *, user_id: int) -> str | None:
        ids = set(self._entries(state, "desired")) | set(self._entries(state, "applied"))
        return next(
            (
                entry_id
                for entry_id in ids
                if self.server_name(entry_id, user_id=user_id, subject=str(state["subject"]))
                == name
            ),
            None,
        )

    def _key(self, user_id: int) -> str:
        return f"enterprise.mcp.node.{self.source_id}.{user_id}"

    @staticmethod
    def _empty(subject: str = "") -> dict[str, Any]:
        empty = build_snapshot(revision=0, published_at=0, entries=[]).model_dump(mode="json")
        return {
            "subject": subject,
            "allow_use": False,
            "desired": empty,
            "applied": empty,
            "desired_auth": {},
            "applied_auth": {},
            "auth_revision": 0,
            "applied_auth_revision": 0,
            "revoked": [],
            "local_disabled": [],
            "last_synced_at": None,
            "sync_error": None,
        }

    def state(self, user_id: int) -> dict[str, Any]:
        raw = self.settings.get(self._key(user_id)) if self.authority else None
        return json.loads(raw) if raw else self._empty()

    def _save(self, user_id: int, state: dict[str, Any]) -> None:
        self.settings.set(self._key(user_id), json.dumps(state, ensure_ascii=False))

    def reset_subject(self, user_id: int, subject: str) -> None:
        if self.state(user_id)["subject"] != subject:
            self._save(user_id, self._empty(subject))

    def receive(self, user_id: int, subject: str, snapshot: CatalogSnapshot) -> None:
        state = self.state(user_id)
        if state["subject"] != subject:
            state = self._empty(subject)
        if snapshot.revision < state["desired"]["revision"]:
            raise OctopError.localized(ErrorCode.ENTERPRISE_MCP_CATALOG_INVALID)
        state["desired"] = snapshot.model_dump(mode="json")
        state["allow_use"] = True
        state["last_synced_at"] = int(time.time())
        state["sync_error"] = None
        self._save(user_id, state)

    def mark_error(self, user_id: int, code: ErrorCode) -> None:
        state = self.state(user_id)
        state["sync_error"] = code.value
        if code in {ErrorCode.ENTERPRISE_ACCESS_DENIED, ErrorCode.ENTERPRISE_LOGIN_REQUIRED}:
            state["allow_use"] = False
        self._save(user_id, state)

    def pending(self, user_id: int) -> bool:
        state = self.state(user_id)
        return bool(
            state["desired"]["checksum"] != state["applied"]["checksum"]
            or state["auth_revision"] != state["applied_auth_revision"]
        )

    @staticmethod
    def _entries(state: dict[str, Any], which: str) -> dict[str, CatalogEntry]:
        snapshot = validate_snapshot(state[which])
        return {entry.entry_id: entry for entry in snapshot.entries}

    def desired_entry(self, user_id: int, entry_id: str) -> CatalogEntry:
        entry = self._entries(self.state(user_id), "desired").get(entry_id)
        if entry is None or not entry.enabled:
            raise OctopError.localized(ErrorCode.CONNECTOR_NOT_FOUND)
        return entry

    def _credential(
        self, user_id: int, state: dict[str, Any], entry: CatalogEntry, which: str
    ) -> dict[str, str] | None:
        if entry.auth_kind == "none":
            return {}
        ref = state[which].get(entry.entry_id)
        if not isinstance(ref, dict) or ref.get("fingerprint") != entry_fingerprint(entry):
            return None
        blob = self.secrets.get(str(ref["key"]))
        if blob is None:
            return None
        try:
            payload = decrypt_json(self.secrets, _PURPOSE, blob)
            if (
                payload.get("subject") != state["subject"]
                or payload.get("user_id") != user_id
                or payload.get("authority") != self.authority
                or payload.get("fingerprint") != entry_fingerprint(entry)
            ):
                return None
            credentials = payload["credentials"]
            if not isinstance(credentials, dict):
                return None
            authorization_headers(entry, credentials)
            return {str(k): str(v) for k, v in credentials.items()}
        except (InvalidToken, ValueError, KeyError, TypeError, OctopError):
            return None

    def authorized(self, user_id: int, entry: CatalogEntry) -> bool:
        state = self.state(user_id)
        credential = self._credential(user_id, state, entry, "desired_auth")
        pending_ref = state["desired_auth"].get(entry.entry_id)
        reconnecting = bool(
            pending_ref and pending_ref != state["applied_auth"].get(entry.entry_id)
        )
        return credential is not None and (
            entry.entry_id not in state["local_disabled"] or reconnecting
        )

    def has_entry(self, user_id: int, entry_id: str) -> bool:
        state = self.state(user_id)
        return any(
            entry_id in values
            for values in (
                self._entries(state, "desired"),
                self._entries(state, "applied"),
                state["desired_auth"],
                state["applied_auth"],
            )
        )

    def stage_credentials(
        self, user_id: int, entry: CatalogEntry, credentials: dict[str, str]
    ) -> None:
        authorization_headers(entry, credentials)
        state = self.state(user_id)
        subject_hash = hashlib.sha256(str(state["subject"]).encode()).hexdigest()[:16]
        key = f"enterprise.mcp.auth.{self.source_id}.{user_id}.{subject_hash}.{uuid.uuid4().hex}"
        self.secrets.set(
            key,
            encrypt_json(
                self.secrets,
                _PURPOSE,
                {
                    "subject": state["subject"],
                    "user_id": user_id,
                    "authority": self.authority,
                    "fingerprint": entry_fingerprint(entry),
                    "credentials": credentials,
                },
            ),
        )
        previous = state["desired_auth"].get(entry.entry_id)
        state["desired_auth"][entry.entry_id] = {
            "key": key,
            "fingerprint": entry_fingerprint(entry),
        }
        state["auth_revision"] += 1
        state["sync_error"] = None
        self._save(user_id, state)
        active = state["applied_auth"].get(entry.entry_id)
        if previous and previous != active:
            self.secrets.delete(previous["key"])

    def revoke(self, user_id: int, entry_id: str) -> None:
        state = self.state(user_id)
        refs = [
            state["desired_auth"].pop(entry_id, None),
            state["applied_auth"].get(entry_id),
        ]
        state["revoked"] = sorted({*state["revoked"], entry_id})
        state["local_disabled"] = sorted({*state["local_disabled"], entry_id})
        state["auth_revision"] += 1
        self._save(user_id, state)
        for ref in refs:
            if isinstance(ref, dict):
                self.secrets.delete(ref["key"])

    def activate_pending(self, user_id: int) -> dict[str, Any]:
        state = self.state(user_id)
        before = copy.deepcopy(state)
        desired = self._entries(state, "desired")
        reconnecting = {
            entry_id
            for entry_id, ref in state["desired_auth"].items()
            if ref != state["applied_auth"].get(entry_id)
            and entry_id in desired
            and self._credential(user_id, state, desired[entry_id], "desired_auth") is not None
        }
        state["local_disabled"] = [
            entry_id for entry_id in state["local_disabled"] if entry_id not in reconnecting
        ]
        state["applied"] = state["desired"]
        state["applied_auth"] = dict(state["desired_auth"])
        self._save(user_id, state)
        return before

    def finish_apply(self, user_id: int, before: dict[str, Any]) -> None:
        state = self.state(user_id)
        state["applied_auth_revision"] = state["auth_revision"]
        state["revoked"] = []
        state["sync_error"] = None
        self._save(user_id, state)
        retained = {ref["key"] for ref in state["desired_auth"].values()}
        for ref in before["applied_auth"].values():
            if ref["key"] not in retained:
                self.secrets.delete(ref["key"])

    def restore_active(self, user_id: int, before: dict[str, Any]) -> None:
        state = self.state(user_id)
        for key in ("applied", "applied_auth", "applied_auth_revision", "local_disabled"):
            state[key] = before[key]
        state["sync_error"] = ErrorCode.ENTERPRISE_MCP_SYNC_FAILED.value
        self._save(user_id, state)

    def callable_entry(
        self, user_id: int, server_name: str, fingerprint: str | None = None
    ) -> CatalogEntry | None:
        return self._callable_entry(user_id, self.state(user_id), server_name, fingerprint)

    def _callable_entry(
        self,
        user_id: int,
        state: dict[str, Any],
        server_name: str,
        fingerprint: str | None = None,
    ) -> CatalogEntry | None:
        entry_id = self._entry_id_for_name(state, server_name, user_id=user_id)
        desired = self._entries(state, "desired").get(entry_id or "")
        active = self._entries(state, "applied").get(entry_id or "")
        if (
            not desired
            or not state["allow_use"]
            or not desired.enabled
            or not active
            or not active.enabled
            or entry_id in state["revoked"]
            or entry_id in state["local_disabled"]
            or (
                fingerprint is not None
                and self._runtime_binding(state, active.entry_id) != fingerprint
            )
            or self._credential(user_id, state, active, "applied_auth") is None
        ):
            return None
        return active

    def runtime_binding(self, user_id: int, entry_id: str) -> str:
        return self._runtime_binding(self.state(user_id), entry_id)

    def _runtime_binding(self, state: dict[str, Any], entry_id: str) -> str:
        entry = self._entries(state, "applied").get(entry_id)
        if entry is None:
            return ""
        ref = state["applied_auth"].get(entry_id, {})
        value = [state["subject"], entry_fingerprint(entry), ref.get("key", "none")]
        return hashlib.sha256(json.dumps(value, separators=(",", ":")).encode()).hexdigest()

    def binding_for_spec(self, user_id: int, server_name: str, spec: dict[str, Any]) -> str:
        """Bind the exact connection spec to one applied credential generation."""
        state = self.state(user_id)
        entry = self._callable_entry(user_id, state, server_name)
        if entry is None:
            return ""
        credentials = self._credential(user_id, state, entry, "applied_auth")
        if credentials is None or spec != {
            "transport": "streamable_http",
            "url": entry.url,
            "headers": authorization_headers(entry, credentials),
        }:
            return ""
        return self._runtime_binding(state, entry.entry_id)

    def runtime_bindings(self, user_id: int) -> dict[str, str]:
        state = self.state(user_id)
        return {
            name: self.runtime_binding(user_id, entry.entry_id)
            for entry in self._entries(state, "applied").values()
            if self.callable_entry(
                user_id, name := self.server_name(entry.entry_id, user_id=user_id)
            )
            is not None
        }

    def harness_configs(self, user_id: int) -> dict[str, Any]:
        if not self.authority:
            return {}
        state = self.state(user_id)
        configs: dict[str, Any] = {}
        for entry in self._entries(state, "applied").values():
            name = self.server_name(entry.entry_id, user_id=user_id)
            if self.callable_entry(user_id, name) is None:
                continue
            credentials = self._credential(user_id, state, entry, "applied_auth")
            assert credentials is not None
            configs[name] = {
                "transport": "streamable_http",
                "url": entry.url,
                "headers": authorization_headers(entry, credentials),
            }
        return configs

    def instances(self, user_id: int, existing_names: set[str]) -> list[dict[str, Any]]:
        if not self.authority:
            return []
        state = self.state(user_id)
        desired = self._entries(state, "desired")
        entries = {**self._entries(state, "applied"), **desired}
        configs = self.harness_configs(user_id)
        result: list[dict[str, Any]] = []
        for entry_id, entry in entries.items():
            name = self.server_name(entry_id, user_id=user_id)
            enabled = entry_id in desired and entry.enabled
            usable = name in configs and name not in existing_names
            result.append(
                {
                    "instance_id": f"enterprise:{entry_id}",
                    "kind": "enterprise-mcp",
                    "display_name": entry.display_name,
                    "description": entry.description,
                    "status": "active" if enabled else "inactive",
                    "mcp_server_name": name,
                    "has_credentials": self.authorized(user_id, entry),
                    "default_open": False,
                    "shared": True,
                    "owner_user_id": user_id,
                    "created_at": state["applied"]["published_at"],
                    "updated_at": state["last_synced_at"] or 0,
                    "usable": usable,
                }
            )
        return result
