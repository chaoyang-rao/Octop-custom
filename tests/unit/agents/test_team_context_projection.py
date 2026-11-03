"""Room instructions are invocation context, never repeated checkpoint messages."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage, SystemMessage
from octop_harness.request import ChatRequest

from octop.infra.agents.teams.team_manager import wire_host_dispatch


@pytest.mark.asyncio
async def test_dispatch_background_is_not_appended_to_peer_history() -> None:
    harness = SimpleNamespace()
    wire_host_dispatch(
        harness,
        is_team=lambda _: True,
        take_prompt=lambda *_: (
            "Analyze the evidence",
            "[Team assignment, not a direct user question]",
        ),
    )
    for _ in range(2):
        request = await harness._enrich_request(
            "expert", ChatRequest(messages="input", thread_id="room~expert")
        )
        assert not any(isinstance(item, SystemMessage) for item in request.messages)
        assert len(request.messages) == 1 and isinstance(request.messages[0], HumanMessage)
        assert request.configurable["octop_team_assignment"] is True
