"""One-time owner-approved device pairing and immediately revocable sessions.

Only hashes of pairing and session credentials are persisted. Push credentials
are encrypted separately. Device grants never inherit the owner's admin role.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import ipaddress
import json
import re
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from octop.infra.connectors.crypto import decrypt_credentials, encrypt_credentials
from octop.infra.db.repos.secrets import SecretRepo
from octop.infra.db.repos.settings import SettingsRepo
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.mobile_access.seal import notification_key
from octop.infra.utils.ulid import new_ulid

TOKEN_PREFIX = "octop_mobile_"
SHARE_PREFIX = TOKEN_PREFIX + "share_"
PAIRING_TTL = 300
DEVICE_TTL = 30 * 86400
SCOPES = frozenset(
    {
        "chat",
        "files",
        "notifications",
        "tasks",
        "browser",
        "desktop",
        "terminal",
        "phone",
        "manage_agents",
    }
)
DEFAULT_SCOPES = ("chat", "files", "notifications", "tasks")
_PAIRINGS_KEY = "mobile_access.pending"
_CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def validate_server_url(raw: str) -> str:
    if any(ord(char) < 32 or ord(char) == 127 for char in raw):
        raise ValueError("mobile_access.invalid_url")
    parts = urlsplit(raw.strip())
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("mobile_access.invalid_url")
    if parts.path not in ("", "/") or not parts.hostname:
        raise ValueError("mobile_access.invalid_url")
    local = parts.hostname in {"localhost", "127.0.0.1", "::1"}
    if parts.scheme != "https" and not (local and parts.scheme == "http"):
        raise ValueError("mobile_access.https_required")
    port = parts.port
    host = parts.hostname.encode("idna").decode("ascii").lower()
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if any(
            not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
            for label in host.split(".")
        ):
            raise ValueError("mobile_access.invalid_url") from None
    authority = f"[{host}]" if ":" in host else host
    if port is not None:
        authority += f":{port}"
    return urlunsplit((parts.scheme, authority, "", "", ""))


def normalize_scopes(scopes: list[str]) -> list[str]:
    if not scopes or not set(scopes) <= SCOPES:
        raise ValueError("mobile_access.invalid_scope")
    return sorted(set(scopes))


def normalize_code(value: str) -> str:
    return re.sub(r"[\s-]", "", value).upper()


def _error() -> OctopError:
    return OctopError(ErrorCode.AUTH_FAILED, "mobile device credential is invalid or expired")


@dataclass(frozen=True)
class DeviceSession:
    user_id: int
    device_id: str
    scopes: tuple[str, ...]
    expires_at: int
    kind: str = "device"


class MobileAccessService:
    def __init__(self, settings_repo: SettingsRepo, secret_repo: SecretRepo) -> None:
        self._settings = settings_repo
        self._secrets = secret_repo
        self._lock = asyncio.Lock()
        self._attempts: dict[str, tuple[int, int]] = {}
        self._presence_lock = threading.RLock()
        self._foreground: dict[str, int] = {}
        self._presence: dict[tuple[int, str], tuple[str | None, int]] = {}

    def _read(self, key: str, default: Any) -> Any:
        raw = self._settings.get(key)
        return json.loads(raw) if raw else default

    def _write(self, key: str, value: Any) -> None:
        self._settings.set(key, json.dumps(value, ensure_ascii=False))

    def _seal(self, value: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(encrypt_credentials(self._secrets, value)).decode()

    def _open(self, value: str) -> dict[str, Any]:
        return decrypt_credentials(self._secrets, base64.urlsafe_b64decode(value))

    def _pending(self) -> list[dict[str, Any]]:
        return [
            row
            for row in self._read(_PAIRINGS_KEY, [])
            if int(row["expires_at"]) > int(time.time())
        ]

    def _rate_limit(self, key: str, limit: int) -> None:
        now = int(time.time())
        minute, count = self._attempts.get(key, (now // 60, 0))
        count = count + 1 if minute == now // 60 else 1
        self._attempts[key] = (now // 60, count)
        if len(self._attempts) > 1024:
            self._attempts = {k: v for k, v in self._attempts.items() if v[0] == now // 60}
        if count > limit:
            raise OctopError(ErrorCode.AUTH_FAILED, "mobile pairing rate limit reached", status=429)

    def _host_fingerprint(self) -> str:
        key = self._secrets.get_or_create(
            "mobile_access.host_identity", lambda: secrets.token_bytes(32)
        )
        return hashlib.sha256(key).hexdigest()

    async def begin_pairing(self, *, name: str, platform: str, network_key: str) -> dict[str, Any]:
        async with self._lock:
            return await asyncio.to_thread(self._begin_pairing, name, platform, network_key)

    def _begin_pairing(self, name: str, platform: str, network_key: str) -> dict[str, Any]:
        self._rate_limit(f"begin:{network_key}", 6)
        self._rate_limit("begin:global", 30)
        rows = self._pending()
        if len(rows) >= 64:
            raise OctopError(ErrorCode.AUTH_FAILED, "mobile pairing capacity reached", status=429)
        name = name.strip()[:80]
        if not name or platform not in {"ios", "android", "web"}:
            raise ValueError("mobile_access.invalid_device")
        code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))
        while any(row["code_hash"] == _hash(code) for row in rows):
            code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))
        credential = secrets.token_urlsafe(32)
        expires = int(time.time()) + PAIRING_TTL
        rows.append(
            {
                "pairing_id": new_ulid(),
                "code_hash": _hash(code),
                "credential_hash": _hash(credential),
                "name": name,
                "platform": platform,
                "expires_at": expires,
                "state": "pending",
            }
        )
        self._write(_PAIRINGS_KEY, rows)
        return {
            "pairing_secret": credential,
            "user_code": f"{code[:4]}-{code[4:]}",
            "expires_at": expires,
            "host_fingerprint": self._host_fingerprint(),
            "interval": 3,
        }

    async def inspect_pairing(self, *, user_id: int, code: str) -> dict[str, Any]:
        async with self._lock:
            return await asyncio.to_thread(self._inspect_pairing, user_id, code)

    def _inspect_pairing(self, user_id: int, code: str) -> dict[str, Any]:
        self._rate_limit(f"inspect:{user_id}", 12)
        digest = _hash(normalize_code(code))
        row = next(
            (r for r in self._pending() if secrets.compare_digest(r["code_hash"], digest)), None
        )
        if row is None or row["state"] != "pending":
            raise _error()
        return {
            "name": row["name"],
            "platform": row["platform"],
            "expires_at": row["expires_at"],
            "host_fingerprint": self._host_fingerprint(),
        }

    async def approve_pairing(
        self, *, user_id: int, code: str, scopes: list[str]
    ) -> dict[str, Any]:
        selected = normalize_scopes(scopes)
        async with self._lock:
            return await asyncio.to_thread(self._approve_pairing, user_id, code, selected)

    def _approve_pairing(self, user_id: int, code: str, scopes: list[str]) -> dict[str, Any]:
        self._rate_limit(f"approve:{user_id}", 12)
        rows = self._pending()
        digest = _hash(normalize_code(code))
        row = next((r for r in rows if secrets.compare_digest(r["code_hash"], digest)), None)
        if row is None or row["state"] != "pending":
            raise _error()
        devices = self._read(f"mobile_access.devices.{user_id}", [])
        if (
            sum(not r.get("revoked_at") and r["expires_at"] > int(time.time()) for r in devices)
            >= 20
        ):
            raise OctopError(ErrorCode.FORBIDDEN, "mobile device limit reached")
        device_id = new_ulid()
        token = f"{TOKEN_PREFIX}{user_id}.{device_id}.{secrets.token_urlsafe(32)}"
        now = int(time.time())
        device = {
            "device_id": device_id,
            "name": row["name"],
            "platform": row["platform"],
            "scopes": scopes,
            "token_hash": _hash(token),
            "created_at": now,
            "expires_at": now + DEVICE_TTL,
            "revoked_at": None,
        }
        devices.append(device)
        self._write(f"mobile_access.devices.{user_id}", devices)
        row.update(
            {
                "state": "approved",
                "user_id": user_id,
                "device_id": device_id,
                "result": self._seal(
                    {
                        "access_token": token,
                        "expires_at": device["expires_at"],
                        "device_id": device_id,
                        "scopes": scopes,
                    }
                ),
            }
        )
        self._write(_PAIRINGS_KEY, rows)
        return self._public_device(device)

    async def exchange_pairing(self, *, pairing_secret: str, network_key: str) -> dict[str, Any]:
        async with self._lock:
            return await asyncio.to_thread(self._exchange_pairing, pairing_secret, network_key)

    def _exchange_pairing(self, credential: str, network_key: str) -> dict[str, Any]:
        self._rate_limit(f"poll:{network_key}", 120)
        digest = _hash(credential)
        rows = self._pending()
        row = next((r for r in rows if secrets.compare_digest(r["credential_hash"], digest)), None)
        if row is None:
            raise _error()
        if row["state"] == "pending":
            return {"status": "pending", "expires_at": row["expires_at"]}
        session = self._open(row["result"])
        # A revoked device cannot be resurrected by retrying an old exchange.
        self.authenticate(session["access_token"])
        return {"status": "approved", **session, "host_fingerprint": self._host_fingerprint()}

    def authenticate(self, token: str) -> DeviceSession:
        if not token.startswith(TOKEN_PREFIX) or len(token) > 180:
            raise _error()
        is_share = token.startswith(SHARE_PREFIX)
        prefix = SHARE_PREFIX if is_share else TOKEN_PREFIX
        parts = token[len(prefix) :].split(".")
        if len(parts) != 3 or not parts[0].isdigit() or not re.fullmatch(r"[A-Z0-9]{26}", parts[1]):
            raise _error()
        user_id = int(parts[0])
        if user_id <= 0:
            raise _error()
        rows = self._read(f"mobile_access.devices.{user_id}", [])
        row = next((r for r in rows if r["device_id"] == parts[1]), None)
        if row is None or row.get("revoked_at") or row["expires_at"] <= int(time.time()):
            raise _error()
        verifier = row.get("share_hash") if is_share else row["token_hash"]
        if not verifier or not secrets.compare_digest(str(verifier), _hash(token)):
            raise _error()
        scopes = tuple(
            scope for scope in row["scopes"] if not is_share or scope in {"chat", "files", "tasks"}
        )
        return DeviceSession(
            user_id, parts[1], scopes, int(row["expires_at"]), "share" if is_share else "device"
        )

    async def share_grant(self, token: str) -> dict[str, Any]:
        async with self._lock:
            return await asyncio.to_thread(self._share_grant, token)

    def _share_grant(self, token: str) -> dict[str, Any]:
        session = self.authenticate(token)
        if session.kind != "device" or "chat" not in session.scopes:
            raise OctopError(
                ErrorCode.FORBIDDEN, "a primary chat-capable device session is required"
            )
        secret = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"octop-mobile-share-credential-salt-v1",
            info=b"octop/mobile/share-login/v1",
        ).derive(token.encode())
        credential = f"{SHARE_PREFIX}{session.user_id}.{session.device_id}.{base64.urlsafe_b64encode(secret).decode().rstrip('=')}"
        key = f"mobile_access.devices.{session.user_id}"
        rows = self._read(key, [])
        row = next(row for row in rows if row["device_id"] == session.device_id)
        digest = _hash(credential)
        if row.get("share_hash") != digest:
            row["share_hash"] = digest
            self._write(key, rows)
        return {
            "access_token": credential,
            "expires_at": session.expires_at,
            "scopes": sorted(set(session.scopes) & {"chat", "files", "tasks"}),
        }

    def _public_device(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            key: row.get(key)
            for key in (
                "device_id",
                "name",
                "platform",
                "scopes",
                "created_at",
                "expires_at",
                "revoked_at",
            )
        } | {
            "push_enabled": bool(row.get("push")),
            "notification_preferences": self._preferences(row),
        }

    async def list_devices(self, user_id: int) -> list[dict[str, Any]]:
        rows = await asyncio.to_thread(self._read, f"mobile_access.devices.{user_id}", [])
        return [self._public_device(row) for row in rows]

    async def revoke(self, *, user_id: int, device_id: str) -> None:
        async with self._lock:
            await asyncio.to_thread(self._revoke, user_id, device_id)

    def _revoke(self, user_id: int, device_id: str) -> None:
        key = f"mobile_access.devices.{user_id}"
        rows = self._read(key, [])
        row = next((r for r in rows if r["device_id"] == device_id), None)
        if row is None:
            raise OctopError(ErrorCode.NOT_FOUND, "mobile device not found")
        row["revoked_at"] = int(time.time())
        row.pop("push", None)
        row.pop("activities", None)
        with self._presence_lock:
            self._foreground.pop(device_id, None)
            self._presence = {
                key: value for key, value in self._presence.items() if value[0] != device_id
            }
        self._write(key, rows)

    async def register_push(self, *, token: str, platform: str, push_token: str) -> None:
        if platform not in {"apns", "fcm"} or not re.fullmatch(
            r"[A-Za-z0-9:_\-]{16,4096}", push_token
        ):
            raise ValueError("mobile_access.invalid_push_token")
        async with self._lock:
            await asyncio.to_thread(self._register_push, token, platform, push_token)

    def _register_push(self, token: str, platform: str, push_token: str) -> None:
        session = self.authenticate(token)
        if "notifications" not in session.scopes:
            raise OctopError(ErrorCode.FORBIDDEN, "mobile notifications scope required")
        key = f"mobile_access.devices.{session.user_id}"
        rows = self._read(key, [])
        row = next(r for r in rows if r["device_id"] == session.device_id)
        row["push"] = self._seal({"platform": platform, "token": push_token})
        self._write(key, rows)

    async def retire_push(self, user_id: int, device_id: str, expected_token: str) -> None:
        async with self._lock:
            await asyncio.to_thread(self._retire_push, user_id, device_id, expected_token)

    def _retire_push(self, user_id: int, device_id: str, expected_token: str) -> None:
        key = f"mobile_access.devices.{user_id}"
        rows = self._read(key, [])
        row = next((row for row in rows if row["device_id"] == device_id), None)
        if row and row.get("push") and self._open(row["push"]).get("token") == expected_token:
            row.pop("push", None)
            self._write(key, rows)

    async def retire_activity(
        self, user_id: int, device_id: str, activity_id: str, expected_token: str
    ) -> None:
        async with self._lock:
            await asyncio.to_thread(
                self._retire_activity, user_id, device_id, activity_id, expected_token
            )

    def _retire_activity(
        self, user_id: int, device_id: str, activity_id: str, expected_token: str
    ) -> None:
        key = f"mobile_access.devices.{user_id}"
        rows = self._read(key, [])
        row = next((row for row in rows if row["device_id"] == device_id), None)
        if row and row.get("activities"):
            activities = self._open(row["activities"])
            if activities.get(activity_id, {}).get("token") == expected_token:
                activities.pop(activity_id)
                row["activities"] = self._seal(activities)
                self._write(key, rows)

    def _preferences(self, row: dict[str, Any]) -> dict[str, Any]:
        preferences: dict[str, Any] = {
            "level": "all",
            "muted_until": None,
            "sound": True,
            "preview": False,
            "muted_agent_ids": [],
        }
        preferences.update(row.get("notification_preferences") or {})
        with self._presence_lock:
            preferences["foreground"] = self._foreground.get(row["device_id"], 0) > int(time.time())
        return preferences

    async def update_notification_preferences(
        self, *, token: str, changes: dict[str, Any]
    ) -> dict[str, Any]:
        if set(changes) - {
            "level",
            "muted_until",
            "sound",
            "preview",
            "muted_agent_ids",
            "foreground",
        }:
            raise ValueError("mobile_access.invalid_notification_preferences")
        if "level" in changes and changes["level"] not in {"all", "needs-me", "none"}:
            raise ValueError("mobile_access.invalid_notification_preferences")
        if (
            "muted_until" in changes
            and changes["muted_until"] is not None
            and (
                not isinstance(changes["muted_until"], int)
                or isinstance(changes["muted_until"], bool)
                or changes["muted_until"] < 0
            )
        ):
            raise ValueError("mobile_access.invalid_notification_preferences")
        for key in ("sound", "preview", "foreground"):
            if key in changes and not isinstance(changes[key], bool):
                raise ValueError("mobile_access.invalid_notification_preferences")
        ids = changes.get("muted_agent_ids", [])
        if (
            not isinstance(ids, list)
            or len(ids) > 200
            or any(not isinstance(item, str) or len(item) > 200 for item in ids)
        ):
            raise ValueError("mobile_access.invalid_notification_preferences")
        async with self._lock:
            return await asyncio.to_thread(
                self._update_notification_preferences, token, dict(changes)
            )

    def _update_notification_preferences(
        self, token: str, changes: dict[str, Any]
    ) -> dict[str, Any]:
        session = self.authenticate(token)
        if "notifications" not in session.scopes:
            raise OctopError(ErrorCode.FORBIDDEN, "mobile notifications scope required")
        key = f"mobile_access.devices.{session.user_id}"
        rows = self._read(key, [])
        row = next(row for row in rows if row["device_id"] == session.device_id)
        if "foreground" in changes:
            with self._presence_lock:
                if changes.pop("foreground"):
                    self._foreground[session.device_id] = int(time.time()) + 30
                else:
                    self._foreground.pop(session.device_id, None)
        if changes:
            preferences = self._preferences(row)
            preferences.pop("foreground", None)
            preferences.update(changes)
            row["notification_preferences"] = preferences
            self._write(key, rows)
        return self._preferences(row)

    def note_presence(
        self, *, user_id: int, client_id: str, device_id: str | None, active: bool
    ) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", client_id):
            raise ValueError("mobile_access.invalid_presence")
        now = int(time.time())
        with self._presence_lock:
            self._presence = {key: value for key, value in self._presence.items() if value[1] > now}
            if active and len(self._presence) < 4096:
                self._presence[(user_id, client_id)] = (device_id, now + 30)
            else:
                self._presence.pop((user_id, client_id), None)

    def active_elsewhere(self, user_id: int, device_id: str) -> bool:
        now = int(time.time())
        with self._presence_lock:
            return any(
                owner == user_id and source != device_id and expires > now
                for (owner, _), (source, expires) in self._presence.items()
            )

    async def push_targets(self, user_id: int) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._push_targets, user_id)

    def _push_targets(self, user_id: int) -> list[dict[str, Any]]:
        rows = self._read(f"mobile_access.devices.{user_id}", [])
        return [
            {
                **self._open(row["push"]),
                "device_id": row["device_id"],
                "notification_key": notification_key(row["token_hash"]),
                "preferences": self._preferences(row),
            }
            for row in rows
            if row.get("push")
            and not row.get("revoked_at")
            and row["expires_at"] > int(time.time())
            and "notifications" in row["scopes"]
        ]

    async def register_activity(
        self, *, token: str, activity_id: str, thread_id: str, push_token: str
    ) -> None:
        if (
            not re.fullmatch(r"[A-Za-z0-9-]{1,128}", activity_id)
            or not thread_id
            or len(thread_id) > 256
            or not re.fullmatch(r"[a-fA-F0-9]{32,256}", push_token)
        ):
            raise ValueError("mobile_access.invalid_activity")
        async with self._lock:
            await asyncio.to_thread(
                self._register_activity, token, activity_id, thread_id, push_token
            )

    def _register_activity(
        self, token: str, activity_id: str, thread_id: str, push_token: str
    ) -> None:
        session = self.authenticate(token)
        if "notifications" not in session.scopes:
            raise OctopError(ErrorCode.FORBIDDEN, "mobile notifications scope required")
        key = f"mobile_access.devices.{session.user_id}"
        rows = self._read(key, [])
        row = next(r for r in rows if r["device_id"] == session.device_id)
        activities = self._open(row["activities"]) if row.get("activities") else {}
        activities = {
            key: value
            for key, value in activities.items()
            if value["expires_at"] > int(time.time())
        }
        if activity_id not in activities and len(activities) >= 8:
            raise OctopError(ErrorCode.FORBIDDEN, "mobile live activity limit reached")
        activities[activity_id] = {
            "thread_id": thread_id,
            "token": push_token,
            "expires_at": int(time.time()) + 8 * 3600,
        }
        row["activities"] = self._seal(activities)
        self._write(key, rows)

    async def remove_activities(self, *, token: str) -> None:
        async with self._lock:
            await asyncio.to_thread(self._remove_activities, token)

    def _remove_activities(self, token: str) -> None:
        session = self.authenticate(token)
        key = f"mobile_access.devices.{session.user_id}"
        rows = self._read(key, [])
        row = next(r for r in rows if r["device_id"] == session.device_id)
        if row.pop("activities", None) is not None:
            self._write(key, rows)

    async def activity_targets(self, user_id: int, thread_id: str) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._activity_targets, user_id, thread_id)

    def _activity_targets(self, user_id: int, thread_id: str) -> list[dict[str, Any]]:
        targets = []
        for row in self._read(f"mobile_access.devices.{user_id}", []):
            if (
                row.get("revoked_at")
                or row["expires_at"] <= int(time.time())
                or "notifications" not in row["scopes"]
                or not row.get("activities")
                or self._preferences(row).get("foreground")
            ):
                continue
            for activity_id, activity in self._open(row["activities"]).items():
                if activity["thread_id"] == thread_id and activity["expires_at"] > int(time.time()):
                    targets.append(
                        {**activity, "device_id": row["device_id"], "activity_id": activity_id}
                    )
        return targets


def service_for(server: Any) -> MobileAccessService:
    service = getattr(server, "_mobile_access_service", None)
    if not isinstance(service, MobileAccessService):
        service = MobileAccessService(server.services.settings_repo, server.services.secret_repo)
        server._mobile_access_service = service
    return service
