"""Notification choices, activity suppression and explicit filtered previews."""

import asyncio

import pytest
from tests.unit.mobile_access.test_mobile_access_service import paired
from tests.unit.mobile_access.test_mobile_access_service import service as service
from tests.unit.mobile_access.test_push import apns_config

from octop.infra.mobile_access.push import MobilePushService
from octop.infra.mobile_access.summary import redact_summary


async def recipient(service):
    _, result = await paired(service)
    await service.register_push(token=result["access_token"], platform="apns", push_token="a" * 64)
    push = MobilePushService(service)
    await push.configure("apns", apns_config())
    return result, push


@pytest.mark.asyncio
async def test_needs_me_mute_sound_and_expert_switches(service, monkeypatch):
    result, push = await recipient(service)
    calls = []

    async def send(config, token, event, **kwargs):
        calls.append((event, kwargs))

    monkeypatch.setattr(push, "_send_apns", send)
    await service.update_notification_preferences(
        token=result["access_token"], changes={"level": "needs-me", "sound": False}
    )
    await push.emit(
        1,
        {"type": "turn.ended", "agent_id": "expert", "thread_id": "thread", "status": "completed"},
    )
    assert not push._pending
    await push.emit(1, {"type": "approval.required", "agent_id": "expert", "thread_id": "thread"})
    await asyncio.gather(*list(push._pending))
    assert len(calls) == 1 and calls[0][1]["sound"] is False
    await service.update_notification_preferences(
        token=result["access_token"], changes={"muted_until": 0}
    )
    await push.emit(1, {"type": "approval.required", "agent_id": "expert"})
    assert not push._pending
    await service.update_notification_preferences(
        token=result["access_token"], changes={"muted_until": None, "muted_agent_ids": ["expert"]}
    )
    await push.emit(1, {"type": "approval.required", "agent_id": "expert"})
    assert not push._pending
    await push.emit(1, {"type": "approval.required", "agent_id": "other"})
    await asyncio.gather(*list(push._pending))
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_foreground_is_memory_only_and_other_session_activity_expires(service, monkeypatch):
    result, push = await recipient(service)
    before = service._settings.get("mobile_access.devices.1")
    await service.update_notification_preferences(
        token=result["access_token"], changes={"foreground": True}
    )
    assert service._settings.get("mobile_access.devices.1") == before
    await push.emit(1, {"type": "turn.ended"})
    assert not push._pending
    await service.update_notification_preferences(
        token=result["access_token"], changes={"foreground": False}
    )
    service.note_presence(user_id=1, client_id="desktop-session", device_id=None, active=True)
    await push.emit(1, {"type": "turn.ended"})
    assert not push._pending
    assert not service.active_elsewhere(2, "another-phone")
    import time

    now = time.time()
    monkeypatch.setattr("octop.infra.mobile_access.service.time.time", lambda: now + 31)
    assert not service.active_elsewhere(1, result["device_id"])


@pytest.mark.asyncio
async def test_previews_require_recipient_opt_in_and_never_travel_as_metadata(service, monkeypatch):
    result, push = await recipient(service)
    calls = []

    async def send(config, token, event, **kwargs):
        calls.append((event, kwargs))

    monkeypatch.setattr(push, "_send_apns", send)
    frame = {
        "type": "dashboard_push",
        "text": "报告已经完成，可以继续核对。",
        "arguments": {"password": "must never travel"},
    }
    await push.emit(1, frame)
    await asyncio.gather(*list(push._pending))
    assert calls[0][1]["summary"] is None
    await service.update_notification_preferences(
        token=result["access_token"], changes={"preview": True}
    )
    await push.emit(1, frame)
    await asyncio.gather(*list(push._pending))
    assert calls[1][1]["summary"] == frame["text"]
    assert "text" not in calls[1][0] and "arguments" not in calls[1][0]
    await push.emit(1, {"type": "dashboard_push", "text": "password: TestPass12"})
    await asyncio.gather(*list(push._pending))
    assert calls[-1][1]["summary"] is None
    assert "must never travel" not in str(calls)


@pytest.mark.parametrize(
    "value",
    [
        "password: short",
        "密钥为 abc",
        "TestPass12",
        "Bearer private",
        "https://server.example/?token=private",
        "```private code```",
        "ghp_examplecredential",
        "eyJhbGciOiJIUzI1NiJ9.payload.signature",
    ],
)
def test_sensitive_preview_uses_generic_fallback(value):
    assert redact_summary(value) is None


def test_hidden_analysis_is_removed_and_numbers_are_masked():
    assert redact_summary("<think>secret hidden</think>报告已完成") == "报告已完成"
    assert redact_summary("已处理 123456 条记录") == "已处理 ••• 条记录"
