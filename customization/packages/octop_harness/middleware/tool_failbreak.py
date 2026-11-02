"""Tool fail-break: truncate bulky tool results and stop failure loops.

A stuck agent (e.g. ``edit_file`` re-issuing ``String not found`` against a
stale match string) otherwise loops for tens of minutes. This middleware:

1. Truncates oversized ``ToolMessage`` bodies so one huge ``execute`` /
   ``read_file`` output cannot blow the context window in a single step.
   Head and tail are kept (tail carries exit codes / closing output).
2. Counts consecutive failures per tool within one turn and, past a
   threshold, raises :class:`ToolFailbreakError` so the turn ends cleanly
   instead of looping forever.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

logger = logging.getLogger(__name__)

DEFAULT_MAX_RESULT_CHARS = 8000
DEFAULT_MAX_CONSECUTIVE_FAILURES = 5

_TRUNCATION_MARK = "\n…(中间内容已截断，完整结果用 read_file / execute 查看)…\n"

# Per-turn consecutive-failure counter keyed by tool name. Reset via
# ``tool_failbreak_scope()`` at the top of each turn so a prior turn's
# failures never leak into the next one.
_FAILURE_STATE: ContextVar[dict[str, int]] = ContextVar("octop_tool_failbreak", default={})


class ToolFailbreakError(RuntimeError):
    """Raised when one tool keeps failing; ends the turn instead of looping."""


@contextmanager
def tool_failbreak_scope() -> Iterator[None]:
    """Wrap one agent turn; isolates the failure counter from other turns."""
    token = _FAILURE_STATE.set({})
    try:
        yield
    finally:
        _FAILURE_STATE.reset(token)


def _truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    head = max_chars // 2
    tail = max_chars - head
    skipped = len(text) - head - tail
    return text[:head] + _TRUNCATION_MARK.replace("中间", str(skipped)) + text[-tail:]


def _truncate_content(content: Any, max_chars: int) -> Any:
    if isinstance(content, str):
        return _truncate_text(content, max_chars)
    if isinstance(content, list):
        out: list[Any] = []
        changed = False
        for block in content:
            if isinstance(block, str):
                new_block = _truncate_text(block, max_chars)
                out.append(new_block)
                changed = changed or new_block != block
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                text = str(block["text"])
                new_text = _truncate_text(text, max_chars)
                if new_text != text:
                    out.append({**block, "text": new_text})
                    changed = True
                else:
                    out.append(block)
            else:
                out.append(block)
        return out if changed else content
    return content


def _with_content(message: ToolMessage, content: Any) -> ToolMessage:
    if content is message.content:
        return message
    copy = getattr(message, "model_copy", None)
    if callable(copy):
        try:
            return copy(update={"content": content})
        except Exception:  # pragma: no cover - defensive
            pass
    try:
        object.__setattr__(message, "content", content)
    except Exception:  # pragma: no cover - defensive
        message.content = content
    return message


def _is_error(message: ToolMessage) -> bool:
    return str(getattr(message, "status", "") or "") == "error"


class ToolFailbreakMiddleware(AgentMiddleware[Any, Any]):
    """Truncate tool outputs and stop consecutive-failure loops."""

    def __init__(
        self,
        *,
        max_result_chars: int = DEFAULT_MAX_RESULT_CHARS,
        max_consecutive_failures: int = DEFAULT_MAX_CONSECUTIVE_FAILURES,
    ) -> None:
        super().__init__()
        self._max_result_chars = max_result_chars
        self._max_consecutive_failures = max_consecutive_failures

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        tool_name = str((request.tool_call or {}).get("name", "") or "tool")
        result = await handler(request)
        if not isinstance(result, ToolMessage):
            return result

        result = _with_content(result, _truncate_content(result.content, self._max_result_chars))

        state = _FAILURE_STATE.get()
        if _is_error(result):
            count = state.get(tool_name, 0) + 1
            state[tool_name] = count
            logger.warning(
                "tool failbreak: %s failed %d consecutive time(s) this turn",
                tool_name,
                count,
            )
            if count >= self._max_consecutive_failures:
                raise ToolFailbreakError(
                    f"{tool_name} failed {count} times in a row; stopping the turn to "
                    "avoid looping. Re-read the file/inputs before retrying."
                )
        else:
            state.pop(tool_name, None)

        return result


__all__ = [
    "ToolFailbreakError",
    "ToolFailbreakMiddleware",
    "tool_failbreak_scope",
]
