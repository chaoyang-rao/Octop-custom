"""Project large old tool results to native offload pointers before summarizing."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterator
from typing import Any, cast

from langchain_core.messages import AIMessage, ToolMessage

from octop_harness.middleware.runtime import runtime_config

logger = logging.getLogger(__name__)


def _candidates(mw: Any, request: Any) -> Iterator[tuple[int, ToolMessage, str]]:
    profile = getattr(request.model, "profile", None)
    cap = profile.get("max_input_tokens", 0) if isinstance(profile, dict) else 0
    if not isinstance(cap, int) or cap <= 0:
        return
    effective = mw._get_effective_messages(request)
    if mw._count_tokens(effective, request.system_message, request.tools) < int(cap * 0.75):
        return
    cfg = runtime_config(request).get("configurable") or {}
    event = (request.state or {}).get("_summarization_event")
    start = event.get("cutoff_index", 0) if isinstance(event, dict) else 0
    start = start if isinstance(start, int) and start >= 0 else 0
    calls: set[str] = set()
    threshold = min(4000, max(512, cap // 16))
    for index, message in enumerate(request.messages):
        if isinstance(message, AIMessage):
            calls.update(str(call["id"]) for call in message.tool_calls if call.get("id"))
        if index < start or index >= len(request.messages) - 8:
            continue
        if not isinstance(message, ToolMessage) or message.tool_call_id not in calls:
            continue
        if not isinstance(message.content, str) or mw.token_counter([message]) < threshold:
            continue
        # Reused provider call ids in different rooms or revisions must not
        # overwrite an unrelated result in the shared expert workspace.
        digest = hashlib.sha256((str(cfg.get("thread_id") or "") + message.content).encode()).hexdigest()[:24]
        yield index, message, f"{mw._large_tool_results_prefix}/{digest}"


def prune_context_tools(mw: Any, request: Any) -> Any:
    from deepagents.middleware._message_eviction import _offload_tool_message_content

    messages = list(request.messages)
    changed = False
    for index, message, prefix in _candidates(mw, request):
        try:
            replacement = _offload_tool_message_content(message, cast(str, message.content), mw._backend, prefix)
        except Exception as exc:
            logger.debug("Old tool offload unavailable (%s)", type(exc).__name__)
            continue
        if replacement is not None:
            messages[index] = replacement
            changed = True
    # Keep the raw checkpoint and tool call/result pairing unchanged.
    return request.override(messages=messages) if changed else request


async def aprune_context_tools(mw: Any, request: Any) -> Any:
    from deepagents.middleware._message_eviction import _aoffload_tool_message_content

    messages = list(request.messages)
    changed = False
    for index, message, prefix in _candidates(mw, request):
        try:
            replacement = await _aoffload_tool_message_content(message, cast(str, message.content), mw._backend, prefix)
        except Exception as exc:
            logger.debug("Old tool offload unavailable (%s)", type(exc).__name__)
            continue
        if replacement is not None:
            messages[index] = replacement
            changed = True
    return request.override(messages=messages) if changed else request
