"""Fetch online documents as markdown so they can be imported into a knowledge base.

Feishu / Lark links go through the official ``lark-cli`` (``docs +fetch``), which
reuses the operator's existing CLI authorization on this host. Any other
``http(s)`` link is fetched directly and reduced to plain text.
"""

from __future__ import annotations

import ipaddress
import json
import re
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlparse

from octop.infra.connectors.gateway.cli_runner import resolve_binary, run_cli
from octop.infra.knowledge.parse import _html_text

# Lark/Feishu documents, including the doubao.com front door for the same docs.
FEISHU_DOMAINS = ("feishu.cn", "larksuite.com", "larkoffice.com", "doubao.com")
CLI_TIMEOUT_S = 60.0
WEB_TIMEOUT_S = 20.0
WEB_MAX_BYTES = 5 * 1024 * 1024

_MARKDOWN_TITLE_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_HTML_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


class OnlineDocumentError(ValueError):
    """Raised when an online document cannot be fetched or is not usable."""


@dataclass(frozen=True)
class OnlineDocument:
    title: str
    markdown: str
    source_url: str


def is_feishu_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == domain or host.endswith(f".{domain}") for domain in FEISHU_DOMAINS)


def fetch_online_document(url: str) -> OnlineDocument:
    """Fetch *url* and return its title plus markdown/plain-text body."""
    target = (url or "").strip()
    parsed = urlparse(target)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise OnlineDocumentError("仅支持 http(s) 在线文档链接")
    if is_feishu_url(target):
        return fetch_feishu_document(target)
    return fetch_web_document(target)


def fetch_feishu_document(url: str, *, env: dict[str, str] | None = None) -> OnlineDocument:
    binary = resolve_binary("lark-cli")
    try:
        raw = run_cli(
            [
                binary,
                "docs",
                "+fetch",
                "--doc",
                url,
                "--doc-format",
                "markdown",
                "--format",
                "json",
            ],
            env=env,
            timeout_s=CLI_TIMEOUT_S,
        )
    except ValueError as exc:
        raise OnlineDocumentError(_feishu_hint(str(exc))) from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OnlineDocumentError("飞书 CLI 返回了无法解析的内容") from exc
    if not isinstance(payload, dict):
        raise OnlineDocumentError("飞书 CLI 返回了无法解析的内容")
    if payload.get("ok") is False:
        raise OnlineDocumentError(_feishu_hint(str(payload.get("error") or "未知错误")))
    document = (payload.get("data") or {}).get("document") or {}
    content = str(document.get("content") or "").strip()
    if not content:
        raise OnlineDocumentError("飞书文档内容为空")
    title = _markdown_title(content) or str(document.get("document_id") or "") or "飞书文档"
    return OnlineDocument(title=title, markdown=content, source_url=url)


def fetch_web_document(url: str) -> OnlineDocument:
    _ensure_public_host(url)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "OctopKnowledge/1.0", "Accept-Language": "zh-CN,en;q=0.8"},
    )
    try:
        with urllib.request.urlopen(request, timeout=WEB_TIMEOUT_S) as response:  # noqa: S310
            raw = response.read(WEB_MAX_BYTES + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise OnlineDocumentError(f"无法访问该链接：{exc}") from exc
    if len(raw) > WEB_MAX_BYTES:
        raise OnlineDocumentError("网页内容超过 5 MB，无法导入")
    text = raw.decode("utf-8", errors="replace")
    title = _html_title(text) or (urlparse(url).hostname or "网页文档")
    body = _html_text(text) if "<" in text[:2048] else text.strip()
    if not body.strip():
        raise OnlineDocumentError("网页没有可导入的正文内容")
    return OnlineDocument(title=title, markdown=body.strip(), source_url=url)


def _markdown_title(markdown: str) -> str:
    match = _MARKDOWN_TITLE_RE.search(markdown)
    return match.group(1).strip() if match else ""


def _html_title(html: str) -> str:
    match = _HTML_TITLE_RE.search(html)
    return " ".join(match.group(1).split()) if match else ""


def _ensure_public_host(url: str) -> None:
    host = urlparse(url).hostname or ""
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except socket.gaierror as exc:
        raise OnlineDocumentError(f"无法解析域名：{host}") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise OnlineDocumentError("不支持导入内网地址")


def _feishu_hint(message: str) -> str:
    text = (message or "").strip()
    lower = text.lower()
    if "未找到主机命令" in text or "command not found" in lower:
        return "主机未安装飞书 CLI，请先在「连接器 → 飞书 CLI」中安装"
    if "auth" in lower or "授权" in text or "token" in lower or "permission" in lower:
        return f"飞书 CLI 尚未授权或缺少文档读取权限：{text}"
    return f"飞书文档读取失败：{text}"


TITLE_MAX_BYTES = 256 * 1024


def fetch_page_title(url: str) -> str:
    """Best-effort page title for a user-sent link. Never raises."""
    if not url.lower().startswith(("http://", "https://")):
        return ""
    try:
        _ensure_public_host(url)
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "OctopLink/1.0", "Accept-Language": "zh-CN,en;q=0.8"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
            raw = response.read(TITLE_MAX_BYTES)
    except Exception:  # noqa: BLE001 - a dead link must not fail the request
        return ""
    text = raw.decode("utf-8", errors="replace")
    title = _html_title(text) or _og_title(text)
    return " ".join(title.split())[:200]


def _og_title(html: str) -> str:
    match = re.search(
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
        html,
        re.IGNORECASE,
    )
    return match.group(1) if match else ""
