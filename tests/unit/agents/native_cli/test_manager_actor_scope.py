"""Internal callers cannot reuse an authenticated actor from checkpoint config."""

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from octop.infra.agents.manager import AgentManager
from octop.infra.connectors.accounts.actor import authenticated_vault_actor, current_vault_actor


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["stream", "call", "resume_hitl"])
@pytest.mark.parametrize("ingress_actor", [None, 1, 2])
async def test_manager_scopes_actual_ingress_or_explicit_deny(entry, ingress_actor):
    observed = []

    async def stream(*args):
        observed.append(current_vault_actor())
        yield "frame"
        observed.append(current_vault_actor())

    async def call(*args):
        observed.append(current_vault_actor())
        return {}

    manager = AgentManager.__new__(AgentManager)
    manager._harness_manager = SimpleNamespace(stream=stream, call=call, resume_hitl=stream)
    manager._primary_for_room = AsyncMock(return_value=None)
    manager._thread_execution_lock = lambda *a: nullcontext()
    manager._track_invocation = lambda *a: nullcontext()
    manager._prepare_stream_request = lambda aid, req: req
    manager._apply_pending_bootstrap_graph_refresh = lambda *a: None
    manager._stream_model_label = lambda *a: "test"
    before = current_vault_actor()
    with authenticated_vault_actor(ingress_actor) if ingress_actor else nullcontext():
        expected = current_vault_actor()
        if entry == "call":
            await manager.call(
                "agent", {"thread_id": "one", "configurable": {"octop_authenticated_user_id": 1}}
            )
        else:
            iterator = (
                manager.resume_hitl("agent", "one", [])
                if entry == "resume_hitl"
                else manager.stream("agent", {"thread_id": "one"})
            )
            async for _ in iterator:
                assert current_vault_actor() == expected
        assert current_vault_actor() == expected
    assert observed and all(value == (True, ingress_actor) for value in observed)
    assert current_vault_actor() == before
