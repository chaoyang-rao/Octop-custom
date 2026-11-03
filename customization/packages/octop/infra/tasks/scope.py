"""Host-only authority for one coordinator continuation, never message metadata."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class CoordinatorContext:
    scope_id: str
    user_id: int
    origin_agent_id: str
    origin_thread_id: str
    parent_task_id: str | None = None
    parent_attempt: int | None = None
    allow_publish: bool = False
    active_signature: str = ""
    system_prompt: str = ""
    user_input: str = ""


_CURRENT: ContextVar[CoordinatorContext | None] = ContextVar(
    "octop_task_coordination", default=None
)


def current_coordinator_scope() -> CoordinatorContext | None:
    return _CURRENT.get()


@contextmanager
def coordinator_scope(context: CoordinatorContext) -> Iterator[None]:
    token = _CURRENT.set(context)
    try:
        yield
    finally:
        _CURRENT.reset(token)
