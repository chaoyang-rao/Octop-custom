"""Versioned HKDF-SHA256 / AES-GCM envelopes for independent native clients."""

from __future__ import annotations

import base64
import json
import secrets
import struct
import time
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

SALT = b"octop-mobile-notifications-salt-v1"
INFO = b"octop/mobile/notification-content/v1"
AAD_FIELDS = (
    "seal_version",
    "host_fingerprint",
    "device_id",
    "agent_id",
    "thread_id",
    "issued_at",
    "expires_at",
    "message_id",
)


def notification_key(token_hash: str) -> bytes:
    """A distinct message key, never usable as the device login credential."""
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=SALT, info=INFO).derive(
        bytes.fromhex(token_hash)
    )


def envelope_aad(envelope: dict[str, str]) -> bytes:
    fields = [envelope[name].encode("utf-8") for name in AAD_FIELDS]
    return b"".join(struct.pack(">I", len(value)) + value for value in fields)


def seal_notification(
    key: bytes, *, host: str, device: str, payload: dict[str, Any]
) -> dict[str, str]:
    routing = payload.get("octop") or {}
    now = int(routing.get("occurred_at") or time.time())
    envelope = {
        "seal_version": "1",
        "host_fingerprint": host,
        "device_id": device,
        "agent_id": str(routing.get("agent_id") or ""),
        "thread_id": str(routing.get("thread_id") or ""),
        "issued_at": str(now),
        "expires_at": str(now + 300),
        "message_id": secrets.token_hex(16),
    }
    nonce = secrets.token_bytes(12)
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    encrypted = nonce + AESGCM(key).encrypt(nonce, body, envelope_aad(envelope))
    envelope["sealed"] = base64.urlsafe_b64encode(encrypted).decode()
    return envelope


def open_notification(
    key: bytes,
    envelope: dict[str, str],
    *,
    host: str,
    device: str,
    now: int | None = None,
    seen: set[str] | None = None,
) -> dict[str, Any]:
    """Reference verifier for cross-language protocol vectors and migrations."""
    if (
        envelope.get("seal_version") != "1"
        or envelope.get("host_fingerprint") != host
        or envelope.get("device_id") != device
    ):
        raise ValueError("notification recipient mismatch")
    encrypted = base64.b64decode(envelope["sealed"], altchars=b"-_", validate=True)
    value = json.loads(AESGCM(key).decrypt(encrypted[:12], encrypted[12:], envelope_aad(envelope)))
    current = int(time.time()) if now is None else now
    issued, expiry = int(envelope["issued_at"]), int(envelope["expires_at"])
    if issued > current + 60 or expiry <= current or not 0 < expiry - issued <= 300:
        raise ValueError("notification expired or issued in the future")
    message_id = envelope["message_id"]
    if seen is not None:
        if message_id in seen:
            raise ValueError("notification replay")
        seen.add(message_id)
    if not isinstance(value, dict):
        raise ValueError("invalid notification payload")
    routing = value.get("octop") or {}
    if (
        str(routing.get("agent_id") or "") != envelope["agent_id"]
        or str(routing.get("thread_id") or "") != envelope["thread_id"]
    ):
        raise ValueError("notification routing mismatch")
    return value
