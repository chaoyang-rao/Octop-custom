"""Conversation-mode stamping on dashboard harness requests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import HumanMessage
from octop_gateway.models import ChannelSubject, InboundMessage, TextContent

from octop.infra.connectors.accounts.actor import (
    authenticated_vault_actor,
    current_vault_actor,
)
from octop.infra.gateway.process.processor import GlobalProcessor, _overwrite_last_user_text
from octop.infra.gateway.slash.dispatcher import SlashDispatcher


def _processor(*, thread: SimpleNamespace | None) -> GlobalProcessor:
    agent_manager = MagicMock()
    agent_manager.merge_turn_mcp_servers = MagicMock(return_value=None)
    agent_manager.get_row = MagicMock(return_value=None)
    agent_manager.default_mcp_servers = MagicMock(return_value=[])
    agent_manager.default_knowledge_base_ids = MagicMock(return_value=[])
    agent_manager.providers = MagicMock()
    agent_manager.providers.is_model_ref_usable = MagicMock(return_value=False)
    agent_manager.providers.resolve_explicit_default_model = MagicMock(return_value=None)
    agent_manager.providers.resolve_model_for_multimodal_turn = MagicMock(
        side_effect=lambda ref, **_k: ref
    )
    agent_manager.get_thread_model = MagicMock(return_value=None)
    thread_registry = MagicMock()
    thread_registry.get_thread = MagicMock(return_value=thread)
    thread_registry.update_composer = MagicMock()
    return GlobalProcessor(
        agent_manager=agent_manager,
        thread_registry=thread_registry,
        audit_repo=MagicMock(),
        agent_repo=MagicMock(get=MagicMock(return_value=MagicMock(default_model=None))),
        user_repo=MagicMock(
            get=MagicMock(return_value=SimpleNamespace(locale="zh", preferences_json=None))
        ),
        connector_repo=MagicMock(),
        dispatcher=SlashDispatcher(),
        usage_repo=None,
        gateway=None,
    )


def test_overwrite_last_user_text_keeps_human_kwargs() -> None:
    request: dict[str, object] = {
        "messages": [HumanMessage(content="执行", additional_kwargs={"composer": True})],
    }
    _overwrite_last_user_text(request, "请按 plans/foo.md 执行")
    last = request["messages"][0]
    assert isinstance(last, HumanMessage)
    assert last.content == "请按 plans/foo.md 执行"
    assert last.additional_kwargs == {"composer": True}


@pytest.mark.asyncio
async def test_dashboard_execute_overwrites_user_text() -> None:
    processor = _processor(
        thread=SimpleNamespace(
            conversation_mode="plan",
            pending_plan_path="plans/foo.md",
            model_ref=None,
        )
    )
    msg = InboundMessage(
        channel_id="ws",
        channel_type="dashboard",
        tenant_id="agent-1",
        channel_subject=ChannelSubject(subject_id="1"),
        content=[TextContent(text="按计划执行")],
        metadata={},
    )
    request = await processor._build_dashboard_request(
        msg,
        agent_id="agent-1",
        user_id=1,
        session_key="sk",
        thread_id="thr",
        meta={},
    )
    assert request["messages"][0]["content"] == "请按 plans/foo.md 执行"
    assert request["conversation_mode"] == "craft"
    processor._thread_registry.update_composer.assert_called_once_with(
        "thr",
        conversation_mode="craft",
        pending_plan_path=None,
    )


@pytest.mark.asyncio
async def test_dashboard_mode_switch_keeps_pending_plan() -> None:
    processor = _processor(
        thread=SimpleNamespace(
            conversation_mode="plan",
            pending_plan_path="plans/foo.md",
            model_ref=None,
        )
    )
    msg = InboundMessage(
        channel_id="ws",
        channel_type="dashboard",
        tenant_id="agent-1",
        channel_subject=ChannelSubject(subject_id="1"),
        content=[TextContent(text="先问一句")],
        metadata={"conversation_mode": "ask"},
    )
    request = await processor._build_dashboard_request(
        msg,
        agent_id="agent-1",
        user_id=1,
        session_key="sk",
        thread_id="thr",
        meta={"conversation_mode": "ask"},
    )
    assert request["messages"][0]["content"] == "先问一句"
    assert request["conversation_mode"] == "ask"
    processor._thread_registry.update_composer.assert_called_once_with(
        "thr",
        conversation_mode="ask",
    )


@pytest.mark.asyncio
async def test_dashboard_turn_applies_hitl_policy() -> None:
    processor = _processor(
        thread=SimpleNamespace(
            conversation_mode="craft",
            pending_plan_path=None,
            model_ref=None,
        )
    )
    msg = InboundMessage(
        channel_id="ws",
        channel_type="dashboard",
        tenant_id="agent-1",
        channel_subject=ChannelSubject(subject_id="1"),
        content=[TextContent(text="hello")],
        metadata={"hitl_policy": {"mode": "allow_all"}},
    )
    await processor._build_dashboard_request(
        msg,
        agent_id="agent-1",
        user_id=1,
        session_key="sk",
        thread_id="thr",
        meta={"hitl_policy": {"mode": "allow_all"}},
    )
    assert processor.hitl_coordinator.session_policies.get("thr").mode == "allow_all"


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["dashboard", "cli", "mcp", "feishu"])
async def test_auto_approved_resume_preserves_only_trusted_ingress_actor(channel) -> None:
    processor = _processor(
        thread=SimpleNamespace(conversation_mode="craft", pending_plan_path=None, model_ref=None)
    )
    processor._agent_repo.get.return_value.user_id = 1
    actors = []

    async def stream(*_args, **_kwargs):
        actors.append(current_vault_actor())
        yield {
            "type": "hitl_required",
            "request": {"action_requests": [{"name": "execute", "args": {}}]},
        }

    async def resume(*_args, **_kwargs):
        actors.append(current_vault_actor())
        yield {"type": "token", "content": "approved result"}

    processor._agent_manager.stream = stream
    processor._agent_manager.resume_hitl = resume
    msg = InboundMessage(
        channel_id="ws",
        channel_type=channel,
        tenant_id="agent-1",
        channel_subject=ChannelSubject(subject_id="1"),
        content=[TextContent(text="run")],
        metadata={"thread_id": "thr", "hitl_policy": {"mode": "allow_all"}},
    )
    with authenticated_vault_actor(99):
        chunks = [chunk async for chunk in processor.iter_turn_chunks(msg)]
        assert current_vault_actor() == (True, 99)

    expected = 1 if channel in ("dashboard", "cli", "mcp") else None
    assert actors == [(True, expected), (True, expected)]
    assert any(chunk.get("content") == "approved result" for chunk in chunks)


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["dashboard", "feishu"])
async def test_chat_answer_resume_preserves_only_trusted_ingress_actor(channel) -> None:
    processor = _processor(thread=None)
    processor._agent_repo.get.return_value.user_id = 1
    actors = []

    async def resume(*_args, **_kwargs):
        actors.append(current_vault_actor())
        yield {"type": "token", "content": "answered result"}

    processor._agent_manager.resume_hitl = resume
    processor.hitl_coordinator.store.register(
        thread_id="thr",
        agent_id="agent-1",
        user_id=1,
        session_key="sk",
        channel_type=channel,
        action_requests=[
            {
                "name": "ask_user_question",
                "args": {"questions": [{"header": "Q1", "question": "Continue?"}]},
            }
        ],
        review_configs=[{"action_name": "ask_user_question", "allowed_decisions": ["respond"]}],
    )
    msg = InboundMessage(
        channel_id="ws",
        channel_type=channel,
        tenant_id="agent-1",
        channel_subject=ChannelSubject(subject_id="1"),
        content=[TextContent(text="continue")],
        metadata={"session_key": "sk", "thread_id": "thr"},
    )
    with authenticated_vault_actor(99):
        chunks = [chunk async for chunk in processor.iter_turn_chunks(msg)]
        assert current_vault_actor() == (True, 99)

    assert actors == [(True, 1 if channel == "dashboard" else None)]
    assert any(chunk.get("content") == "answered result" for chunk in chunks)
    processor._agent_manager.stream.assert_not_called()
