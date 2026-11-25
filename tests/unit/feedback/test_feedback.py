from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from octop.api.deps import current_user, get_server
from octop.api.routers.feedback import center_router, router
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import RepoBundle
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.feedback import service as module
from octop.infra.feedback.models import FeedbackCreate
from octop.infra.feedback.service import FeedbackService
from octop.infra.mobile_access.access import MobileUser, authorize_device_path
from octop.infra.mobile_access.service import DeviceSession
from octop.infra.users.identity import User


@pytest.fixture
def company(tmp_path, monkeypatch):
    monkeypatch.setenv("OCTOP_HOME", str(tmp_path))
    pool = SqlitePool(tmp_path / "octop.db")
    run_migrations(pool)
    repos = RepoBundle.from_pool(pool)
    actors = []
    for username, role in [("publisher", "admin"), ("alice", "user"), ("bob", "user")]:
        user_id = repos.user_repo.create(
            username=username, role=role, display_name=username.title()
        )
        actors.append(
            User(
                id=user_id, username=username, role=role, display_name=username.title(), locale="zh"
            )
        )
    server = SimpleNamespace(
        services=SimpleNamespace(
            feedback_repo=repos.feedback_repo,
            audit_repo=repos.audit_repo,
            config=SimpleNamespace(enterprise_center_enabled=False),
        )
    )
    monkeypatch.setattr(module, "client_for", lambda _: None)
    monkeypatch.setattr(
        module, "center_for", lambda _: SimpleNamespace(require_employee=lambda user: str(user.id))
    )
    yield SimpleNamespace(
        server=server,
        service=FeedbackService(server),
        repos=repos,
        admin=actors[0],
        alice=actors[1],
        bob=actors[2],
        pool=pool,
    )
    pool.close()


def draft(**changes):
    return FeedbackCreate.model_validate(
        {
            "submission_key": "a" * 32,
            "section": "token-usage",
            "kind": "problem",
            "title": "统计页布局",
            "content": "切换板块后布局没有对齐",
            **changes,
        }
    )


@pytest.fixture
async def api(company):
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.include_router(center_router, prefix="/api")
    actor = {"user": company.alice}
    app.dependency_overrides[current_user] = lambda: actor["user"]
    app.dependency_overrides[get_server] = lambda: company.server

    @app.exception_handler(OctopError)
    async def error(request, failure):
        return JSONResponse(status_code=failure.status, content=failure.to_envelope())

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://feedback.test"
    ) as client:
        yield SimpleNamespace(client=client, actor=actor, company=company, app=app)


async def test_feedback_uses_authenticated_author_and_member_sees_only_own(api):
    created = await api.client.post("/api/feedback", json=draft().model_dump())
    assert created.status_code == 200
    assert created.json()["author_name"] == "Alice"
    assert created.headers["cache-control"] == "no-store"
    assert "user_id" not in created.json() and "submission_key" not in created.json()
    api.actor["user"] = api.company.bob
    mine = await api.client.get("/api/feedback/mine?user_id=2")
    assert mine.status_code == 200 and mine.json()["items"] == []
    denied = await api.client.get("/api/feedback/admin")
    assert denied.status_code == 403
    api.actor["user"] = api.company.admin
    records = await api.client.get("/api/feedback/admin?section=token-usage&q=Alice")
    assert (
        records.json()["total"] == 1
        and records.json()["items"][0]["feedback_id"] == created.json()["feedback_id"]
    )


async def test_extra_identity_fields_and_invalid_sections_are_rejected_without_echo(api):
    for changes in [
        {"user_id": "private-rejected-value"},
        {"section": "unknown"},
        {"content": "   "},
    ]:
        body = draft().model_dump() | changes
        result = await api.client.post("/api/feedback", json=body)
        assert result.status_code == 400
        assert result.json()["error"]["code"] == "FEEDBACK_INVALID"
        assert "private-rejected-value" not in result.text
    assert api.company.repos.feedback_repo.list()[1] == 0


async def test_retries_are_idempotent_and_changed_payload_cannot_replace_report(api):
    first = await api.client.post("/api/feedback", json=draft().model_dump())
    second = await api.client.post("/api/feedback", json=draft().model_dump())
    assert first.json()["feedback_id"] == second.json()["feedback_id"]
    assert api.company.repos.feedback_repo.list()[1] == 1
    changed = await api.client.post(
        "/api/feedback", json=draft(content="改变后的内容").model_dump()
    )
    assert changed.status_code == 409
    assert (
        api.company.repos.feedback_repo.get(first.json()["feedback_id"])["content"]
        == draft().content
    )


async def test_admin_reply_revision_conflict_and_member_readback(api):
    row = (await api.client.post("/api/feedback", json=draft().model_dump())).json()
    api.actor["user"] = api.company.admin
    body = {
        "expected_revision": row["revision"],
        "status": "in_progress",
        "reply": "已收到，正在排查。",
    }
    result = await api.client.patch("/api/feedback/admin/" + row["feedback_id"], json=body)
    assert result.status_code == 200 and result.json()["revision"] == 2
    stale = await api.client.patch(
        "/api/feedback/admin/" + row["feedback_id"], json={**body, "reply": "stale"}
    )
    assert stale.status_code == 409
    api.actor["user"] = api.company.alice
    mine = (await api.client.get("/api/feedback/mine")).json()
    assert mine["items"][0]["reply"] == body["reply"]
    assert mine["items"][0]["status"] == "in_progress"


def test_device_even_with_admin_role_cannot_manage_feedback(company):
    device = MobileUser(
        id=company.admin.id, username="device", role="admin", display_name="", locale="zh"
    )
    with pytest.raises(OctopError) as failure:
        company.service.admin_list(device, section=None, status=None, query="", limit=20, offset=0)
    assert failure.value.code == ErrorCode.FORBIDDEN


def test_enterprise_device_feedback_scope_excludes_management():
    session = DeviceSession(
        user_id=1, device_id="test-device", scopes=("enterprise",), expires_at=1
    )
    for path, method in [
        ("/api/enterprise/feedback", "POST"),
        ("/api/enterprise/feedback/mine", "GET"),
        ("/api/enterprise/feedback/options", "GET"),
    ]:
        authorize_device_path(session, path, method)
    for path, method in [
        ("/api/enterprise/feedback/admin", "GET"),
        ("/api/enterprise/feedback/admin/fb_test", "PATCH"),
        ("/api/enterprise/feedback/mine", "DELETE"),
    ]:
        with pytest.raises(OctopError) as failure:
            authorize_device_path(session, path, method)
        assert failure.value.code == ErrorCode.FORBIDDEN


def test_filters_pagination_and_migration_preserve_existing_feedback(company):
    first = company.service.create_local(company.alice, draft())
    company.service.create_local(company.bob, draft(section="connectors", submission_key="b" * 32))
    result = company.service.admin_list(
        company.admin, section=None, status="new", query="", limit=1, offset=1
    )
    assert result.total == 2 and len(result.items) == 1
    run_migrations(company.pool)
    assert company.repos.feedback_repo.get(first.feedback_id)["author_name"] == "Alice"
    assert company.repos.user_repo.get(company.alice.id).username == "alice"


async def test_company_client_uses_existing_grant_and_does_not_silently_store_locally(
    company, monkeypatch
):
    remote_record = company.service.create_local(company.admin, draft()).model_dump()
    client = SimpleNamespace(
        authorize=AsyncMock(),
        _state=lambda _: {"token": "private-device-grant"},
        _remote=AsyncMock(return_value=remote_record),
    )
    monkeypatch.setattr(module, "client_for", lambda _: client)
    before = company.repos.feedback_repo.list()[1]
    result = await company.service.submit(company.alice, draft(submission_key="c" * 32))
    assert result.feedback_id == remote_record["feedback_id"]
    call = client._remote.await_args
    assert call.args == ("POST", "/api/enterprise/feedback")
    assert call.kwargs["token"] == "private-device-grant"
    assert not {"user_id", "author_name", "token", "project_path"} & call.kwargs["body"].keys()
    assert company.repos.feedback_repo.list()[1] == before
    client._remote.side_effect = OctopError.localized(ErrorCode.ENTERPRISE_UNAVAILABLE)
    with pytest.raises(OctopError):
        await company.service.submit(company.alice, draft(submission_key="d" * 32))
    assert company.repos.feedback_repo.list()[1] == before


async def test_company_feedback_requires_verified_employee(api, monkeypatch):
    def reject(user):
        raise OctopError.localized(ErrorCode.ENTERPRISE_ACCESS_DENIED)

    monkeypatch.setattr(module, "center_for", lambda _: SimpleNamespace(require_employee=reject))
    result = await api.client.post("/api/enterprise/feedback", json=draft().model_dump())
    assert result.status_code == 403
    assert api.company.repos.feedback_repo.list()[1] == 0


async def test_options_cover_sidebar_boards_and_member_cannot_submit_admin_update(api):
    result = await api.client.get("/api/feedback/options")
    keys = {section["key"] for section in result.json()["sections"]}
    assert {
        "chat",
        "experts",
        "token-usage",
        "connectors",
        "skill-packages",
        "knowledge-bases",
        "models",
        "companion",
        "general",
    } <= keys
    assert not result.json()["local_admin"]
    row = (await api.client.post("/api/feedback", json=draft().model_dump())).json()
    denied = await api.client.patch(
        "/api/feedback/admin/" + row["feedback_id"],
        json={"status": "resolved", "reply": "", "expected_revision": 1},
    )
    assert denied.status_code == 403
    assert api.app.openapi()["paths"]["/api/feedback"]["post"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"].endswith("FeedbackRecord")
