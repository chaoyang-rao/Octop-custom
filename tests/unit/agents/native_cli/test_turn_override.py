"""A selected native engine does not require an old or deleted API model."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from octop.api.routers.chat import turn as module
from octop.api.routers.chat.models import ChatTurnBody


@pytest.mark.asyncio
async def test_native_turn_ignores_stale_api_model_and_keeps_true_engine(monkeypatch):
    from octop.infra.agents.native_cli import model_selection

    select = AsyncMock(return_value=("fake-b", {"cli_model_id": "fake-b"}))
    monkeypatch.setattr(model_selection, "prepare_model_choice", select)
    providers = SimpleNamespace(is_model_ref_usable=Mock(return_value=False))
    registry = SimpleNamespace(
        native_execution_ref=lambda aid: "native_cli_owned/session", providers=providers
    )
    composer = []
    threads = SimpleNamespace(update_composer=lambda tid, **kw: composer.append((tid, kw)))
    server = SimpleNamespace(
        app_runtime=SimpleNamespace(
            agent_registry=registry, gateway=SimpleNamespace(thread_registry=threads)
        )
    )
    monkeypatch.setattr(
        module, "require_agent_row", lambda *a, **kw: SimpleNamespace(default_model=None)
    )
    monkeypatch.setattr(module, "validate_chat_mcp_servers", AsyncMock(return_value=None))
    monkeypatch.setattr(module, "validate_chat_skills", AsyncMock(return_value=None))
    monkeypatch.setattr(
        module, "resolve_thread_id", AsyncMock(return_value=("thread1", "session1"))
    )
    prepared = await module.prepare_dashboard_turn(
        server,
        agent_id="owned",
        user=SimpleNamespace(id=1),
        turn=ChatTurnBody.from_ws_payload(
            {
                "text": "hello",
                "default_model": "removed-api/deleted-model",
                "native_model_id": "fake-b",
            }
        ),
    )
    assert prepared.model_ref == "native_cli_owned/session"
    assert composer[0][1]["model_ref"] == "native_cli_owned/session"
    providers.is_model_ref_usable.assert_not_called()
    assert select.await_args.kwargs["selected"] == "fake-b"
    inbound = module.build_dashboard_inbound(
        agent_id="owned",
        user_id=1,
        prepared=prepared,
        turn=ChatTurnBody(text="hello"),
        ws_connection_id="connection",
    )
    assert inbound.metadata["native_cli_model_id"] == "fake-b"
    assert prepared.composer_context["cli_model_id"] == "fake-b"
