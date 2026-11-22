"""Company model relay. Upstream credentials stay encrypted at the center."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from typing import Any, cast
from urllib.parse import urlsplit

import httpx
from cryptography.fernet import InvalidToken
from pydantic import BaseModel, ConfigDict, Field, model_validator

from octop.infra.crypto.fernet import decrypt_json, encrypt_json
from octop.infra.enterprise_resources.companion import CompanionCatalog
from octop.infra.enterprise_resources.models import canonical, conflict, digest
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.users.identity import User
from octop.infra.users.permissions import user_has_permission
from octop.infra.users.resource_policy import assert_token_quota_available

CONFIG_KEY = "enterprise.companion.inference.v1"
PURPOSE = "enterprise_companion_inference_fernet"
MAX_BODY = 24 * 1024 * 1024
MODEL_FIELDS = frozenset(
    {
        "id",
        "enabled",
        "thinking",
        "api_mode",
        "api_fallback",
        "name",
        "context_window",
        "input_tokens",
        "output_tokens",
        "max_tokens",
        "max_input_tokens",
        "max_output_tokens",
        "input",
        "output",
        "vision",
        "reasoning",
        "tool_calling",
    }
)


class InferenceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    base_url: str = ""
    api_key: str = Field(default="", repr=False)
    headers: dict[str, str] = Field(default_factory=dict, repr=False)
    default_model: str = "deepseek-v4-pro"
    models: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    stream_usage: bool = False
    max_output_tokens: int = Field(default=8192, ge=256, le=65536)
    requests_per_minute: int = Field(default=20, ge=1, le=300)
    concurrent_per_user: int = Field(default=2, ge=1, le=8)

    @model_validator(mode="after")
    def validate_config(self) -> InferenceConfig:
        if not self.enabled and not self.base_url:
            return self
        url = urlsplit(self.base_url)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
            or "/enterprise/companion/" in url.path
        ):
            raise ValueError("invalid model origin")
        if not self.api_key or any(c in self.api_key for c in "\r\n\0"):
            raise ValueError("model credential required")
        self.base_url = self.base_url.rstrip("/")
        self.models = [
            {k: v for k, v in model.items() if k in MODEL_FIELDS} for model in self.models
        ]
        ids = [m.get("id") for m in self.models]
        if (
            not ids
            or not all(isinstance(i, str) and 0 < len(i) <= 160 for i in ids)
            or len(set(ids)) != len(ids)
            or self.default_model not in ids
            or (
                self.enabled
                and self.default_model
                not in {m["id"] for m in self.models if m.get("enabled", True)}
            )
        ):
            raise ValueError("invalid model catalog")
        if any(not k or any(c in k + v for c in "\r\n\0") for k, v in self.headers.items()):
            raise ValueError("invalid model headers")
        return self


class InferenceService:
    def __init__(self, server: Any) -> None:
        self.server = server
        self.services = server.services
        self.catalog = CompanionCatalog(server)
        self._lock = asyncio.Lock()
        self._recent: dict[int, deque[float]] = defaultdict(deque)
        self._active: dict[int, int] = defaultdict(int)
        self.transport: httpx.AsyncBaseTransport | None = None

    def config(self) -> tuple[str, InferenceConfig]:
        raw = self.services.settings_repo.get(CONFIG_KEY)
        if not raw:
            return digest(""), InferenceConfig()
        try:
            private = decrypt_json(self.services.secret_repo, PURPOSE, raw.encode())
            return digest(raw), InferenceConfig.model_validate(private)
        except (ValueError, TypeError, InvalidToken):
            raise OctopError.localized(ErrorCode.DORA_MODEL_UNAVAILABLE) from None

    def admin(self, user: User) -> dict[str, Any]:
        self.catalog.catalog._admin(user)
        etag, config = self.config()
        return {
            **config.model_dump(exclude={"api_key", "headers"}),
            "etag": etag,
            "key_configured": bool(config.api_key),
        }

    def configure(self, user: User, config: InferenceConfig, expected_etag: str) -> dict[str, Any]:
        self.catalog.catalog._admin(user)
        old = self.services.settings_repo.get(CONFIG_KEY)
        if digest(old or "") != expected_etag:
            raise conflict()
        sealed = encrypt_json(self.services.secret_repo, PURPOSE, config.model_dump()).decode()
        if not self.services.settings_repo.compare_and_set(CONFIG_KEY, old, sealed):
            raise conflict()
        self.services.audit_repo.write(
            actor=user.username,
            action="enterprise.companion.model.configure",
            target=CONFIG_KEY,
            payload=canonical(
                {
                    "enabled": config.enabled,
                    "default_model": config.default_model,
                    "models": len(config.models),
                }
            ),
        )
        return self.admin(user)

    def profile(self, user: User) -> dict[str, Any]:
        self.catalog.catalog.center.require_employee(user)
        if not user_has_permission(user, "experts"):
            raise OctopError.localized(ErrorCode.ENTERPRISE_ACCESS_DENIED)
        etag, cfg = self.config()
        if not cfg.enabled:
            raise OctopError.localized(ErrorCode.DORA_MODEL_UNAVAILABLE)
        return {
            "revision": etag,
            "default_model": cfg.default_model,
            "models": [
                {
                    **m,
                    "max_output_tokens": min(
                        int(m.get("max_output_tokens") or cfg.max_output_tokens),
                        cfg.max_output_tokens,
                    ),
                }
                for m in cfg.models
                if m.get("enabled", True)
            ],
            "stream_usage": cfg.stream_usage,
        }

    def _principal(self, user: User) -> User:
        self.profile(user)
        owner = self.server.user_manager.get_by_id(user.id)
        if owner is None:
            raise OctopError.localized(ErrorCode.ENTERPRISE_ACCESS_DENIED)
        assert_token_quota_available(
            self.services.user_policy_repo, self.services.usage_repo, owner.id
        )
        return cast(User, owner)

    def usage(self, user: User, days: int) -> dict[str, Any]:
        self.catalog.catalog.center.require_employee(user)
        owner = self.server.user_manager.get_by_id(user.id)
        if owner is None or not user_has_permission(owner, "token_usage"):
            raise OctopError.localized(ErrorCode.ENTERPRISE_ACCESS_DENIED)
        until = int(time.time()) + 1
        since = until - days * 86400
        rows = self.services.repos.company_model_usage_repo.window(
            since, until, None if owner.is_admin else owner.id
        )
        names = {u.id: u.label for u in self.server.user_manager.list()}
        for row in rows:
            row["member_name"] = names.get(row["user_id"], str(row["user_id"]))
        keys = ("requests", "input_tokens", "output_tokens", "total_tokens", "estimated_requests")
        return {
            "scope": "company" if owner.is_admin else "self",
            "range_start": since,
            "range_end": until,
            "totals": {key: sum(row[key] for row in rows) for key in keys},
            "rows": rows,
        }

    async def open(self, user: User, endpoint: str, payload: dict[str, Any]) -> InferenceReply:
        if endpoint not in {"chat/completions", "responses"}:
            raise OctopError.localized(ErrorCode.DORA_MODEL_INVALID_REQUEST)
        owner = await asyncio.to_thread(self._principal, user)
        _, cfg = await asyncio.to_thread(self.config)
        body = dict(payload)
        if not isinstance(body.get("model"), str) or body.get("model") not in {
            m["id"] for m in cfg.models if m.get("enabled", True)
        }:
            raise OctopError.localized(ErrorCode.FORBIDDEN)
        if not isinstance(body.get("stream", False), bool) or any(
            k in body for k in {"api_key", "base_url", "headers"}
        ):
            raise OctopError.localized(ErrorCode.DORA_MODEL_INVALID_REQUEST)
        if endpoint == "chat/completions" and (
            not isinstance(body.get("messages"), list) or len(body["messages"]) > 2000
        ):
            raise OctopError.localized(ErrorCode.DORA_MODEL_INVALID_REQUEST)
        if endpoint == "responses" and not isinstance(body.get("input"), (str, list)):
            raise OctopError.localized(ErrorCode.DORA_MODEL_INVALID_REQUEST)
        limit_key = (
            "max_output_tokens"
            if endpoint == "responses"
            else "max_completion_tokens"
            if "max_completion_tokens" in body
            else "max_tokens"
        )
        requested = body.get(limit_key, cfg.max_output_tokens)
        if not isinstance(requested, int) or isinstance(requested, bool) or requested < 1:
            raise OctopError.localized(ErrorCode.DORA_MODEL_INVALID_REQUEST)
        body[limit_key] = min(requested, cfg.max_output_tokens)
        for key in ("max_tokens", "max_completion_tokens", "max_output_tokens"):
            if key in body:
                value = body[key]
                if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                    raise OctopError.localized(ErrorCode.DORA_MODEL_INVALID_REQUEST)
                body[key] = min(value, cfg.max_output_tokens)
        if body.get("n", 1) != 1 or body.get("best_of", 1) != 1:
            raise OctopError.localized(ErrorCode.DORA_MODEL_INVALID_REQUEST)
        if not cfg.stream_usage:
            body.pop("stream_options", None)
        try:
            encoded = json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
        except (ValueError, TypeError):
            raise OctopError.localized(ErrorCode.DORA_MODEL_INVALID_REQUEST) from None
        if len(encoded) > MAX_BODY:
            raise OctopError.localized(ErrorCode.DORA_MODEL_INVALID_REQUEST)
        async with self._lock:
            now = time.monotonic()
            recent = self._recent[owner.id]
            while recent and recent[0] <= now - 60:
                recent.popleft()
            if (
                len(recent) >= cfg.requests_per_minute
                or self._active[owner.id] >= cfg.concurrent_per_user
                or sum(self._active.values()) >= 16
            ):
                raise OctopError.localized(ErrorCode.DORA_MODEL_RATE_LIMITED)
            recent.append(now)
            self._active[owner.id] += 1
        client = httpx.AsyncClient(
            transport=self.transport,
            follow_redirects=False,
            trust_env=False,
            timeout=httpx.Timeout(180, connect=15),
        )
        headers = {
            **cfg.headers,
            "Authorization": "Bearer " + cfg.api_key,
            "Content-Type": "application/json",
        }
        try:
            response = await client.send(
                client.build_request(
                    "POST", cfg.base_url + "/" + endpoint, content=encoded, headers=headers
                ),
                stream=True,
            )
            if response.status_code != 200 or (
                body.get("stream")
                and "text/event-stream" not in response.headers.get("content-type", "")
            ):
                status = response.status_code
                await response.aclose()
                if status in {400, 422}:
                    raise OctopError.localized(ErrorCode.DORA_MODEL_INVALID_REQUEST)
                if status == 429:
                    raise OctopError.localized(ErrorCode.DORA_MODEL_RATE_LIMITED)
                raise OctopError.localized(ErrorCode.DORA_MODEL_UNAVAILABLE)
            return InferenceReply(
                self,
                client,
                response,
                owner.id,
                str(body["model"]),
                len(encoded),
                bool(body.get("stream")),
                [
                    cfg.api_key,
                    *[
                        v
                        for k, v in cfg.headers.items()
                        if any(s in k.lower() for s in ("key", "token", "authorization", "secret"))
                    ],
                ],
            )
        except BaseException as exc:
            await client.aclose()
            async with self._lock:
                self._active[owner.id] -= 1
            if isinstance(exc, httpx.HTTPError):
                raise OctopError.localized(ErrorCode.DORA_MODEL_UNAVAILABLE) from None
            raise


class InferenceReply:
    def __init__(
        self,
        service: InferenceService,
        client: httpx.AsyncClient,
        response: httpx.Response,
        user_id: int,
        model: str,
        input_bytes: int,
        streaming: bool,
        redact: list[str],
    ) -> None:
        self.service, self.client, self.response = service, client, response
        self.user_id, self.model, self.input_bytes, self.streaming = (
            user_id,
            model,
            input_bytes,
            streaming,
        )
        self._usage: dict[str, Any] = {}
        self._output_bytes = 0
        self._closed = False
        self._redactions = [s for s in redact if len(s) >= 8]

    def _safe(self, value: Any) -> Any:
        if isinstance(value, str):
            for secret in self._redactions:
                value = value.replace(secret, "***")
            return value
        if isinstance(value, dict):
            return {self._safe(k): self._safe(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._safe(item) for item in value]
        return value

    def _observe(self, data: Any) -> None:
        if not isinstance(data, dict):
            return
        nested = data.get("response")
        usage = data.get("usage") or (nested.get("usage") if isinstance(nested, dict) else None)
        if isinstance(usage, dict):
            self._usage = usage

    async def json(self) -> Any:
        try:
            raw = await self.response.aread()
            if len(raw) > MAX_BODY:
                raise OctopError.localized(ErrorCode.DORA_MODEL_UNAVAILABLE)
            self._output_bytes = len(raw)
            value = json.loads(raw)
            self._observe(value)
            return self._safe(value)
        except (ValueError, TypeError):
            raise OctopError.localized(ErrorCode.DORA_MODEL_UNAVAILABLE) from None
        finally:
            await self.close()

    async def events(self) -> AsyncIterator[bytes]:
        pending = b""
        try:
            async for chunk in self.response.aiter_bytes():
                self._output_bytes += len(chunk)
                if self._output_bytes > MAX_BODY:
                    raise httpx.StreamError("model output limit")
                pending += chunk
                lines = pending.split(b"\n")
                pending = lines.pop()
                for line in lines:
                    if line.startswith(b"data:"):
                        try:
                            item = json.loads(line[5:].strip())
                            self._observe(item)
                            line = (
                                b"data: "
                                + json.dumps(self._safe(item), ensure_ascii=False).encode()
                            )
                        except (ValueError, TypeError):
                            pass
                    for secret in self._redactions:
                        line = line.replace(secret.encode(), b"***")
                    yield line + b"\n"
            if pending:
                for secret in self._redactions:
                    pending = pending.replace(secret.encode(), b"***")
                yield pending
        except httpx.HTTPError:
            error = OctopError.localized(ErrorCode.DORA_MODEL_UNAVAILABLE)
            yield (
                "data: "
                + json.dumps({"error": {"message": error.message, "code": error.code.value}})
                + "\n\ndata: [DONE]\n\n"
            ).encode()
        finally:
            await self.close()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self.response.aclose()
            await self.client.aclose()
            actual = bool(self._usage)
            inputs = max(
                0,
                int(
                    self._usage.get(
                        "prompt_tokens", self._usage.get("input_tokens", self.input_bytes // 3)
                    )
                ),
            )
            outputs = max(
                0,
                int(
                    self._usage.get(
                        "completion_tokens",
                        self._usage.get("output_tokens", self._output_bytes // 4),
                    )
                ),
            )
            await asyncio.to_thread(
                self.service.services.repos.company_model_usage_repo.record,
                user_id=self.user_id,
                model=self.model,
                request_id="dora-" + uuid.uuid4().hex,
                input_tokens=inputs,
                output_tokens=outputs,
                source="dora_model" if actual else "dora_model_estimate",
            )
        finally:
            async with self.service._lock:
                self.service._active[self.user_id] -= 1


def inference_for(server: Any) -> InferenceService:
    value = getattr(server, "_companion_inference", None)
    if value is None:
        value = InferenceService(server)
        server._companion_inference = value
    return value
