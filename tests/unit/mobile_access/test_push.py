"""Push provider configuration and payload privacy without external requests."""

from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from tests.unit.mobile_access.test_mobile_access_service import paired
from tests.unit.mobile_access.test_mobile_access_service import service as service

from octop.infra.errors import OctopError
from octop.infra.mobile_access.push import MobilePushService


def apns_config():
    key = ec.generate_private_key(ec.SECP256R1())
    return {
        "team_id": "ABCDEFGHIJ",
        "key_id": "KLMNOPQRST",
        "topic": "com.octop.mobile",
        "sandbox": True,
        "private_key": key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode(),
    }


@pytest.mark.asyncio
async def test_provider_key_is_encrypted_and_status_has_no_credentials(service):
    push = MobilePushService(service)
    config = apns_config()
    await push.configure("apns", config)
    assert config["private_key"] not in service._settings.get("mobile_access.push.apns")
    assert await push.configuration_status() == {"apns": True, "fcm": False}
    await push.configure("apns", None)
    assert await push.configuration_status() == {"apns": False, "fcm": False}
    with pytest.raises(ValueError):
        await push.configure("apns", {**config, "key_id": "not-valid"})


@pytest.mark.asyncio
async def test_only_authorized_devices_receive_metadata_not_transcripts(service, monkeypatch):
    _, result = await paired(service)
    await service.register_push(token=result["access_token"], platform="apns", push_token="a" * 64)
    push = MobilePushService(service)
    await push.configure("apns", apns_config())
    received = []

    async def send(config, token, event, **kwargs):
        received.append(event)

    monkeypatch.setattr(push, "_send_apns", send)
    await push.emit(
        1,
        {
            "type": "turn.ended",
            "thread_id": "thread",
            "text": "private answer",
            "prompt": "private question",
            "arguments": {"secret": "hidden"},
        },
    )
    import asyncio

    await asyncio.gather(*list(push._pending))
    assert len(received) == 1
    assert "private" not in str(received) and "hidden" not in str(received)
    assert received[0]["thread_id"] == "thread"
    await service.revoke(user_id=1, device_id=result["device_id"])
    await push.emit(1, {"type": "turn.ended", "thread_id": "thread"})
    await asyncio.gather(*list(push._pending))
    assert len(received) == 1
    await push.stop()


@pytest.mark.asyncio
async def test_live_activity_tokens_are_encrypted_and_scoped_to_thread(service):
    _, result = await paired(service)
    await service.register_activity(
        token=result["access_token"],
        activity_id="activity-1",
        thread_id="owned-thread",
        push_token="b" * 64,
    )
    assert "b" * 64 not in service._settings.get("mobile_access.devices.1")
    assert len(await service.activity_targets(1, "owned-thread")) == 1
    assert await service.activity_targets(2, "owned-thread") == []
    assert await service.activity_targets(1, "another-thread") == []
    await service.revoke(user_id=1, device_id=result["device_id"])
    assert await service.activity_targets(1, "owned-thread") == []
    with pytest.raises(OctopError):
        await service.register_activity(
            token=result["access_token"],
            activity_id="activity-2",
            thread_id="owned-thread",
            push_token="b" * 64,
        )


@pytest.mark.asyncio
async def test_apns_live_activity_uses_specific_topic_and_end_payload(service, monkeypatch):
    calls = []

    class FakeClient:
        def __init__(self, **kwargs):
            assert kwargs.get("http2") is True and kwargs.get("follow_redirects") is False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, **kwargs):
            calls.append((url, kwargs))
            return SimpleNamespace(raise_for_status=lambda: None)

    monkeypatch.setattr("octop.infra.mobile_access.push.httpx.AsyncClient", FakeClient)
    push = MobilePushService(service)
    await push._send_apns(
        apns_config(), "c" * 64, {"type": "turn.ended", "thread_id": "owned"}, live_activity=True
    )
    assert calls[0][0].startswith("https://api.sandbox.push.apple.com/3/device/")
    data = calls[0][1]
    assert data["headers"]["apns-push-type"] == "liveactivity"
    assert data["headers"]["apns-topic"] == "com.octop.mobile.push-type.liveactivity"
    assert data["json"]["aps"]["event"] == "end"
    assert data["json"]["aps"]["content-state"]["status"] == "complete"


@pytest.mark.asyncio
async def test_unconfigured_chat_events_create_no_identity_or_background_tasks(service):
    push = MobilePushService(service)
    assert service._secrets.get("mobile_access.host_identity") is None
    await push.emit(1, {"type": "turn.ended", "thread_id": "ordinary-chat"})
    assert not push._pending
    assert service._secrets.get("mobile_access.host_identity") is None
    assert service._settings.get("mobile_access.devices.1") is None


@pytest.mark.asyncio
async def test_live_activity_only_device_receives_updates_without_normal_push_token(
    service, monkeypatch
):
    _, result = await paired(service)
    await service.register_activity(
        token=result["access_token"],
        activity_id="activity-only",
        thread_id="working-thread",
        push_token="d" * 64,
    )
    push = MobilePushService(service)
    await push.configure("apns", apns_config())
    calls = []

    async def send(config, token, event, **kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(push, "_send_apns", send)
    await push.emit(1, {"type": "turn.ended", "thread_id": "working-thread"})
    import asyncio

    await asyncio.gather(*list(push._pending))
    assert len(calls) == 1 and calls[0]["live_activity"] is True


@pytest.mark.asyncio
async def test_task_notify_false_and_turn_start_only_update_live_activity(service, monkeypatch):
    import asyncio

    _, result = await paired(service)
    await service.register_push(token=result["access_token"], platform="apns", push_token="a" * 64)
    await service.register_activity(
        token=result["access_token"],
        activity_id="activity",
        thread_id="thread",
        push_token="b" * 64,
    )
    push = MobilePushService(service)
    await push.configure("apns", apns_config())
    calls = []

    async def send(config, token, event, **kwargs):
        calls.append((event, kwargs))

    monkeypatch.setattr(push, "_send_apns", send)
    for frame in [
        {"type": "turn.started", "thread_id": "thread"},
        {
            "type": "task.updated",
            "thread_id": "thread",
            "status": "completed",
            "notify": False,
            "prompt": "private",
        },
    ]:
        await push.emit(1, frame)
        await asyncio.gather(*list(push._pending))
    assert len(calls) == 2 and all(kwargs.get("live_activity") is True for _, kwargs in calls)
    assert calls[1][0]["notify"] == "false" and "private" not in str(calls)


@pytest.mark.asyncio
async def test_invalid_target_retirement_never_removes_a_new_registration(service):
    _, result = await paired(service)
    token = result["access_token"]
    await service.register_push(token=token, platform="apns", push_token="a" * 64)
    await service.register_push(token=token, platform="apns", push_token="b" * 64)
    await service.retire_push(1, result["device_id"], "a" * 64)
    assert (await service.push_targets(1))[0]["token"] == "b" * 64
    await service.retire_push(1, result["device_id"], "b" * 64)
    assert await service.push_targets(1) == []
