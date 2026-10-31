"""Trusted ingress identity for vault tools, including resumed graph executions."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_UNSET = object()
_actor: ContextVar[object] = ContextVar("octop_vault_authenticated_actor", default=_UNSET)


@contextmanager
def authenticated_vault_actor(user_id: int | None) -> Iterator[None]:
    """Scope a server-authenticated actor; explicit None denies checkpoint fallback.

    Enter this around the *execution* of an async event stream, not its creation.
    Never derive the value from model arguments or client metadata.
    """
    value = (
        user_id
        if isinstance(user_id, int) and not isinstance(user_id, bool) and user_id > 0
        else None
    )
    token = _actor.set(value)
    try:
        yield
    finally:
        _actor.reset(token)


def current_vault_actor() -> tuple[bool, int | None]:
    """Return whether ingress set an actor plus its trusted identity."""
    value = _actor.get()
    return value is not _UNSET, value if isinstance(value, int) and not isinstance(
        value, bool
    ) else None


async def actor_stream[T](stream: AsyncIterator[T], user_id: int | None) -> AsyncIterator[T]:
    """Run every stream step under ingress identity and restore before yielding.

    Restoring between yielded frames prevents an unclosed stream from changing
    its consumer's actor. Tasks created during graph steps inherit this scope.
    """
    iterator = stream.__aiter__()
    try:
        while True:
            with authenticated_vault_actor(user_id):
                try:
                    item = await anext(iterator)
                except StopAsyncIteration:
                    return
            yield item
    finally:
        close = getattr(iterator, "aclose", None)
        if callable(close):
            with authenticated_vault_actor(user_id):
                await close()
