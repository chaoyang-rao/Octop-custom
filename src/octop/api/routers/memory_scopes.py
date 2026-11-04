"""Conversation-bound memory management; identity comes from the session."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from octop.api.deps import current_user, get_server, require_permission

Scope = Literal["auto", "user", "project", "expert", "session"]
router = APIRouter(dependencies=[Depends(require_permission("memory"))])
_BASE = "/agents/{agent_id}/threads/{thread_id}/memory"


class MemorySource(BaseModel):
    thread_id: str
    agent_id: str
    title: str
    message_id: str | None = None
    created_at: str
    origin: str


class ScopedAtom(BaseModel):
    id: str
    assertion: str
    kind: str | None = None
    created_at: str
    deprecated_at: str | None = None
    superseded_by: str | None = None
    sources: list[MemorySource] = Field(default_factory=list)


class ScopedMemories(BaseModel):
    scope: str
    scope_token: str
    default_scope: str
    available_scopes: list[str]
    project_name: str | None = None
    items: list[ScopedAtom]
    total: int
    has_more: bool


class SaveMemory(BaseModel):
    scope: Scope = "auto"
    expected_scope_token: str = Field(
        min_length=1,
        max_length=100,
        description="Token from the loaded scope; prevents writing after a conversation changes projects.",
    )
    content: str = Field(
        min_length=1,
        max_length=4000,
        description="A fact explicitly supplied or corrected by the user.",
    )
    replaces: str | None = Field(
        default=None,
        description="Atom ID in the same scope; a successor is created and the old revision remains.",
    )


class SavedMemory(BaseModel):
    scope: str
    atom_id: str
    replaces: str | None = None
    source: dict[str, Any]


class MemoryRevision(BaseModel):
    id: str
    timestamp: str
    action: str
    actor: str
    target_atom_id: str | None = None
    before: dict[str, Any] | None = Field(
        default=None,
        description="Fields before the change, including assertion and atom_id for corrections.",
    )
    after: dict[str, Any] | None = Field(
        default=None, description="Fields after the change; previous revisions remain immutable."
    )
    note: str = ""
    source: dict[str, Any] | None = None


class RevisionList(BaseModel):
    items: list[MemoryRevision]
    total: int
    has_more: bool


class RetiredMemory(BaseModel):
    atom_id: str
    status: Literal["deprecated"]


async def _call(
    server: Any, user: Any, agent_id: str, thread_id: str, operation: str, **params: Any
) -> dict[str, Any]:
    return await asyncio.to_thread(
        server.app_runtime.agent_registry.scoped_memory_operation,
        agent_id,
        thread_id,
        user.id,
        operation,
        **params,
    )


@router.get(
    _BASE,
    response_model=ScopedMemories,
    summary="List memory in this conversation's authorized scope",
    description="The project comes from the persisted folder binding, never a caller-supplied path. User scopes remain isolated even for shared experts.",
)
async def list_memories(
    agent_id: str,
    thread_id: str,
    scope: Scope = "auto",
    query: str = Query("", max_length=200),
    offset: int = Query(0, ge=0),
    include_deprecated: bool = False,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    return await _call(
        server,
        user,
        agent_id,
        thread_id,
        "list",
        scope=scope,
        query=query,
        offset=offset,
        include_deprecated=include_deprecated,
    )


@router.post(
    _BASE,
    response_model=SavedMemory,
    summary="Save or correct a scoped memory",
    description="Explicit user action. Corrections create a new revision; the previous assertion and source history remain available.",
)
async def save_memory(
    agent_id: str,
    thread_id: str,
    body: SaveMemory,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    return await _call(
        server, user, agent_id, thread_id, "save", **body.model_dump(exclude_none=True)
    )


@router.post(
    _BASE + "/{atom_id}:deprecate",
    response_model=RetiredMemory,
    summary="Retire a memory without deleting its source history",
)
async def deprecate_memory(
    agent_id: str,
    thread_id: str,
    atom_id: str,
    scope: Scope = "auto",
    expected_scope_token: str = Query(..., min_length=1, max_length=100),
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    return await _call(
        server,
        user,
        agent_id,
        thread_id,
        "deprecate",
        atom_id=atom_id,
        scope=scope,
        expected_scope_token=expected_scope_token,
    )


@router.get(
    _BASE + "/{atom_id}/revisions",
    response_model=RevisionList,
    summary="Read the memory's revision journal",
)
async def revisions(
    agent_id: str,
    thread_id: str,
    atom_id: str,
    scope: Scope = "auto",
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    return await _call(server, user, agent_id, thread_id, "revisions", atom_id=atom_id, scope=scope)
