"""Signed navigation and single-use confirmation for a particular task attempt.

A link is never an execution capability: opening it only permits preparing an
owned-device confirmation. Mutations require a fresh authenticated POST.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from octop.infra.errors import ErrorCode, OctopError
from octop.infra.mobile_access.access import effective_device_scopes
from octop.infra.mobile_access.service import DeviceSession, service_for
from octop.infra.users.permissions import user_has_permission


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


class MobileTaskActions:
    def __init__(self, server: Any) -> None:
        self.server = server
        self.access = service_for(server)
        self._lock = asyncio.Lock()

    async def _session(self, token: str) -> DeviceSession:
        session = await asyncio.to_thread(self.access.authenticate, token)
        owner = await asyncio.to_thread(self.server.user_manager.get_by_id, session.user_id)
        if (
            session.kind != "device"
            or owner is None
            or "tasks" not in effective_device_scopes(owner, session.scopes)
            or not user_has_permission(owner, "tasks")
        ):
            raise OctopError(ErrorCode.FORBIDDEN, "mobile_access.action_forbidden")
        return session

    async def _task(self, session: DeviceSession, task_id: str, attempt: int) -> dict[str, Any]:
        task: dict[str, Any] = await self.server.task_manager.detail(session.user_id, task_id)
        if (
            task.get("attempt") != attempt
            or task.get("state") not in {"queued", "running", "waiting", "paused"}
            or task.get("archived")
        ):
            raise OctopError(ErrorCode.FORBIDDEN, "mobile_access.action_stale", status=409)
        return task

    async def _key(self) -> bytes:
        return await asyncio.to_thread(
            self.server.services.secret_repo.get_or_create,
            "mobile_access.task_navigation.v1",
            lambda: secrets.token_bytes(32),
        )

    async def navigation(self, token: str, task_id: str, attempt: int) -> str:
        session = await self._session(token)
        await self._task(session, task_id, attempt)
        body = {
            "v": 1,
            "user": session.user_id,
            "device": session.device_id,
            "host": await asyncio.to_thread(self.access._host_fingerprint),
            "task": task_id,
            "attempt": attempt,
            "operation": "cancel",
            "expires": min(session.expires_at, int(time.time()) + 8 * 3600),
        }
        payload = _encode(json.dumps(body, separators=(",", ":"), sort_keys=True).encode())
        signature = _encode(hmac.digest(await self._key(), payload.encode(), "sha256"))
        return payload + "." + signature

    async def _navigation(
        self, token: str, navigation: str
    ) -> tuple[DeviceSession, dict[str, Any]]:
        session = await self._session(token)
        try:
            payload, signature = navigation.split(".")
            if len(navigation) > 2048 or not hmac.compare_digest(
                _encode(hmac.digest(await self._key(), payload.encode(), "sha256")), signature
            ):
                raise ValueError
            body = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            if not isinstance(body, dict) or (
                body.get("v") != 1
                or body.get("user") != session.user_id
                or body.get("device") != session.device_id
                or body.get("operation") != "cancel"
                or body.get("host") != await asyncio.to_thread(self.access._host_fingerprint)
                or not isinstance(body.get("expires"), int)
                or body["expires"] <= int(time.time())
                or not isinstance(body.get("task"), str)
                or not isinstance(body.get("attempt"), int)
            ):
                raise ValueError
        except (ValueError, TypeError, KeyError):
            raise OctopError(ErrorCode.FORBIDDEN, "mobile_access.action_invalid") from None
        return session, body

    async def prepare(self, token: str, navigation: str) -> dict[str, Any]:
        session, target = await self._navigation(token, navigation)
        task = await self._task(session, target["task"], target["attempt"])
        proof = secrets.token_urlsafe(32)
        summary = {
            "task_id": target["task"],
            "attempt": target["attempt"],
            "operation": "cancel",
            "title": str(task.get("title") or "")[:300],
            "agent_id": str(task.get("agent_id") or ""),
        }
        # Title+target digest means an edited operation cannot be confirmed by an old sheet.
        digest = _digest(json.dumps(summary, sort_keys=True, separators=(",", ":")))
        record = {
            "device": session.device_id,
            "target": target,
            "digest": digest,
            "expires": min(session.expires_at, int(time.time()) + 120),
        }
        async with self._lock:
            key = f"mobile_access.task_actions.{session.user_id}"
            records = await asyncio.to_thread(self.access._read, key, {})
            records = {k: v for k, v in records.items() if v["expires"] > int(time.time())}
            if len(records) >= 32:
                raise OctopError(ErrorCode.FORBIDDEN, "mobile_access.action_limit")
            records[_digest(proof)] = record
            await asyncio.to_thread(self.access._write, key, records)
        return {**summary, "confirmation": proof, "expires_at": record["expires"]}

    async def execute(self, token: str, proof: str) -> dict[str, str]:
        session = await self._session(token)
        async with self._lock:
            key = f"mobile_access.task_actions.{session.user_id}"
            records = await asyncio.to_thread(self.access._read, key, {})
            record = records.get(_digest(proof))
            if (
                not record
                or record["device"] != session.device_id
                or record["expires"] <= int(time.time())
            ):
                raise OctopError(ErrorCode.FORBIDDEN, "mobile_access.action_invalid")
            target = record["target"]
            task = await self._task(session, target["task"], target["attempt"])
            summary = {
                "task_id": target["task"],
                "attempt": target["attempt"],
                "operation": "cancel",
                "title": str(task.get("title") or "")[:300],
                "agent_id": str(task.get("agent_id") or ""),
            }
            if (
                _digest(json.dumps(summary, sort_keys=True, separators=(",", ":")))
                != record["digest"]
            ):
                raise OctopError(ErrorCode.FORBIDDEN, "mobile_access.action_stale", status=409)
            # Consume before mutation: a lost response must never cause an automatic replay.
            del records[_digest(proof)]
            await asyncio.to_thread(self.access._write, key, records)
            # Re-check revocation following I/O; TaskManager checks ownership and CAS attempt.
            await self._session(token)
            await self.server.task_manager.action(
                session.user_id, target["task"], "cancel", expected_attempt=target["attempt"]
            )
        return {"status": "cancelled"}


def actions_for(server: Any) -> MobileTaskActions:
    service = getattr(server, "_mobile_task_actions", None)
    if not isinstance(service, MobileTaskActions):
        service = MobileTaskActions(server)
        server._mobile_task_actions = service
    return service
