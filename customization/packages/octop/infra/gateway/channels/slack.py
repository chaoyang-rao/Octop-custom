"""Slack Socket Mode transport using Slack's public Web API.

No hosted relay or external SDK is required. Channel configuration and routing
stay in Octop; event payloads cannot supply an Octop user or agent identity.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Self
from urllib.parse import urlsplit

import aiohttp
from octop_gateway.channel import (
    BaseChannel,
    ChannelConfig,
    ChannelCredentialsError,
    MessageProcessor,
)
from octop_gateway.constraints import ChannelConstraints
from octop_gateway.models import (
    ChannelSubject,
    ContentPart,
    FileContent,
    ImageContent,
    InboundMessage,
    TextContent,
)

_MAX_FILE_BYTES = 25 * 1024 * 1024


@dataclass
class SlackConfig(ChannelConfig):
    bot_token: str = ""
    app_token: str = ""
    allowed_channel_ids: list[str] = field(default_factory=list)
    allowed_user_ids: list[str] = field(default_factory=list)
    allow_all_channels: bool = False

    required_credentials = ("bot_token", "app_token")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        cleaned = dict(data)
        for key in ("allowed_channel_ids", "allowed_user_ids"):
            value = cleaned.get(key, [])
            if isinstance(value, str):
                value = re.split(r"[,\s]+", value.strip()) if value.strip() else []
            if not isinstance(value, list) or any(
                not isinstance(item, str) or not re.fullmatch(r"[A-Z][A-Z0-9]+", item)
                for item in value
            ):
                raise ValueError("slack_invalid_allowlist")
            cleaned[key] = list(dict.fromkeys(value))
        if not isinstance(cleaned.get("allow_all_channels", False), bool):
            raise ValueError("slack_invalid_allowlist")
        return super().from_dict(cleaned)


def _slack_url(url: str, scheme: str) -> bool:
    parts = urlsplit(url)
    return bool(
        parts.scheme == scheme
        and parts.hostname
        and parts.hostname.endswith(".slack.com")
        and not parts.username
        and not parts.password
        and parts.port in (None, 443)
    )


class SlackChannel(BaseChannel):
    channel_type = "slack"

    def __init__(
        self,
        processor: MessageProcessor,
        *,
        config: SlackConfig,
        channel_id: str | None = None,
        tenant_id: str | None = None,
        debounce_seconds: float = 0.0,
        constraints: ChannelConstraints | None = None,
    ) -> None:
        super().__init__(
            processor,
            config=config,
            channel_id=channel_id,
            tenant_id=tenant_id,
            debounce_seconds=debounce_seconds,
            constraints=constraints,
        )
        self._config = config
        self._socket: aiohttp.ClientWebSocketResponse | None = None
        self._reader: asyncio.Task[None] | None = None
        self._connected = False
        self._runtime_error: str | None = None
        self._team_id = ""
        self._bot_user_id = ""
        self._seen: OrderedDict[str, None] = OrderedDict()

    def _default_constraints(self) -> ChannelConstraints:
        return ChannelConstraints(show_thinking=False, show_tool_hints=False)

    @property
    def is_connected(self) -> bool:
        return bool(self._connected and self._socket and not self._socket.closed)

    @property
    def runtime_error(self) -> str | None:
        return None if self.is_connected else self._runtime_error or "slack_disconnected"

    async def _api(
        self, method: str, values: dict[str, Any], *, app: bool = False
    ) -> dict[str, Any]:
        session = await self._ensure_http()
        token = self._config.app_token if app else self._config.bot_token
        for attempt in range(2):
            async with session.post(
                f"https://slack.com/api/{method}",
                json=values,
                headers={"Authorization": f"Bearer {token}"},
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                if response.status == 429 and attempt == 0:
                    delay = min(30, max(1, int(response.headers.get("Retry-After", "1"))))
                    await asyncio.sleep(delay)
                    continue
                if response.status != 200:
                    raise RuntimeError("slack_connection_failed")
                result = await response.json()
            if not isinstance(result, dict) or not result.get("ok"):
                code = result.get("error") if isinstance(result, dict) else None
                error = (
                    "slack_invalid_token"
                    if code in {"invalid_auth", "not_authed", "token_revoked", "account_inactive"}
                    else "slack_api_failed"
                )
                if code in {"missing_scope", "not_allowed_token_type"}:
                    error = "slack_missing_scope"
                raise RuntimeError(error)
            return result
        raise RuntimeError("slack_connection_failed")

    async def _connect(self) -> None:
        connection = await self._api("apps.connections.open", {}, app=True)
        url = str(connection.get("url") or "")
        if not _slack_url(url, "wss"):
            raise RuntimeError("slack_connection_failed")
        session = await self._ensure_http()
        self._socket = await asyncio.wait_for(session.ws_connect(url, heartbeat=30), timeout=30)
        self._connected = True
        self._runtime_error = None

    async def start(self) -> None:
        if self.is_connected:
            return
        await self.stop()
        missing = self._config.missing_credentials()
        if missing:
            raise ChannelCredentialsError("slack", missing)
        try:
            identity = await self._api("auth.test", {})
            self._team_id = str(identity["team_id"])
            self._bot_user_id = str(identity["user_id"])
            await self._connect()
        except asyncio.CancelledError:
            await self.stop()
            raise
        except Exception as exc:
            await self.stop()
            code = str(exc)
            if code not in {"slack_invalid_token", "slack_missing_scope", "slack_api_failed"}:
                code = "slack_connection_failed"
            raise RuntimeError(code) from None
        self._reader = asyncio.create_task(self._read_socket(), name=f"slack-{self.channel_id}")

    async def stop(self) -> None:
        task, self._reader = self._reader, None
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        if self._socket:
            await self._socket.close()
        self._socket = None
        self._connected = False
        await self._close_http()

    async def _read_socket(self) -> None:
        retry_delay = 1
        while True:
            try:
                if self._socket is None or self._socket.closed:
                    await self._connect()
                assert self._socket is not None
                async for packet in self._socket:
                    if packet.type == aiohttp.WSMsgType.TEXT:
                        payload = json.loads(packet.data)
                        if payload.get("type") == "disconnect":
                            break
                        await self._handle_envelope(payload)
                    elif packet.type in {aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR}:
                        break
                retry_delay = 1
            except asyncio.CancelledError:
                raise
            except Exception:
                # SDK/network errors can include token-bearing WebSocket URLs.
                self._runtime_error = "slack_connection_failed"
            self._connected = False
            if self._socket:
                await self._socket.close()
            self._socket = None
            await asyncio.sleep(retry_delay)
            retry_delay = min(30, retry_delay * 2)

    async def _handle_envelope(self, envelope: dict[str, Any]) -> None:
        envelope_id = envelope.get("envelope_id")
        if envelope_id and self._socket:
            await self._socket.send_json({"envelope_id": envelope_id})
        if envelope.get("type") != "events_api":
            return
        payload = envelope.get("payload", {})
        if not isinstance(payload, dict) or payload.get("team_id") != self._team_id:
            return
        event = payload.get("event", {})
        if not isinstance(event, dict) or event.get("type") not in {"app_mention", "message"}:
            return
        if (
            event.get("bot_id")
            or event.get("user") == self._bot_user_id
            or event.get("subtype") not in (None, "file_share")
        ):
            return
        channel = str(event.get("channel") or "")
        sender = str(event.get("user") or "")
        if not channel or not sender or not event.get("ts"):
            return
        is_dm = event.get("channel_type") == "im" or channel.startswith("D")
        if is_dm:
            if sender not in self._config.allowed_user_ids:
                return
        elif not (self._config.allow_all_channels or channel in self._config.allowed_channel_ids):
            return
        if (
            not is_dm
            and event.get("type") != "app_mention"
            and f"<@{self._bot_user_id}>" not in str(event.get("text") or "")
        ):
            return
        key = f"{channel}:{event['ts']}"
        if key in self._seen:
            return
        self._seen[key] = None
        if len(self._seen) > 2048:
            self._seen.popitem(last=False)
        self.enqueue(self.parse_inbound(event))

    def parse_inbound(self, raw_payload: Any) -> InboundMessage:
        if isinstance(raw_payload, InboundMessage):
            return raw_payload
        event: dict[str, Any] = raw_payload
        channel = str(event["channel"])
        is_dm = event.get("channel_type") == "im" or channel.startswith("D")
        thread_ts = str(event.get("thread_ts") or event["ts"])
        text = str(event.get("text") or "").replace(f"<@{self._bot_user_id}>", "").strip()
        parts: list[ContentPart] = [TextContent(text=text)] if text else []
        for attachment in event.get("files", []):
            url = str(attachment.get("url_private_download") or attachment.get("url_private") or "")
            size = attachment.get("size")
            if not _slack_url(url, "https") or not isinstance(size, int) or size > _MAX_FILE_BYTES:
                continue
            mime = str(attachment.get("mimetype") or "application/octet-stream")
            common: dict[str, Any] = {"url": url, "mime_type": mime, "size": size}
            if mime.startswith("image/"):
                parts.append(ImageContent(**common, alt_text=str(attachment.get("name") or "")))
            else:
                parts.append(
                    FileContent(**common, filename=str(attachment.get("name") or "attachment"))
                )
        metadata: dict[str, Any] = {
            "chat_id": channel,
            "channel_id_native": channel,
            "chat_type": "dm" if is_dm else "group",
            "sender_id": str(event["user"]),
            "message_id": str(event["ts"]),
            "team_id": self._team_id,
            "thread_ts": thread_ts,
        }
        # Every Slack thread has its own history; DMs retain a continuous session.
        subject = channel if is_dm else f"{channel}:{thread_ts}"
        return InboundMessage(
            channel_id=self.channel_id,
            channel_type="slack",
            tenant_id=self.tenant_id,
            channel_subject=ChannelSubject(
                subject_id=subject, chat_type=metadata["chat_type"], metadata=dict(metadata)
            ),
            content=parts,
            metadata=metadata,
        )

    @staticmethod
    def _destination(subject: ChannelSubject) -> dict[str, str]:
        channel, _, thread = subject.subject_id.partition(":")
        metadata = subject.metadata or {}
        result = {"channel": str(metadata.get("chat_id") or channel)}
        thread = str(metadata.get("thread_ts") or thread)
        if thread:
            result["thread_ts"] = thread
        return result

    async def _send_text(self, subject: ChannelSubject, text: str) -> None:
        # Prevent @channel/@here/user pings and automatic link unfurling.
        escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        for offset in range(0, len(escaped), 3500):
            await self._api(
                "chat.postMessage",
                {
                    **self._destination(subject),
                    "text": escaped[offset : offset + 3500],
                    "mrkdwn": False,
                    "parse": "none",
                    "unfurl_links": False,
                    "unfurl_media": False,
                },
            )

    async def _send_content(self, subject: ChannelSubject, parts: list[ContentPart]) -> None:
        for part in parts:
            if isinstance(part, TextContent):
                await self._send_text(subject, part.text)
            else:
                await self._send_media(subject, part)

    async def _send_media(self, subject: ChannelSubject, media: ContentPart) -> None:
        data, _ = await self.load_media_bytes(media)
        if len(data) > _MAX_FILE_BYTES:
            raise RuntimeError("slack_file_too_large")
        filename = str(
            getattr(media, "filename", None) or getattr(media, "alt_text", None) or "attachment"
        )
        filename = filename.replace("\\", "/").rsplit("/", 1)[-1]
        upload = await self._api(
            "files.getUploadURLExternal", {"filename": filename, "length": len(data)}
        )
        url = str(upload.get("upload_url") or "")
        if not _slack_url(url, "https"):
            raise RuntimeError("slack_api_failed")
        session = await self._ensure_http()
        async with session.post(
            url, data=data, allow_redirects=False, timeout=aiohttp.ClientTimeout(total=60)
        ) as response:
            if response.status != 200:
                raise RuntimeError("slack_api_failed")
        destination = self._destination(subject)
        await self._api(
            "files.completeUploadExternal",
            {
                "files": [{"id": upload["file_id"], "title": filename}],
                "channel_id": destination["channel"],
                **({"thread_ts": destination["thread_ts"]} if destination.get("thread_ts") else {}),
            },
        )

    async def fetch_remote_media(self, url: str) -> tuple[bytes, str]:
        if not _slack_url(url, "https"):
            raise RuntimeError("slack_api_failed")
        session = await self._ensure_http()
        async with session.get(
            url,
            headers={"Authorization": f"Bearer {self._config.bot_token}"},
            allow_redirects=False,
            timeout=aiohttp.ClientTimeout(total=60),
        ) as response:
            if response.status != 200:
                raise RuntimeError("slack_api_failed")
            data = bytearray()
            async for chunk in response.content.iter_chunked(65536):
                data.extend(chunk)
                if len(data) > _MAX_FILE_BYTES:
                    raise RuntimeError("slack_file_too_large")
            return bytes(data), response.headers.get("Content-Type", "application/octet-stream")
