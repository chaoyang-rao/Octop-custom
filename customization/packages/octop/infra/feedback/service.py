"""Member feedback forwarding and administrator triage, without chat/file collection."""

from __future__ import annotations

import asyncio
import platform
import time
from typing import Any
from urllib.parse import urlencode

from octop import __version__
from octop.infra.auth.enterprise import center_for, client_for
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.feedback.models import (
    SECTION_KEYS,
    SECTIONS,
    FeedbackCreate,
    FeedbackList,
    FeedbackOptions,
    FeedbackRecord,
    FeedbackSection,
    FeedbackUpdate,
    Status,
)
from octop.infra.mobile_access.access import MobileUser
from octop.infra.users.identity import User
from octop.infra.utils.ulid import new_ulid


class FeedbackService:
    def __init__(self, server: Any) -> None:
        self.server = server
        self.repo = server.services.feedback_repo

    def _company_member(self, user: User) -> None:
        center = center_for(self.server)
        if center is None:
            raise OctopError.localized(ErrorCode.ENTERPRISE_NOT_CONFIGURED)
        center.require_employee(user)

    def _admin(self, user: User) -> None:
        if client_for(self.server) is not None or isinstance(user, MobileUser) or not user.is_admin:
            raise OctopError.localized(ErrorCode.FORBIDDEN)
        if self.server.services.config.enterprise_center_enabled:
            self._company_member(user)

    def options(self, user: User, *, company: bool = False) -> FeedbackOptions:
        if company:
            self._company_member(user)
        remote = client_for(self.server) is not None
        return FeedbackOptions(
            sections=[
                FeedbackSection(key=key, label_key=label, path=path)
                for key, label, path in SECTIONS
            ],
            destination="company" if remote or company else "local",
            local_admin=not remote
            and not company
            and user.is_admin
            and not isinstance(user, MobileUser),
        )

    def create_local(
        self, user: User, request: FeedbackCreate, *, company: bool = False
    ) -> FeedbackRecord:
        if company:
            self._company_member(user)
        now = int(time.time())
        values = request.model_dump()
        values.update(
            feedback_id="fb_" + new_ulid(),
            user_id=user.id,
            author_name=user.label[:200],
            created_at=now,
            updated_at=now,
        )
        row = self.repo.create(values)
        if any(
            row[key] != getattr(request, key) for key in ("section", "kind", "title", "content")
        ):
            raise OctopError.localized(ErrorCode.FEEDBACK_CONFLICT)
        if row["feedback_id"] == values["feedback_id"]:
            self.server.services.audit_repo.write(
                actor=user.username,
                action="feedback.create",
                target=row["feedback_id"],
                payload=request.section + ":" + request.kind,
            )
        return FeedbackRecord.model_validate(row)

    async def _remote(
        self, user: User, method: str, path: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        client = client_for(self.server)
        if client is None:
            raise OctopError.localized(ErrorCode.ENTERPRISE_NOT_CONFIGURED)
        await client.authorize(user)
        credentials = await asyncio.to_thread(client._state, user.id)
        return await client._remote(
            method, "/api/enterprise/feedback" + path, token=credentials["token"], body=body
        )

    async def submit(self, user: User, request: FeedbackCreate) -> FeedbackRecord:
        if client_for(self.server) is not None:
            system = platform.system().lower()
            client_platform = {"darwin": "macos", "windows": "windows", "linux": "linux"}.get(
                system, "web"
            )
            forwarded = request.model_dump()
            forwarded.update(
                client_version=request.client_version or __version__,
                client_platform=request.client_platform or client_platform,
            )
            result = await self._remote(user, "POST", "", forwarded)
            return FeedbackRecord.model_validate(result)
        return await asyncio.to_thread(self.create_local, user, request)

    def mine_local(
        self, user: User, *, limit: int = 20, offset: int = 0, company: bool = False
    ) -> FeedbackList:
        if company:
            self._company_member(user)
        rows, total = self.repo.list(user_id=user.id, limit=limit, offset=offset)
        return FeedbackList(
            items=[FeedbackRecord.model_validate(row) for row in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def mine(self, user: User, *, limit: int = 20, offset: int = 0) -> FeedbackList:
        if client_for(self.server) is not None:
            result = await self._remote(
                user, "GET", "/mine?" + urlencode({"limit": limit, "offset": offset})
            )
            return FeedbackList.model_validate(result)
        return await asyncio.to_thread(self.mine_local, user, limit=limit, offset=offset)

    def admin_list(
        self,
        user: User,
        *,
        section: str | None,
        status: Status | None,
        query: str,
        limit: int,
        offset: int,
    ) -> FeedbackList:
        self._admin(user)
        if section is not None and section not in SECTION_KEYS:
            raise OctopError.localized(ErrorCode.FEEDBACK_INVALID)
        rows, total = self.repo.list(
            section=section, status=status, query=query, limit=limit, offset=offset
        )
        return FeedbackList(
            items=[FeedbackRecord.model_validate(row) for row in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    def admin_update(self, user: User, feedback_id: str, request: FeedbackUpdate) -> FeedbackRecord:
        self._admin(user)
        if self.repo.get(feedback_id) is None:
            raise OctopError.localized(ErrorCode.FEEDBACK_NOT_FOUND)
        if not self.repo.update(
            feedback_id,
            expected_revision=request.expected_revision,
            status=request.status,
            reply=request.reply.strip(),
            updated_at=int(time.time()),
        ):
            raise OctopError.localized(ErrorCode.FEEDBACK_CONFLICT)
        self.server.services.audit_repo.write(
            actor=user.username,
            action="feedback.update",
            target=feedback_id,
            payload=request.status,
        )
        return FeedbackRecord.model_validate(self.repo.get(feedback_id))
