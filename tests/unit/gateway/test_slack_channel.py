"""Slack routing, lifecycle, event acknowledgement and credential boundaries."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from octop_gateway.models import ChannelSubject, MessageEvent

from octop.infra.gateway.channels.host_channels import register_host_channels
from octop.infra.gateway.channels.slack import SlackChannel, SlackConfig
from octop.infra.gateway.process.message_keys import sanitize_im_metadata, session_key_from_message


async def processor(message):
    yield MessageEvent.completed()


def make_channel(**config):
    channel = SlackChannel(
        processor,
        config=SlackConfig.from_dict(config),
        channel_id="registration",
        tenant_id="owned-agent",
    )
    channel._team_id = "T1"
    channel._bot_user_id = "UBOT"
    return channel


def envelope(*, channel="C123", user="U123", ts="1.001", team="T1", **extra):
    return {
        "type": "events_api",
        "envelope_id": "receipt",
        "payload": {
            "team_id": team,
            "event": {
                "type": "app_mention",
                "channel": channel,
                "user": user,
                "ts": ts,
                "text": "<@UBOT> hello",
                **extra,
            },
        },
    }


@pytest.mark.asyncio
async def test_ack_duplicate_workspace_and_allowlist():
    channel = make_channel(allowed_channel_ids="C123", allowed_user_ids="U123")
    socket = SimpleNamespace(send_json=AsyncMock())
    channel._socket = socket
    received = []
    channel.set_enqueue_callback(received.append)
    event = envelope()
    await channel._handle_envelope(event)
    await channel._handle_envelope(envelope(type="message"))
    await channel._handle_envelope(envelope(team="OTHER", ts="2.001"))
    await channel._handle_envelope(envelope(channel="C999", ts="2.002"))
    await channel._handle_envelope(envelope(user="UBOT", ts="2.003"))
    await channel._handle_envelope(envelope(bot_id="BOTHER", ts="2.004"))
    await channel._handle_envelope(envelope(subtype="message_changed", ts="2.005"))
    await channel._handle_envelope(envelope(type="message", text="no mention", ts="2.006"))
    assert socket.send_json.await_count == 8
    assert len(received) == 1
    assert received[0].tenant_id == "owned-agent"
    assert received[0].text == "hello"


@pytest.mark.asyncio
async def test_dm_denied_unless_user_explicitly_allowed():
    channel = make_channel(allow_all_channels=True)
    received = []
    channel.set_enqueue_callback(received.append)
    await channel._handle_envelope(envelope(channel="D123", type="message"))
    assert received == []
    channel._config.allowed_user_ids = ["U123"]
    await channel._handle_envelope(envelope(channel="D123", type="message"))
    assert len(received) == 1
    assert received[0].channel_subject.chat_type == "dm"


def test_thread_routing_and_durable_push_address():
    channel = make_channel()
    first = channel.parse_inbound(envelope()["payload"]["event"])
    reply = channel.parse_inbound(envelope(ts="2.001", thread_ts="1.001")["payload"]["event"])
    other = channel.parse_inbound(envelope(ts="3.001")["payload"]["event"])

    def key(msg):
        return session_key_from_message(msg, agent_id="owned-agent")

    assert key(first) == key(reply)
    assert key(first) != key(other)
    assert sanitize_im_metadata(reply)["thread_ts"] == "1.001"
    assert SlackChannel._destination(
        ChannelSubject(subject_id=first.channel_subject.subject_id)
    ) == {
        "channel": "C123",
        "thread_ts": "1.001",
    }
    assert "sender_id" not in sanitize_im_metadata(reply)


def test_untrusted_attachment_urls_are_not_forwarded_bot_credentials():
    channel = make_channel()
    event = envelope(
        files=[
            {"url_private": "https://attacker.example/a.png", "size": 100, "mimetype": "image/png"},
            {
                "url_private": "https://files.slack.com/a.png",
                "size": 100,
                "mimetype": "image/png",
                "name": "a.png",
            },
            {"url_private": "https://files.slack.com/huge", "size": 30 * 1024 * 1024},
        ]
    )["payload"]["event"]
    message = channel.parse_inbound(event)
    assert len(message.content) == 2
    assert message.content[1].url == "https://files.slack.com/a.png"


@pytest.mark.asyncio
async def test_reply_stays_in_thread_and_disables_mentions(monkeypatch):
    channel = make_channel()
    api = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(channel, "_api", api)
    await channel._send_text(ChannelSubject(subject_id="C123:1.001"), "<!channel> & <@U123>")
    payload = api.call_args.args[1]
    assert payload["channel"] == "C123" and payload["thread_ts"] == "1.001"
    assert "<!channel>" not in payload["text"]
    assert payload["mrkdwn"] is False and payload["unfurl_links"] is False


@pytest.mark.asyncio
async def test_connection_errors_do_not_expose_socket_url(monkeypatch):
    channel = make_channel(bot_token="private-bot", app_token="private-app")
    monkeypatch.setattr(
        channel, "_api", AsyncMock(return_value={"team_id": "T1", "user_id": "UBOT"})
    )
    monkeypatch.setattr(
        channel, "_connect", AsyncMock(side_effect=RuntimeError("wss://example?ticket=private"))
    )
    with pytest.raises(RuntimeError, match="^slack_connection_failed$"):
        await channel.start()
    assert channel._reader is None
    assert not channel.is_connected


@pytest.mark.asyncio
async def test_registered_transport_works_with_channel_manager(monkeypatch, tmp_path):
    from octop_gateway.manager import ChannelManager
    from octop_gateway.media import FileSystemMediaBackend

    monkeypatch.setenv("OCTOP_HOME", str(tmp_path))
    monkeypatch.setattr(SlackChannel, "start", AsyncMock())
    register_host_channels()
    manager = ChannelManager(
        processor=processor, media_backend=FileSystemMediaBackend(str(tmp_path))
    )
    await manager.start()
    try:
        await manager.add_channel(
            "slack",
            {"bot_token": "fake", "app_token": "fake", "allowed_channel_ids": "C123"},
            channel_id="slack1",
            tenant_id="owned-agent",
        )
        channel = manager.get_channel("slack1")
        assert isinstance(channel, SlackChannel)
        assert channel.tenant_id == "owned-agent"
        assert channel._config.allowed_channel_ids == ["C123"]
    finally:
        await manager.stop()


@pytest.mark.parametrize("value", [True, ["#general"], [123], {"U123": True}])
def test_invalid_allowlist_rejected(value):
    with pytest.raises(ValueError):
        SlackConfig.from_dict({"allowed_user_ids": value})
