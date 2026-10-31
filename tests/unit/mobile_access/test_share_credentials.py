"""Share extensions get a constrained sibling grant, never notification/login keys."""

from types import SimpleNamespace

import pytest
from tests.unit.mobile_access.test_mobile_access_service import paired
from tests.unit.mobile_access.test_mobile_access_service import service as service

from octop.infra.errors import OctopError
from octop.infra.mobile_access.access import resolve_mobile_user
from octop.infra.users.identity import User


@pytest.mark.asyncio
async def test_share_grant_is_stable_hashed_and_narrowed(service):
    _, device = await paired(service, ["chat", "files", "tasks", "terminal", "notifications"])
    grant = await service.share_grant(device["access_token"])
    assert grant == await service.share_grant(device["access_token"])
    assert grant["access_token"] not in service._settings.get("mobile_access.devices.1")
    session = service.authenticate(grant["access_token"])
    assert session.kind == "share" and set(session.scopes) == {"chat", "files", "tasks"}
    owner = User(id=1, username="owner", role="admin", display_name=None)
    server = SimpleNamespace(
        _mobile_access_service=service, user_manager=SimpleNamespace(get_by_id=lambda _: owner)
    )
    assert (
        resolve_mobile_user(
            server, grant["access_token"], path="/api/tasks", method="POST"
        ).device_kind
        == "share"
    )
    for path, method in [
        ("/api/workflows", "POST"),
        ("/api/tasks/workflows", "POST"),
        ("/api/tasks-calendar/token", "PUT"),
        ("/api/mobile-access/self/notifications", "PUT"),
        ("/api/mobile-access/self/share-grant", "POST"),
        ("/api/agents/A/terminal/ws", "WS"),
    ]:
        with pytest.raises(OctopError):
            resolve_mobile_user(server, grant["access_token"], path=path, method=method)
    with pytest.raises(OctopError):
        await service.share_grant(grant["access_token"])
    owner.role = "user"
    owner.permissions = ["experts"]
    with pytest.raises(OctopError):
        resolve_mobile_user(server, grant["access_token"], path="/api/tasks", method="POST")
    await service.revoke(user_id=1, device_id=device["device_id"])
    with pytest.raises(OctopError):
        service.authenticate(grant["access_token"])
