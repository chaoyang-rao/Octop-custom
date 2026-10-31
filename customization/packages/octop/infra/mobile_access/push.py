"""Privacy-minimal APNS and FCM delivery using each vendor's official API."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from collections.abc import Callable
from typing import Any

import httpx
import jwt

from octop.i18n import tr
from octop.infra.mobile_access.seal import seal_notification
from octop.infra.mobile_access.service import MobileAccessService
from octop.infra.mobile_access.summary import redact_summary
from octop.infra.utils.locale import DEFAULT_LOCALE

logger = logging.getLogger(__name__)

_ALLOWED_EVENTS = frozenset(
    {
        "dashboard_push",
        "turn.started",
        "turn.resumed",
        "turn.completed",
        "turn.ended",
        "approval.required",
        "task.updated",
    }
)


class PushTargetGone(Exception):
    """The provider confirmed this registration no longer reaches the app."""


class MobilePushService:
    def __init__(
        self,
        access: MobileAccessService,
        user_locale: Callable[[int], str | None] | None = None,
        preview_source: Callable[[int, dict[str, str]], str | None] | None = None,
        label_source: Callable[[int, dict[str, str]], str] | None = None,
    ) -> None:
        self.access = access
        self._user_locale = user_locale or (lambda _: DEFAULT_LOCALE)
        self._preview_source = preview_source
        self._label_source = label_source
        self._pending: set[asyncio.Task[None]] = set()
        self._limit = asyncio.Semaphore(2)
        self._auth_cache: dict[str, tuple[int, str]] = {}

    async def configure(self, provider: str, config: dict[str, Any] | None) -> None:
        if provider not in {"apns", "fcm"}:
            raise ValueError("mobile_access.invalid_push_provider")
        if config is not None:
            try:
                if provider == "apns":
                    if not re.fullmatch(
                        r"[A-Z0-9]{10}", str(config["team_id"])
                    ) or not re.fullmatch(r"[A-Z0-9]{10}", str(config["key_id"])):
                        raise ValueError()
                    if not re.fullmatch(
                        r"[A-Za-z0-9.-]{3,255}", str(config["topic"])
                    ) or not isinstance(config.get("sandbox", True), bool):
                        raise ValueError()
                    jwt.encode(
                        {"iss": config["team_id"], "iat": int(time.time())},
                        config["private_key"],
                        algorithm="ES256",
                        headers={"kid": config["key_id"]},
                    )
                else:
                    if not re.fullmatch(
                        r"[a-z][a-z0-9-]{4,62}", str(config["project_id"])
                    ) or not str(config["client_email"]).endswith(".iam.gserviceaccount.com"):
                        raise ValueError()
                    jwt.encode(
                        {"iss": config["client_email"], "iat": int(time.time())},
                        config["private_key"],
                        algorithm="RS256",
                    )
            except Exception:
                raise ValueError("mobile_access.invalid_push_configuration") from None
        async with self.access._lock:
            await asyncio.to_thread(self._store_config, provider, config)
        self._auth_cache.clear()

    def _store_config(self, provider: str, config: dict[str, Any] | None) -> None:
        self.access._write(
            f"mobile_access.push.{provider}", self.access._seal(config) if config else None
        )

    async def configuration_status(self) -> dict[str, bool]:
        return {
            provider: bool(
                await asyncio.to_thread(self.access._read, f"mobile_access.push.{provider}", None)
            )
            for provider in ("apns", "fcm")
        }

    @staticmethod
    def _alert_event(event: dict[str, str]) -> bool:
        return (
            event.get("notify") != "false"
            and event.get("type") not in {"turn.started", "turn.resumed"}
            and not (
                event.get("type") == "task.updated"
                and event.get("status") in {"queued", "running", "working"}
            )
        )

    def _eligible_alert(self, user_id: int, event: dict[str, str], target: dict[str, Any]) -> bool:
        preferences = target.get("preferences") or {}
        if (
            not self._alert_event(event)
            or preferences.get("level") == "none"
            or preferences.get("foreground")
        ):
            return False
        mute = preferences.get("muted_until")
        if mute == 0 or (isinstance(mute, int) and mute > int(time.time())):
            return False
        if event.get("agent_id") in preferences.get("muted_agent_ids", []):
            return False
        if self.access.active_elsewhere(user_id, str(target.get("device_id") or "")):
            return False
        needs_me = event.get("type") == "approval.required" or event.get("status") in {
            "waiting",
            "failed",
            "interrupted",
        }
        return preferences.get("level") != "needs-me" or needs_me

    async def emit(self, user_id: int, frame: dict[str, Any]) -> None:
        if frame.get("type") not in _ALLOWED_EVENTS or len(self._pending) >= 64:
            return
        # No prompt, answer, tool argument or attachment content enters push payloads.
        event = {
            key: str(frame[key])[:160]
            for key in ("type", "thread_id", "agent_id", "task_id", "task_attempt", "status")
            if frame.get(key) is not None
        }
        event["occurred_at"] = str(int(time.time()))
        if isinstance(frame.get("notify"), bool):
            event["notify"] = "true" if frame["notify"] else "false"
        candidates = await self.access.push_targets(user_id) if self._alert_event(event) else []
        targets = [target for target in candidates if self._eligible_alert(user_id, event, target)]
        activities = (
            await self.access.activity_targets(user_id, event["thread_id"])
            if event.get("thread_id") and event.get("type") != "dashboard_push"
            else []
        )
        if not targets and not activities:
            return
        event["server_fingerprint"] = await asyncio.to_thread(self.access._host_fingerprint)
        if len(self._pending) >= 64:
            return
        preview = None
        if any(target.get("preferences", {}).get("preview") for target in targets):
            candidate = (
                await asyncio.to_thread(self._preview_source, user_id, event)
                if self._preview_source is not None
                else None
            )
            if (
                candidate is None
                and frame.get("type") == "dashboard_push"
                and isinstance(frame.get("text"), str)
            ):
                candidate = frame["text"]
            preview = redact_summary(candidate) if isinstance(candidate, str) else None
        title = (
            await asyncio.to_thread(self._label_source, user_id, event)
            if targets and self._label_source is not None
            else "Octop"
        )
        task = asyncio.create_task(
            self._deliver(user_id, event, preview, title), name="octop-mobile-push"
        )
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def stop(self) -> None:
        tasks = list(self._pending)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _config(self, provider: str) -> dict[str, Any] | None:
        value = await asyncio.to_thread(self.access._read, f"mobile_access.push.{provider}", None)
        return await asyncio.to_thread(self.access._open, value) if value else None

    async def _deliver(
        self, user_id: int, event: dict[str, str], preview: str | None = None, title: str = "Octop"
    ) -> None:
        async with self._limit:
            if int(event.get("occurred_at") or time.time()) + 300 <= int(time.time()):
                return
            locale = await asyncio.to_thread(self._user_locale, user_id)
            if locale is None:
                return
            targets = await self.access.push_targets(user_id)
            for target in targets:
                provider = target["platform"]
                config = await self._config(provider)
                if config is None:
                    continue
                try:
                    announce = self._eligible_alert(user_id, event, target)
                    preferences = target.get("preferences") or {}
                    summary = preview if preferences.get("preview") else None
                    sound = bool(preferences.get("sound", True))
                    recipient = str(target.get("device_id") or "")
                    encryption_key = target.get("notification_key")
                    if announce and provider == "apns":
                        await self._send_apns(
                            config,
                            target["token"],
                            event,
                            locale=locale,
                            summary=summary,
                            sound=sound,
                            title=title,
                            encryption_key=encryption_key,
                            recipient=recipient,
                        )
                    elif announce and provider == "fcm":
                        await self._send_fcm(
                            config,
                            target["token"],
                            event,
                            locale=locale,
                            summary=summary,
                            sound=sound,
                            title=title,
                            encryption_key=encryption_key,
                            recipient=recipient,
                        )
                except asyncio.CancelledError:
                    raise
                except PushTargetGone:
                    await self.access.retire_push(
                        user_id, str(target.get("device_id") or ""), target["token"]
                    )
                except Exception as exc:
                    # Provider errors can contain device tokens or private key text.
                    # Failure must not interrupt the agent's response or leak credentials.
                    status = (
                        exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                    )
                    if status == 410:
                        await self.access.retire_push(
                            user_id, str(target.get("device_id") or ""), target["token"]
                        )
                    logger.warning("Mobile push delivery failed for %s (HTTP %s)", provider, status)
                    continue

            if event.get("thread_id") and event.get("type") != "dashboard_push":
                config = await self._config("apns")
                if config:
                    for target in await self.access.activity_targets(user_id, event["thread_id"]):
                        try:
                            await self._send_apns(
                                config, target["token"], event, live_activity=True, locale=locale
                            )
                        except asyncio.CancelledError:
                            raise
                        except httpx.HTTPStatusError as exc:
                            if exc.response.status_code == 410:
                                await self.access.retire_activity(
                                    user_id,
                                    target["device_id"],
                                    target["activity_id"],
                                    target["token"],
                                )
                        except Exception:
                            continue
                        else:
                            if event.get("type") in {"turn.ended", "turn.completed"} or event.get(
                                "status"
                            ) in {"completed", "failed", "cancelled", "interrupted"}:
                                await self.access.retire_activity(
                                    user_id,
                                    target["device_id"],
                                    target["activity_id"],
                                    target["token"],
                                )

    def _cached(self, config: dict[str, Any]) -> tuple[str, str | None]:
        key = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
        stored = self._auth_cache.get(key)
        return key, stored[1] if stored and stored[0] > int(time.time()) + 60 else None

    async def _send_apns(
        self,
        config: dict[str, Any],
        device_token: str,
        event: dict[str, str],
        *,
        live_activity: bool = False,
        locale: str = DEFAULT_LOCALE,
        summary: str | None = None,
        sound: bool = True,
        title: str = "Octop",
        encryption_key: bytes | None = None,
        recipient: str = "",
    ) -> None:
        if not re.fullmatch(r"[a-fA-F0-9]{32,256}", device_token):
            return
        key, authorization = self._cached(config)
        if authorization is None:
            authorization = jwt.encode(
                {"iss": config["team_id"], "iat": int(time.time())},
                config["private_key"],
                algorithm="ES256",
                headers={"kid": config["key_id"]},
            )
            self._auth_cache[key] = (int(time.time()) + 1800, authorization)
        host = "api.sandbox.push.apple.com" if config.get("sandbox", True) else "api.push.apple.com"
        message_key = (
            "mobile_access.push_needs_input"
            if event.get("type") == "approval.required" or event.get("status") == "waiting"
            else "mobile_access.push_failed"
            if event.get("status") in {"failed", "interrupted"}
            else "mobile_access.push_activity"
        )
        inner = {
            "title": title[:80],
            "body": summary or tr(message_key, locale),
            "octop": {**event, "device_id": recipient},
            "sound": sound,
        }
        envelope = (
            seal_notification(
                encryption_key,
                host=event.get("server_fingerprint", ""),
                device=recipient,
                payload=inner,
            )
            if encryption_key is not None and recipient
            else {}
        )
        payload = {
            "aps": {
                "alert": {"title": "Octop", "body": tr("mobile_access.push_activity", locale)},
                "mutable-content": 1,
                **({"sound": "default"} if sound else {}),
            },
            **envelope,
        }
        topic = config["topic"]
        push_type = "alert"
        if live_activity:
            now = int(time.time())
            approval = event.get("type") == "approval.required" or event.get("status") == "waiting"
            working = event.get("status") in {"queued", "running", "working"} or event.get(
                "type"
            ) in {"turn.started", "turn.resumed"}
            status = (
                "approval"
                if approval
                else "working"
                if working
                else "failed"
                if event.get("status") in {"failed", "interrupted"}
                else "paused"
                if event.get("status") == "paused"
                else "complete"
            )
            ended = status in {"complete", "failed"}
            payload = {
                "aps": {
                    "timestamp": now,
                    "event": "end" if ended else "update",
                    "content-state": {"status": status, "updatedAt": now, "locale": locale},
                    "dismissal-date": now + 30,
                }
                if ended
                else {
                    "timestamp": now,
                    "event": "update",
                    "content-state": {"status": status, "updatedAt": now, "locale": locale},
                    "stale-date": now + 90,
                }
            }
            topic += ".push-type.liveactivity"
            push_type = "liveactivity"
        from octop.infra.utils.runtime_http2 import ensure_http2

        await asyncio.to_thread(ensure_http2)
        async with httpx.AsyncClient(http2=True, timeout=10, follow_redirects=False) as client:
            response = await client.post(
                f"https://{host}/3/device/{device_token}",
                json=payload,
                headers={
                    "authorization": f"bearer {authorization}",
                    "apns-topic": topic,
                    "apns-push-type": push_type,
                    "apns-priority": "10",
                    "apns-expiration": str(int(time.time()) + 300),
                },
            )
            response.raise_for_status()

    async def _send_fcm(
        self,
        config: dict[str, Any],
        device_token: str,
        event: dict[str, str],
        *,
        locale: str = DEFAULT_LOCALE,
        summary: str | None = None,
        sound: bool = True,
        title: str = "Octop",
        encryption_key: bytes | None = None,
        recipient: str = "",
    ) -> None:
        message_key = (
            "mobile_access.push_needs_input"
            if event.get("type") == "approval.required" or event.get("status") == "waiting"
            else "mobile_access.push_failed"
            if event.get("status") in {"failed", "interrupted"}
            else "mobile_access.push_activity"
        )
        key, authorization = self._cached(config)
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
            if authorization is None:
                now = int(time.time())
                assertion = jwt.encode(
                    {
                        "iss": config["client_email"],
                        "scope": "https://www.googleapis.com/auth/firebase.messaging",
                        "aud": "https://oauth2.googleapis.com/token",
                        "iat": now,
                        "exp": now + 3600,
                    },
                    config["private_key"],
                    algorithm="RS256",
                )
                result = await client.post(
                    "https://oauth2.googleapis.com/token",
                    data={
                        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                        "assertion": assertion,
                    },
                )
                result.raise_for_status()
                body = result.json()
                authorization = str(body["access_token"])
                self._auth_cache[key] = (
                    now + min(3600, int(body.get("expires_in", 3600))),
                    authorization,
                )
            inner = {
                "title": title[:80],
                "body": summary or tr(message_key, locale),
                "octop": event,
                "sound": sound,
            }
            envelope = (
                seal_notification(
                    encryption_key,
                    host=event.get("server_fingerprint", ""),
                    device=recipient,
                    payload=inner,
                )
                if encryption_key is not None and recipient
                else {}
            )
            response = await client.post(
                f"https://fcm.googleapis.com/v1/projects/{config['project_id']}/messages:send",
                headers={"Authorization": f"Bearer {authorization}"},
                json={
                    "message": {
                        "token": device_token,
                        "data": envelope,
                        "android": {"ttl": "300s", "priority": "high"},
                    }
                },
            )
            if response.status_code in {400, 403, 404, 410}:
                try:
                    errors = response.json().get("error", {}).get("details", [])
                    if any(
                        item.get("errorCode") in {"UNREGISTERED", "SENDER_ID_MISMATCH"}
                        for item in errors
                        if isinstance(item, dict)
                    ):
                        raise PushTargetGone()
                except ValueError:
                    pass
            response.raise_for_status()


def push_for(server: Any) -> MobilePushService:
    from octop.infra.mobile_access.service import service_for

    service = getattr(server, "_mobile_push_service", None)
    if not isinstance(service, MobilePushService):

        def locale_for(user_id: int) -> str | None:
            user = (
                server.user_manager.get_by_id(user_id) if server.user_manager is not None else None
            )
            return user.locale if user is not None else None

        def preview_for(user_id: int, event: dict[str, str]) -> str | None:
            thread_id = event.get("thread_id") or ""
            if not thread_id:
                return None
            thread = server.services.thread_repo.get(thread_id)
            if thread is None or thread.user_id != user_id:
                return None
            rows, _ = server.services.thread_message_repo.page(thread_id, limit=12)
            for row in reversed(rows):
                if row.role not in {"ai", "assistant"} or len(row.message_json) > 64000:
                    continue
                value = json.loads(row.message_json)
                data = value.get("data", value)
                if data.get("tool_calls"):
                    continue
                content = data.get("content")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    return " ".join(
                        str(block.get("text") or "")
                        for block in content
                        if isinstance(block, dict) and block.get("type") == "text"
                    )
            return None

        def label_for(user_id: int, event: dict[str, str]) -> str:
            thread = server.services.thread_repo.get(event.get("thread_id") or "")
            row = server.services.agent_repo.get(event.get("agent_id") or "")
            if row is not None and (
                row.user_id == user_id or (thread is not None and thread.user_id == user_id)
            ):
                return str(row.name or "Octop")[:80]
            return "Octop"

        service = MobilePushService(
            service_for(server),
            user_locale=locale_for,
            preview_source=preview_for,
            label_source=label_for,
        )
        server._mobile_push_service = service
    return service
