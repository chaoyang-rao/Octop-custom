"""Dashboard chat attachments — stored in agent workspace ``inbound/``."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, UploadFile

from octop.api.common.attachments import (
    StoredAttachment,
    dashboard_inbound_preview_url,
    save_attachment,
)
from octop.api.common.upload_limit import read_upload_capped
from octop.api.common.workspace import require_running_workspace
from octop.api.deps import current_user, get_server
from octop.config import DEFAULT_MAX_UPLOAD_MB, upload_mb_to_bytes
from octop.infra.gateway.media.attachment_hints import sniff_image_media_type
from octop.infra.gateway.media.inbound_store import INBOUND_EXTENSION_MEDIA_TYPES

router = APIRouter()


def _resolve_media_type(filename: str, content_type: str | None, data: bytes = b"") -> str:
    raw = (content_type or "").split(";", 1)[0].strip().lower()
    if raw and raw != "application/octet-stream":
        return raw
    ext = Path(filename or "").suffix.lower()
    if ext in INBOUND_EXTENSION_MEDIA_TYPES:
        return INBOUND_EXTENSION_MEDIA_TYPES[ext]
    guessed, _ = mimetypes.guess_type(filename or "")
    if guessed:
        return guessed.lower()
    sniffed = sniff_image_media_type(data)
    if sniffed:
        return sniffed
    return "application/octet-stream"


def _attachment_payload(agent_id: str, stored: StoredAttachment) -> dict[str, str]:
    path = stored.data_path
    preview_url = dashboard_inbound_preview_url(
        agent_id,
        path,
        media_type=stored.media_type,
    )
    return {
        "path": path,
        "workspace_path": path,
        "url": preview_url,
        "access_url": preview_url,
        "filename": stored.filename,
        "media_type": stored.media_type,
    }


@router.post("/agents/{agent_id}/upload", summary="Upload a chat attachment")
async def upload_attachment(
    agent_id: str,
    file: UploadFile = File(...),  # noqa: B008
    as_user: int | None = None,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, str]:
    from octop.infra.mobile_access.access import CURRENT_MOBILE_REQUEST, MobileUser

    if isinstance(user, MobileUser) and user.device_kind == "share":
        from octop.infra.mobile_access.shares import prepare_share_upload

        # The narrow credential can start only its owned target after Send.
        context = CURRENT_MOBILE_REQUEST.get()
        token = context.token if context is not None else None
        await prepare_share_upload(server, token=token or "", agent_id=agent_id)
    ws = await require_running_workspace(agent_id, user=user, as_user=as_user, server=server)
    max_bytes = (
        int(server.services.config.max_upload_bytes) if server.services is not None else None
    )
    fallback = upload_mb_to_bytes(DEFAULT_MAX_UPLOAD_MB)
    data = await read_upload_capped(file, max_bytes=max_bytes or fallback)
    filename = file.filename or "upload.bin"
    media_type = _resolve_media_type(filename, file.content_type, data)
    stored = await save_attachment(
        ws,
        owner_id=user.id,
        filename=filename,
        media_type=media_type,
        data=data,
        max_bytes=max_bytes,
    )
    from octop.infra.tasks.attachments import issue_upload_receipt

    payload = _attachment_payload(agent_id, stored)
    receipt = await issue_upload_receipt(
        server.services.repos,
        user_id=user.id,
        agent_id=agent_id,
        workspace_path=stored.data_path,
        filename=stored.filename,
        mime_type=stored.media_type,
        data=data,
    )
    if receipt is not None:
        payload["upload_receipt"] = receipt
    return payload
