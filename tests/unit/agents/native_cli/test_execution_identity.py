"""Checked channel/cron execution authority is separate from vault login identity."""

from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage
from octop_gateway.models import MessageEvent
from tests.unit.agents.native_cli.test_graph_acp import graph_for, runtime_for

from octop.infra.connectors.accounts.actor import authenticated_vault_actor
from octop.infra.gateway.channels.slack import SlackChannel, SlackConfig
from octop.infra.gateway.process.harness_request import build_harness_request
from octop.infra.gateway.process.message_keys import resolve_user_id_for_message


@pytest.mark.asyncio
async def test_real_slack_allowlist_then_server_owner_stamp_runs_native_without_vault_login(
    tmp_path,
):
    received = []

    async def process(message):
        yield MessageEvent.completed()

    channel = SlackChannel(
        process,
        config=SlackConfig(allowed_channel_ids=["C123"]),
        tenant_id="agent1",
        channel_id="registered",
    )
    channel._team_id = "T1"
    channel._bot_user_id = "UBOT"
    channel.set_enqueue_callback(received.append)
    envelope = {
        "type": "events_api",
        "envelope_id": "receipt",
        "payload": {
            "team_id": "T1",
            "event": {
                "type": "app_mention",
                "channel": "C123",
                "user": "U123",
                "text": "<@UBOT> native request",
                "ts": "1.001",
            },
        },
    }
    await channel._handle_envelope(envelope)
    assert len(received) == 1
    uid = resolve_user_id_for_message(received[0], agent_owner_id=1)
    request = build_harness_request(
        thread_id="thread1",
        user_id=uid,
        source="slack/registered",
        agent_id="agent1",
        text=received[0].text,
    )
    assert request["configurable"]["octop_execution_user_id"] == 1
    runtime, _ = runtime_for(tmp_path, mode="text")
    try:
        with authenticated_vault_actor(None):
            result = await graph_for(runtime, []).ainvoke(
                {"messages": [HumanMessage(content=received[0].text)]},
                config={"configurable": {"thread_id": "thread1", **request["configurable"]}},
            )
        assert result["messages"][-1].content == "native text"
    finally:
        await runtime.aclose()


@pytest.mark.asyncio
async def test_authorized_cron_owner_stamp_runs_native_with_no_authenticated_login(tmp_path):
    request = build_harness_request(
        thread_id="thread1",
        user_id=1,
        source="cron/owned-job",
        agent_id="agent1",
        text="scheduled work",
    )
    assert request["configurable"]["octop_execution_user_id"] == 1
    runtime, _ = runtime_for(tmp_path, mode="text")
    try:
        with authenticated_vault_actor(None):
            result = await graph_for(runtime, []).ainvoke(
                {"messages": [HumanMessage(content="scheduled work")]},
                config={"configurable": {"thread_id": "thread1", **request["configurable"]}},
            )
        assert result["messages"][-1].content == "native text"
    finally:
        await runtime.aclose()
