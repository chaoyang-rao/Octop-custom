"""Owned uploaded-file references; no URL downloads or arbitrary host paths."""

from __future__ import annotations

import asyncio
import hashlib
import secrets
from pathlib import PurePosixPath
from typing import Any

from octop_gateway.models import ContentPart, FileContent, ImageContent

from octop.infra.db.repos._base import now_ts
from octop.infra.gateway.media.attachment_hints import is_vision_attachment, sniff_image_media_type
from octop.infra.gateway.media.inbound_store import (
    sanitize_inbound_filename,
    validate_inbound_media_type,
)
from octop.infra.tasks.models import TaskAttachment
from octop.infra.utils.ulid import new_ulid

MAX_TASK_FILES = 10
MAX_TASK_FILE_BYTES = 25 * 1024 * 1024
MAX_TASK_TOTAL_BYTES = 100 * 1024 * 1024


class TaskAttachmentError(ValueError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


async def issue_upload_receipt(
    repos: Any,
    *,
    user_id: int,
    agent_id: str,
    workspace_path: str,
    filename: str,
    mime_type: str,
    data: bytes,
) -> str | None:
    """Issue only for the actual upload bytes, never for arbitrary workspace references.

    Shared/administrator-as-another-owner uploads keep normal chat behavior,
    but cannot create an owned Task attachment receipt for another expert.
    """
    row = await asyncio.to_thread(repos.agent_repo.get, agent_id)
    if row is None or row.user_id != user_id:
        return None
    path = validate_path(workspace_path)
    token = secrets.token_urlsafe(32)
    await asyncio.to_thread(
        repos.task_repo.create_upload_receipt,
        receipt_id=new_ulid(),
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        user_id=user_id,
        agent_id=agent_id,
        path=path,
        filename=filename,
        mime_type=mime_type,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )
    return token


async def authorize_uploads(
    repos: Any,
    *,
    user_id: int,
    agent_id: str,
    references: list[TaskAttachment],
    check_expiry: bool = True,
) -> list[TaskAttachment]:
    """Validate durable upload provenance before any workspace content is read."""
    checked = []
    for reference in references:
        path = validate_path(reference.workspace_path)
        if not reference.upload_receipt:
            raise TaskAttachmentError("attachment_receipt")
        receipt = await asyncio.to_thread(
            repos.task_repo.upload_receipt,
            hashlib.sha256(reference.upload_receipt.encode()).hexdigest(),
            user_id=user_id,
            agent_id=agent_id,
            path=path,
        )
        if receipt is None or (check_expiry and receipt["expires_at"] < now_ts()):
            raise TaskAttachmentError("attachment_receipt")
        if (reference.size is not None and reference.size != receipt["byte_size"]) or (
            reference.sha256 is not None and reference.sha256 != receipt["sha256"]
        ):
            raise TaskAttachmentError("attachment_changed")
        checked.append(
            reference.model_copy(
                update={
                    "filename": receipt["filename"],
                    "mime_type": receipt["mime_type"],
                    "size": receipt["byte_size"],
                    "sha256": receipt["sha256"],
                }
            )
        )
    return checked


def validate_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        len(path.parts) != 2
        or path.parts[0] != "inbound"
        or str(path) != value
        or any(part in {".", ".."} for part in value.split("/"))
        or any(ch in value for ch in ("\\", ":", "%", "\x00", "\r", "\n"))
    ):
        raise TaskAttachmentError("attachment_invalid")
    return value


async def validate_references(
    workspace: Any, references: list[TaskAttachment]
) -> list[TaskAttachment]:
    if len(references) > MAX_TASK_FILES:
        raise TaskAttachmentError("attachment_count")
    if not references:
        return []
    if workspace is None:
        raise TaskAttachmentError("attachment_missing")
    listing = await workspace.als("inbound")
    entries = getattr(listing, "entries", []) if listing is not None else []
    by_name = {
        PurePosixPath(
            str(item.get("path", "") if isinstance(item, dict) else getattr(item, "path", ""))
        ).name: item
        for item in entries
    }
    result = []
    total = 0
    seen = set()
    for reference in references:
        path = validate_path(reference.workspace_path)
        if path in seen:
            continue
        seen.add(path)
        entry = by_name.get(PurePosixPath(path).name)
        if entry is None:
            raise TaskAttachmentError("attachment_missing")

        def value(key: str, source: Any = entry) -> Any:
            return source.get(key) if isinstance(source, dict) else getattr(source, key, None)

        if value("is_dir") or value("is_symlink"):
            raise TaskAttachmentError("attachment_invalid")
        reported = value("size")
        if isinstance(reported, int) and reported > MAX_TASK_FILE_BYTES:
            raise TaskAttachmentError("attachment_limit")
        data = await workspace.adownload_bytes(path)
        if data is None:
            raise TaskAttachmentError("attachment_missing")
        size = len(data)
        total += size
        if size > MAX_TASK_FILE_BYTES or total > MAX_TASK_TOTAL_BYTES:
            raise TaskAttachmentError("attachment_limit")
        if reference.size is not None and reference.size != size:
            raise TaskAttachmentError("attachment_changed")
        digest = hashlib.sha256(data).hexdigest()
        if reference.sha256 is not None and reference.sha256 != digest:
            raise TaskAttachmentError("attachment_changed")
        filename = sanitize_inbound_filename(reference.filename or PurePosixPath(path).name)
        mime = validate_inbound_media_type(reference.mime_type, filename)
        if mime.startswith("image/"):
            sniffed = sniff_image_media_type(data)
            if sniffed:
                mime = sniffed
            elif mime in {"image/png", "image/jpeg", "image/gif", "image/webp"}:
                raise TaskAttachmentError("attachment_invalid")
        result.append(
            reference.model_copy(
                update={"filename": filename, "mime_type": mime, "size": size, "sha256": digest}
            )
        )
    return result


def content_parts(references: list[TaskAttachment]) -> list[ContentPart]:
    parts: list[ContentPart] = []
    for item in references:
        if is_vision_attachment(
            kind="image" if item.mime_type.startswith("image/") else "file",
            media_type=item.mime_type,
            path=item.workspace_path,
        ):
            parts.append(
                ImageContent(
                    local_path=item.workspace_path,
                    mime_type=item.mime_type,
                    alt_text=item.filename,
                    size=item.size,
                )
            )
        else:
            parts.append(
                FileContent(
                    local_path=item.workspace_path,
                    filename=item.filename,
                    mime_type=item.mime_type,
                    size=item.size,
                )
            )
    return parts
