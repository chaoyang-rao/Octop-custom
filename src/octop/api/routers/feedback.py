"""Authenticated feedback forms and administrator-only triage HTTP adapters."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Query, Response

from octop.api.deps import current_user, get_server
from octop.api.routers.enterprise_mcp_admin import _CatalogRoute, _no_store
from octop.infra.errors import ErrorCode
from octop.infra.feedback.models import (
    FeedbackCreate,
    FeedbackList,
    FeedbackOptions,
    FeedbackRecord,
    FeedbackUpdate,
    Status,
)
from octop.infra.feedback.service import FeedbackService
from octop.infra.users.identity import User


class FeedbackRoute(_CatalogRoute):
    validation_error = ErrorCode.FEEDBACK_INVALID


router = APIRouter(route_class=FeedbackRoute)
center_router = APIRouter(route_class=FeedbackRoute)


@router.get(
    "/feedback/options",
    response_model=FeedbackOptions,
    summary="List sidebar sections available for feedback",
)
async def options(
    response: Response, user: User = Depends(current_user), server: Any = Depends(get_server)
) -> FeedbackOptions:
    _no_store(response)
    return await asyncio.to_thread(FeedbackService(server).options, user)


@center_router.get(
    "/enterprise/feedback/options",
    response_model=FeedbackOptions,
    summary="List company feedback sections",
)
async def company_options(
    response: Response, user: User = Depends(current_user), server: Any = Depends(get_server)
) -> FeedbackOptions:
    _no_store(response)
    return await asyncio.to_thread(FeedbackService(server).options, user, company=True)


@router.post(
    "/feedback",
    response_model=FeedbackRecord,
    summary="Submit feedback to the configured administrator",
    description="Company clients forward only the feedback form through their existing company identity; other installations retain it locally. Repeated submission keys are idempotent.",
)
async def submit(
    body: FeedbackCreate,
    response: Response,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> FeedbackRecord:
    _no_store(response)
    return await FeedbackService(server).submit(user, body)


@center_router.post(
    "/enterprise/feedback",
    response_model=FeedbackRecord,
    summary="Submit company feedback under the authenticated employee identity",
)
async def company_submit(
    body: FeedbackCreate,
    response: Response,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> FeedbackRecord:
    _no_store(response)
    return await asyncio.to_thread(FeedbackService(server).create_local, user, body, company=True)


@router.get(
    "/feedback/mine",
    response_model=FeedbackList,
    summary="Read the current member's feedback and administrator replies",
)
async def mine(
    response: Response,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0, le=100000),
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> FeedbackList:
    _no_store(response)
    return await FeedbackService(server).mine(user, limit=limit, offset=offset)


@center_router.get(
    "/enterprise/feedback/mine",
    response_model=FeedbackList,
    summary="Read only the authenticated employee's company feedback",
)
async def company_mine(
    response: Response,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0, le=100000),
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> FeedbackList:
    _no_store(response)
    return await asyncio.to_thread(
        FeedbackService(server).mine_local, user, limit=limit, offset=offset, company=True
    )


@router.get(
    "/feedback/admin",
    response_model=FeedbackList,
    summary="Administrators: filter and paginate installation feedback",
)
@center_router.get(
    "/enterprise/feedback/admin",
    response_model=FeedbackList,
    summary="Company administrators: filter member feedback",
)
async def admin_list(
    response: Response,
    section: str | None = Query(None, max_length=64),
    status: Status | None = None,
    q: str = Query("", max_length=100),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0, le=100000),
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> FeedbackList:
    _no_store(response)
    return await asyncio.to_thread(
        FeedbackService(server).admin_list,
        user,
        section=section,
        status=status,
        query=q,
        limit=limit,
        offset=offset,
    )


@router.patch(
    "/feedback/admin/{feedback_id}",
    response_model=FeedbackRecord,
    summary="Administrators: record feedback status and reply",
)
@center_router.patch(
    "/enterprise/feedback/admin/{feedback_id}",
    response_model=FeedbackRecord,
    summary="Company administrators: record a feedback outcome",
    description="Requires the current revision; concurrent edits return a conflict instead of replacing another administrator's reply.",
)
async def admin_update(
    feedback_id: str,
    body: FeedbackUpdate,
    response: Response,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> FeedbackRecord:
    _no_store(response)
    return await asyncio.to_thread(FeedbackService(server).admin_update, user, feedback_id, body)
