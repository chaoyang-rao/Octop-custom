"""Deliver one approved header to a pinned public HTTPS host; discard all bodies."""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from octop.infra.utils.ssrf_guard import PinnedIPTransport, _resolve_validated_ip


async def send_secret_header(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    body: dict[str, Any] | None,
) -> int:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    # The caller validates the exact action; resolve and pin again at delivery.
    request_url = urlunsplit(("https", host, parsed.path or "/", parsed.query, ""))
    async with asyncio.timeout(30):
        pin = await _resolve_validated_ip(url)
        async with (
            httpx.AsyncClient(
                transport=PinnedIPTransport(host, pin), timeout=20, follow_redirects=False
            ) as client,
            client.stream(method, request_url, json=body, headers=headers) as response,
        ):
            # Do not read, buffer, log or forward body / Location / headers.
            return response.status_code
