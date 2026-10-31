"""Lossless media projection between LangChain, ACP and MCP content blocks."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from typing import Any

from acp.schema import (
    AudioContentBlock,
    BlobResourceContents,
    EmbeddedResourceContentBlock,
    ImageContentBlock,
    ResourceContentBlock,
    TextContentBlock,
    TextResourceContents,
)

from octop.infra.agents.native_cli.config import NativeCLIError

_MAX_BYTES = 12 * 1024 * 1024


async def native_attachment_content(
    message: Any, content: str | list[dict[str, Any]], media_backend: Any
) -> str | list[dict[str, Any]]:
    """Forward original ingress attachments through the workspace media adapter.

    The common API path may reduce unsupported files to path hints. Native ACP
    needs typed content so it can check advertised capabilities before prompt.
    """
    from octop_gateway.models import FileContent, ImageContent

    media = []
    total = 0
    for part in message.content:
        if not isinstance(part, ImageContent | FileContent):
            continue
        data = getattr(part, "data", None)
        if isinstance(data, str) and data:
            encoded = _encoded(data)
        elif part.local_path and media_backend is not None:
            try:
                raw = await media_backend.read(part.local_path)
            except Exception:
                raise NativeCLIError("unsupported_media") from None
            if not isinstance(raw, bytes):
                raise NativeCLIError("unsupported_media")
            if len(raw) > _MAX_BYTES:
                raise NativeCLIError("input_too_large")
            encoded = base64.b64encode(raw).decode("ascii")
        else:
            # A remote URL is not fetched under the server's network identity.
            raise NativeCLIError("unsupported_media")
        total += len(encoded)
        if total > 24 * 1024 * 1024:
            raise NativeCLIError("input_too_large")
        mime = part.mime_type or "application/octet-stream"
        if isinstance(part, ImageContent) or mime.startswith("image/"):
            media.append({"type": "image", "data": encoded, "mimeType": mime})
        elif mime.startswith("audio/"):
            media.append({"type": "audio", "data": encoded, "mimeType": mime})
        else:
            block = media_block(
                {
                    "type": "file",
                    "file": {"data": encoded, "mimeType": mime, "filename": part.filename},
                }
            )
            assert block is not None
            media.append(block)
    if not media:
        return content
    # Preserve text/group context; replace common-path image projections with
    # original typed attachments to avoid duplicates or silent vision fallback.
    text = (
        [block for block in content if block.get("type") == "text"]
        if isinstance(content, list)
        else [{"type": "text", "text": content}]
    )
    return [*text, *media]


def _encoded(value: str) -> str:
    if len(value) > _MAX_BYTES * 4 // 3 + 8:
        raise NativeCLIError("input_too_large")
    try:
        base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        raise NativeCLIError("unsupported_media") from None
    return value


def media_block(part: dict[str, Any]) -> dict[str, Any] | None:
    kind = part.get("type")
    if kind in {"resource", "resource_link"}:
        resource = part.get("resource") if kind == "resource" else part
        if not isinstance(resource, dict) or not isinstance(resource.get("uri"), str):
            raise NativeCLIError("unsupported_media")
        return dict(part)
    if kind == "image_url":
        image = part.get("image_url")
        url = image.get("url") if isinstance(image, dict) else image
        if not isinstance(url, str) or not url.startswith("data:image/") or ";base64," not in url:
            raise NativeCLIError("unsupported_media")
        prefix, image_url_data = url.split(";base64,", 1)
        return {
            "type": "image",
            "data": _encoded(image_url_data),
            "mimeType": prefix.removeprefix("data:"),
        }
    if kind == "image" and isinstance(part.get("url"), str):
        return media_block({"type": "image_url", "image_url": part["url"]})
    if kind in {"image", "audio"}:
        media_data = part.get("data")
        mime = part.get("mimeType") or part.get("mime_type")
        if not isinstance(media_data, str) or not isinstance(mime, str):
            raise NativeCLIError("unsupported_media")
        return {"type": kind, "data": _encoded(media_data), "mimeType": mime}
    if kind == "input_audio":
        raw = part.get("input_audio") or {}
        return {
            "type": "audio",
            "data": _encoded(str(raw.get("data") or "")),
            "mimeType": "audio/" + str(raw.get("format") or "wav"),
        }
    if kind == "file":
        raw_file = part.get("file")
        file: dict[str, Any] = raw_file if isinstance(raw_file, dict) else part
        data = file.get("file_data") or file.get("data")
        mime = file.get("mime_type") or file.get("mimeType") or "application/octet-stream"
        if isinstance(data, str) and data.startswith("data:") and ";base64," in data:
            prefix, data = data.split(";base64,", 1)
            mime = prefix.removeprefix("data:")
        if not isinstance(data, str):
            uri = file.get("url") or file.get("uri")
            if isinstance(uri, str):
                from urllib.parse import urlsplit

                parsed = urlsplit(uri)
                if parsed.username or parsed.password:
                    raise NativeCLIError("unsupported_media")
                return {
                    "type": "resource_link",
                    "uri": uri,
                    "name": str(file.get("filename") or "attachment"),
                    "mimeType": mime,
                }
            raise NativeCLIError("unsupported_media")
        blob = _encoded(data)
        uri = "octop://attachment/" + hashlib.sha256(blob.encode()).hexdigest()[:24]
        return {"type": "resource", "resource": {"uri": uri, "mimeType": mime, "blob": blob}}
    return None


def acp_content(block: dict[str, Any], capabilities: dict[str, Any]) -> Any:
    kind = block["type"]
    if kind == "image":
        if not capabilities.get("image"):
            raise NativeCLIError("unsupported_media")
        return ImageContentBlock(type="image", data=block["data"], mime_type=block["mimeType"])
    if kind == "audio":
        if not capabilities.get("audio"):
            raise NativeCLIError("unsupported_media")
        return AudioContentBlock(type="audio", data=block["data"], mime_type=block["mimeType"])
    if kind == "resource_link":
        return ResourceContentBlock(
            type="resource_link",
            uri=str(block["uri"]),
            name=str(block.get("name") or "attachment"),
            mime_type=block.get("mimeType"),
            description=block.get("description"),
        )
    if kind == "resource":
        if not capabilities.get("embedded_context"):
            raise NativeCLIError("unsupported_media")
        resource = block["resource"]
        if "blob" in resource:
            contents: Any = BlobResourceContents(
                uri=str(resource["uri"]),
                mime_type=resource.get("mimeType"),
                blob=_encoded(str(resource["blob"])),
            )
        else:
            contents = TextResourceContents(
                uri=str(resource["uri"]),
                mime_type=resource.get("mimeType"),
                text=str(resource.get("text") or ""),
            )
        return EmbeddedResourceContentBlock(type="resource", resource=contents)
    return TextContentBlock(type="text", text=str(block.get("text") or ""))


def prompt_media(messages: list[Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = []
    media = []
    for message in messages:
        content = message.content
        if message.type == "tool":
            content = mcp_content(content)
        if isinstance(content, list):
            visible = []
            for item in content:
                block = media_block(item) if isinstance(item, dict) else None
                if block is not None:
                    media.append(block)
                    visible.append({"type": block["type"], "attachment_index": len(media) - 1})
                else:
                    visible.append(item)
            content = visible
        row = {"role": message.type, "content": content}
        if getattr(message, "tool_calls", None):
            row["tool_calls"] = message.tool_calls
        if message.type == "tool":
            row.update(tool_call_id=message.tool_call_id, name=message.name, status=message.status)
        rows.append(row)
    if len(json.dumps(media)) > 24 * 1024 * 1024:
        raise NativeCLIError("input_too_large")
    return rows, media


def mcp_content(content: Any, *, supports_images: bool = True) -> list[dict[str, Any]]:
    original = content
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except ValueError:
            parsed = None
        candidate = parsed.get("content") if isinstance(parsed, dict) else parsed
        if isinstance(candidate, list) and any(
            isinstance(item, dict)
            and item.get("type") in {"image", "image_url", "audio", "resource", "resource_link"}
            for item in candidate
        ):
            content = candidate
    if not isinstance(content, list):
        return [
            {
                "type": "text",
                "text": original
                if isinstance(original, str)
                else json.dumps(original, ensure_ascii=False),
            }
        ]
    result = []
    for item in content:
        if not isinstance(item, dict):
            result.append({"type": "text", "text": json.dumps(item, ensure_ascii=False)})
            continue
        block = media_block(item)
        if block is not None:
            if block["type"] == "image" and not supports_images:
                raise NativeCLIError("unsupported_media")
            result.append(block)
        elif item.get("type") == "text":
            result.append({"type": "text", "text": str(item.get("text") or "")})
        else:
            result.append({"type": "text", "text": json.dumps(item, ensure_ascii=False)})
    return result
