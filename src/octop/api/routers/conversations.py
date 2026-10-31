"""Thin HTTP surface for owned conversation controls and previewed portability."""

from __future__ import annotations

from typing import Any, cast

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from octop.api.deps import current_user, get_server
from octop.infra.conversations.archives import MAX_ARCHIVE_BYTES
from octop.infra.conversations.models import (
    ExportSelection,
    ImportSelection,
    MessageLocator,
    QuotedMessage,
)
from octop.infra.conversations.service import ConversationService
from octop.infra.conversations.transfer import ConversationTransfer

router = APIRouter()


def _service(server: Any) -> ConversationService:
    return cast(ConversationService, server.conversation_service)


def _transfer(server: Any) -> ConversationTransfer:
    return cast(ConversationTransfer, server.conversation_transfer)


class ConversationView(BaseModel):
    thread_id: str
    agent_id: str
    agent_name: str
    kind: str
    title: str | None
    archived: bool
    last_active: int
    created_at: int
    project_name: str | None = None
    origin: dict[str, Any] | None = None


class ConversationList(BaseModel):
    conversations: list[ConversationView]
    has_more: bool
    next_offset: int


class ArchiveBody(BaseModel):
    archived: bool = Field(
        description="Archive hides the conversation from normal lists without deleting messages."
    )


class ReactionBody(BaseModel):
    message: MessageLocator
    emoji: str = Field(min_length=1, max_length=16)
    active: bool = Field(description="Set or remove one reaction idempotently.")


class ReactionView(BaseModel):
    message_key: str
    message_digest: str
    message_role: str
    emoji: str
    created_at: int


class AnnotationsView(BaseModel):
    reactions: list[ReactionView]
    allowed: list[str]


class ReactionResult(BaseModel):
    message_key: str
    reactions: list[ReactionView]


class SideQuestionView(BaseModel):
    thread_id: str
    agent_id: str
    session_key: str
    source_thread_id: str
    copied_messages: int
    title: str | None
    last_active: int
    created_at: int
    conversation_mode: str


class ImportItem(BaseModel):
    key: str
    name: str
    messages: int
    skills: int
    files: int
    duplicate: bool
    name_conflict: bool


class ImportPreview(BaseModel):
    id: str
    kind: str
    state: str
    sha256: str
    expires_at: int
    items: list[ImportItem]
    omitted_messages: int
    ignored_files: int
    warnings: list[str]
    bytes: int


class ImportedThread(BaseModel):
    thread_id: str
    agent_id: str
    title: str


class ImportedAgent(BaseModel):
    agent_id: str
    name: str
    source_key: str


class ImportResult(BaseModel):
    threads: list[ImportedThread]
    agents: list[ImportedAgent]
    skipped: int
    warnings: list[str]


@router.get(
    "/conversations",
    response_model=ConversationList,
    summary="Browse owned active or archived conversations",
)
async def browse_conversations(
    archived: bool = False,
    agent_id: str = "",
    query: str = Query(default="", max_length=300),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    return await _service(server).browse(
        user.id, archived=archived, agent_id=agent_id, query=query, limit=limit, offset=offset
    )


@router.patch(
    "/conversations/{thread_id}/archive",
    response_model=ConversationView,
    summary="Archive or restore a conversation",
)
async def archive_conversation(
    thread_id: str,
    body: ArchiveBody,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    return await _service(server).archive_thread(user.id, thread_id, body.archived)


@router.get(
    "/conversations/{thread_id}/annotations",
    response_model=AnnotationsView,
    summary="Read current user's message reactions",
)
async def get_annotations(
    thread_id: str, user: Any = Depends(current_user), server: Any = Depends(get_server)
) -> dict[str, Any]:
    return await _service(server).annotations(user.id, thread_id)


@router.post(
    "/conversations/{thread_id}/reactions",
    response_model=ReactionResult,
    summary="Set or remove a reaction to a real owned message",
)
async def react(
    thread_id: str,
    body: ReactionBody,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    return await _service(server).react(user.id, thread_id, body.message, body.emoji, body.active)


@router.post(
    "/conversations/{thread_id}/resolve",
    response_model=QuotedMessage,
    summary="Resolve a quoted message from owned history",
)
async def resolve_message(
    thread_id: str,
    body: MessageLocator,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> QuotedMessage:
    return await _service(server).resolve(user.id, thread_id, body)


@router.post(
    "/conversations/{thread_id}/side-question",
    response_model=SideQuestionView,
    summary="Create an independent question branch at an assistant answer",
    description="Copies history through the selected reply into a separate session, keeps the primary chat binding, and defaults to read-only ask mode. No model call is made until the user sends a question.",
)
async def side_question(
    thread_id: str,
    body: MessageLocator,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    return await _service(server).side_question(user.id, thread_id, body)


@router.post(
    "/conversation-imports/preview",
    response_model=ImportPreview,
    summary="Preview an uploaded ZIP without importing or executing",
    description="Raw application/zip body, at most 100 MiB. Supports Grok conversation exports and reviewed public agent formats. Preview is owner-bound, expires after 30 minutes, and importing requires a separate explicit confirmation.",
    openapi_extra={
        "requestBody": {
            "content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}},
            "required": True,
        }
    },
)
async def preview_import(
    request: Request, user: Any = Depends(current_user), server: Any = Depends(get_server)
) -> dict[str, Any]:
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_ARCHIVE_BYTES:
            raise _service(server).error("archive_limit", user.id, 413)
    return await _transfer(server).stage(user.id, bytes(data))


@router.get(
    "/conversation-imports/{preview_id}",
    response_model=ImportPreview,
    summary="Read a private import preview",
)
async def get_preview(
    preview_id: str, user: Any = Depends(current_user), server: Any = Depends(get_server)
) -> dict[str, Any]:
    return await _transfer(server).preview(user.id, preview_id)


@router.post(
    "/conversation-imports/{preview_id}/confirm",
    response_model=ImportResult,
    summary="Import selected preview items as new resources",
    description="Single-use preview, insert-only conversations, fresh private expert IDs and avatars. Foreign login state, host paths, connectors and approval bypass settings are never applied. Imported history remains an archived provenance record.",
)
async def confirm_import(
    preview_id: str,
    body: ImportSelection,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> dict[str, Any]:
    return await _transfer(server).confirm(user.id, preview_id, body)


@router.delete(
    "/conversation-imports/{preview_id}",
    status_code=204,
    summary="Discard a private import preview",
)
async def discard_import(
    preview_id: str, user: Any = Depends(current_user), server: Any = Depends(get_server)
) -> Response:
    await _transfer(server).discard(user.id, preview_id)
    return Response(status_code=204)


@router.post(
    "/conversation-transfer/export",
    summary="Export selected owned experts to a portable ZIP",
    description="Explicitly selected workspace files, skills, conversation records and workflow definitions may be included. Excludes login and credential stores, native CLI commands, host paths and approval policies. User-authored files or chat text may contain sensitive content; review selections before sharing.",
    response_class=Response,
    responses={200: {"content": {"application/zip": {}}, "description": "Portable expert ZIP"}},
)
async def export_bundle(
    body: ExportSelection, user: Any = Depends(current_user), server: Any = Depends(get_server)
) -> Response:
    data = await _transfer(server).export(user.id, body)
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="octop-transfer.zip"'},
    )
