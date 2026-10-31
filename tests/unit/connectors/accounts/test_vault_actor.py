"""Ingress identity scopes cover execution and never remain on consumers."""

from __future__ import annotations

import pytest

from octop.infra.connectors.accounts.actor import (
    actor_stream,
    authenticated_vault_actor,
    current_vault_actor,
)


@pytest.mark.asyncio
async def test_stream_scope_covers_steps_and_close_then_restores_consumer():
    closed = []

    async def stream():
        try:
            yield current_vault_actor()
            yield current_vault_actor()
        finally:
            closed.append(current_vault_actor())

    with authenticated_vault_actor(9):
        wrapped = actor_stream(stream(), 1)
        assert await anext(wrapped) == (True, 1)
        assert current_vault_actor() == (True, 9)
        await wrapped.aclose()
        assert current_vault_actor() == (True, 9)
    assert current_vault_actor() == (False, None)
    assert closed == [(True, 1)]


@pytest.mark.asyncio
async def test_explicit_unauthenticated_scope_and_exception_restore():
    async def stream():
        assert current_vault_actor() == (True, None)
        raise RuntimeError("test error")
        yield None

    with authenticated_vault_actor(1):
        with pytest.raises(RuntimeError, match="test error"):
            async for _ in actor_stream(stream(), None):
                pass
        assert current_vault_actor() == (True, 1)
