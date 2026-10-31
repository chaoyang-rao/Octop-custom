"""A lockscreen link cannot perform or retarget a task mutation."""

import asyncio
from types import SimpleNamespace

import pytest
from tests.unit.mobile_access.test_mobile_access_service import paired
from tests.unit.mobile_access.test_mobile_access_service import service as service

from octop.infra.errors import ErrorCode, OctopError
from octop.infra.mobile_access.actions import MobileTaskActions
from octop.infra.users.identity import User


class Tasks:
    def __init__(self):
        self.task = {
            "task_id": "TASK",
            "user_id": 1,
            "agent_id": "A",
            "title": "Current task",
            "attempt": 1,
            "state": "running",
            "archived": False,
        }
        self.calls = 0

    async def detail(self, uid, tid):
        if uid != self.task["user_id"] or tid != "TASK":
            raise OctopError(ErrorCode.FORBIDDEN, "not owned")
        return dict(self.task)

    async def action(self, uid, tid, action, *, expected_attempt):
        assert uid == 1 and tid == "TASK" and action == "cancel"
        if expected_attempt != self.task["attempt"]:
            raise OctopError(ErrorCode.FORBIDDEN, "stale", status=409)
        self.calls += 1
        self.task["state"] = "cancelled"


def server_for(service):
    owner = User(id=1, username="owner", role="admin", display_name=None)
    return SimpleNamespace(
        _mobile_access_service=service,
        user_manager=SimpleNamespace(get_by_id=lambda _: owner),
        services=SimpleNamespace(secret_repo=service._secrets),
        task_manager=Tasks(),
    ), owner


@pytest.mark.asyncio
async def test_navigation_is_readonly_and_proof_is_device_bound_hashed_single_use(service):
    _, device = await paired(service, ["chat", "tasks"])
    server, _ = server_for(service)
    actions = MobileTaskActions(server)
    nav = await actions.navigation(device["access_token"], "TASK", 1)
    prepared = await actions.prepare(device["access_token"], nav)
    assert server.task_manager.calls == 0 and prepared["title"] == "Current task"
    assert prepared["confirmation"] not in service._settings.get("mobile_access.task_actions.1")
    _, second = await paired(service, ["tasks"])
    with pytest.raises(OctopError):
        await actions.prepare(second["access_token"], nav)
    with pytest.raises(OctopError):
        await actions.execute(second["access_token"], prepared["confirmation"])
    await actions.execute(device["access_token"], prepared["confirmation"])
    assert server.task_manager.calls == 1
    with pytest.raises(OctopError):
        await actions.execute(device["access_token"], prepared["confirmation"])


@pytest.mark.asyncio
async def test_stale_retry_and_edited_summary_cannot_be_cancelled(service):
    _, device = await paired(service, ["tasks"])
    server, _ = server_for(service)
    actions = MobileTaskActions(server)
    nav = await actions.navigation(device["access_token"], "TASK", 1)
    prepared = await actions.prepare(device["access_token"], nav)
    server.task_manager.task["attempt"] = 2
    with pytest.raises(OctopError):
        await actions.prepare(device["access_token"], nav)
    with pytest.raises(OctopError):
        await actions.execute(device["access_token"], prepared["confirmation"])
    server.task_manager.task["attempt"] = 1
    server.task_manager.task["title"] = "Changed task"
    with pytest.raises(OctopError):
        await actions.execute(device["access_token"], prepared["confirmation"])
    assert server.task_manager.calls == 0


@pytest.mark.asyncio
async def test_revoked_lost_permission_expired_and_tampered_actions_reject(service, monkeypatch):
    _, device = await paired(service, ["tasks"])
    server, owner = server_for(service)
    actions = MobileTaskActions(server)
    nav = await actions.navigation(device["access_token"], "TASK", 1)
    with pytest.raises(OctopError):
        await actions.prepare(device["access_token"], nav[:-1] + ("A" if nav[-1] != "A" else "B"))
    prepared = await actions.prepare(device["access_token"], nav)
    import octop.infra.mobile_access.actions as module

    now = module.time.time()
    monkeypatch.setattr(module.time, "time", lambda: now + 121)
    with pytest.raises(OctopError):
        await actions.execute(device["access_token"], prepared["confirmation"])
    monkeypatch.setattr(module.time, "time", lambda: now)
    owner.role = "user"
    owner.permissions = ["experts"]
    with pytest.raises(OctopError):
        await actions.prepare(device["access_token"], nav)
    owner.role = "admin"
    await service.revoke(user_id=1, device_id=device["device_id"])
    with pytest.raises(OctopError):
        await actions.execute(device["access_token"], prepared["confirmation"])
    assert server.task_manager.calls == 0


@pytest.mark.asyncio
async def test_double_confirmation_has_only_one_effect(service):
    _, device = await paired(service, ["tasks"])
    server, _ = server_for(service)
    actions = MobileTaskActions(server)
    nav = await actions.navigation(device["access_token"], "TASK", 1)
    prepared = await actions.prepare(device["access_token"], nav)
    results = await asyncio.gather(
        *(actions.execute(device["access_token"], prepared["confirmation"]) for _ in range(2)),
        return_exceptions=True,
    )
    assert sum(isinstance(result, OctopError) for result in results) == 1
    assert server.task_manager.calls == 1


@pytest.mark.asyncio
async def test_cross_server_signature_and_share_sibling_cannot_execute(service):
    _, device = await paired(service, ["chat", "tasks"])
    server, _ = server_for(service)
    actions = MobileTaskActions(server)
    nav = await actions.navigation(device["access_token"], "TASK", 1)
    grant = await service.share_grant(device["access_token"])
    with pytest.raises(OctopError):
        await actions.prepare(grant["access_token"], nav)
    service._secrets.rotate("mobile_access.task_navigation.v1", b"different-server-secret-for-test")
    with pytest.raises(OctopError):
        await actions.prepare(device["access_token"], nav)
    assert server.task_manager.calls == 0
