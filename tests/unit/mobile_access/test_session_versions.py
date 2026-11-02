"""Password and MFA session changes also invalidate opaque mobile grants."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from tests.unit.mobile_access.test_mobile_access_service import paired
from tests.unit.mobile_access.test_mobile_access_service import service as service
from tests.unit.mobile_access.test_task_actions import server_for

from octop.infra.errors import OctopError
from octop.infra.mobile_access.actions import MobileTaskActions
from octop.infra.mobile_access.push import MobilePushService
from octop.infra.mobile_access.service import service_for


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["password_version", "mfa_version"])
async def test_pairing_binds_current_versions_and_fresh_pairing_recovers(service, field):
    owner = service._users.get(1)
    owner.password_version, owner.mfa_version = 3, 5
    server, _ = server_for(service)
    assert service_for(server) is service
    request, device = await paired(service, ["chat", "tasks", "notifications"])
    sibling = await service.share_grant(device["access_token"])
    stored = service._read("mobile_access.devices.1", [])[0]
    assert (stored["password_version"], stored["mfa_version"]) == (3, 5)
    await service.register_push(token=device["access_token"], platform="apns", push_token="a" * 64)
    await service.register_activity(
        token=device["access_token"],
        activity_id="version-check",
        thread_id="thread",
        push_token="b" * 64,
    )
    setattr(owner, field, getattr(owner, field) + 1)
    for token in (device["access_token"], sibling["access_token"]):
        with pytest.raises(OctopError):
            service.authenticate(token)
    with pytest.raises(OctopError):
        await service.exchange_pairing(
            pairing_secret=request["pairing_secret"], network_key="local"
        )
    assert await service.push_targets(1) == []
    assert await service.activity_targets(1, "thread") == []
    _, fresh = await paired(service)
    assert service.authenticate(fresh["access_token"]).device_id == fresh["device_id"]
    with pytest.raises(OctopError):
        service.authenticate(device["access_token"])


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["password_version", "mfa_version"])
async def test_legacy_grants_only_survive_while_account_versions_are_zero(service, field):
    _, device = await paired(service)
    rows = service._read("mobile_access.devices.1", [])
    rows[0].pop("password_version")
    rows[0].pop("mfa_version")
    service._write("mobile_access.devices.1", rows)
    assert service.authenticate(device["access_token"]).device_id == device["device_id"]
    setattr(service._users.get(1), field, 1)
    with pytest.raises(OctopError):
        service.authenticate(device["access_token"])
    # The compatibility read never upgrades the old grant to the current account version.
    assert field not in service._read("mobile_access.devices.1", [])[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("removed", [False, True])
async def test_disabled_or_deleted_account_cannot_authenticate_pair_or_receive_push(
    service, monkeypatch, removed
):
    _, device = await paired(service)
    await service.register_push(token=device["access_token"], platform="apns", push_token="a" * 64)
    if removed:
        monkeypatch.setattr(service._users, "get", lambda uid: None)
    else:
        service._users.get(1).disabled = True
    with pytest.raises(OctopError):
        service.authenticate(device["access_token"])
    assert await service.push_targets(1) == []
    with pytest.raises(OctopError):
        await paired(service)


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["password_version", "mfa_version"])
async def test_prepared_action_proof_cannot_bypass_version_invalidation(service, field):
    server, _ = server_for(service)
    actions = MobileTaskActions(server)
    _, device = await paired(service, ["chat", "tasks"])
    nav = await actions.navigation(device["access_token"], "TASK", 1)
    proof = await actions.prepare(device["access_token"], nav)
    setattr(service._users.get(1), field, 1)
    with pytest.raises(OctopError):
        await actions.prepare(device["access_token"], nav)
    with pytest.raises(OctopError):
        await actions.execute(device["access_token"], proof["confirmation"])
    assert server.task_manager.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["password_version", "mfa_version"])
async def test_invalid_device_has_no_preview_lookup_alert_or_live_activity(
    service, monkeypatch, field
):
    _, device = await paired(service)
    await service.register_push(token=device["access_token"], platform="apns", push_token="a" * 64)
    await service.register_activity(
        token=device["access_token"],
        activity_id="activity",
        thread_id="thread",
        push_token="b" * 64,
    )
    await service.update_notification_preferences(
        token=device["access_token"], changes={"preview": True}
    )
    preview = Mock(return_value="private answer")
    push = MobilePushService(service, preview_source=preview)
    sent = AsyncMock()
    monkeypatch.setattr(push, "_send_apns", sent)
    monkeypatch.setattr(push, "_config", AsyncMock(return_value={"configured": True}))
    setattr(service._users.get(1), field, 1)
    await push.emit(1, {"type": "turn.ended", "thread_id": "thread"})
    assert not push._pending
    preview.assert_not_called()
    # A queued delivery must also re-resolve the grant before generating encrypted output.
    await push._deliver(1, {"type": "turn.ended", "thread_id": "thread"}, "queued private preview")
    sent.assert_not_called()


@pytest.mark.asyncio
async def test_delivery_rechecks_version_after_awaiting_provider_configuration(
    service, monkeypatch
):
    _, device = await paired(service)
    await service.register_push(token=device["access_token"], platform="apns", push_token="a" * 64)
    push = MobilePushService(service)
    entered, release = asyncio.Event(), asyncio.Event()

    async def config(provider):
        entered.set()
        await release.wait()
        return {"configured": True}

    sent = AsyncMock()
    monkeypatch.setattr(push, "_config", config)
    monkeypatch.setattr(push, "_send_apns", sent)
    pending = asyncio.create_task(
        push._deliver(1, {"type": "dashboard_push"}, "private queued preview")
    )
    await asyncio.wait_for(entered.wait(), timeout=2)
    service._users.get(1).password_version += 1
    release.set()
    await asyncio.wait_for(pending, timeout=2)
    sent.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("cached", [False, True])
async def test_production_factory_binds_current_user_repo_even_for_cached_service(service, cached):
    _, device = await paired(service)
    changed = SimpleNamespace(password_version=1, mfa_version=0, disabled=False)
    users = SimpleNamespace(get=lambda uid: changed if uid == 1 else None)
    server = SimpleNamespace(
        services=SimpleNamespace(
            settings_repo=service._settings,
            secret_repo=service._secrets,
            user_repo=users,
        )
    )
    if cached:
        server._mobile_access_service = service
    bound = service_for(server)
    assert (bound is service) is cached
    with pytest.raises(OctopError):
        bound.authenticate(device["access_token"])
