"""Context window usage without checkpoint reads on dashboard requests."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

logger = logging.getLogger(__name__)

# Prefer harness SoT when present (PyPI may lag local editable installs).
_FALLBACK_SEGMENT_KEYS: tuple[str, ...] = (
    "system_prompt",
    "tool_definitions",
    "rules",
    "skills",
    "mcp",
    "subagent_definitions",
    "conversation",
)

try:
    from octop_harness.context_usage import SEGMENT_KEYS as SEGMENT_KEYS
except ImportError:  # pragma: no cover - older octop-harness wheels
    SEGMENT_KEYS = _FALLBACK_SEGMENT_KEYS

__all__ = [
    "SEGMENT_KEYS",
    "ContextBreakdownResult",
    "compute_context_breakdown",
    "usage_dict_from_message",
]


@dataclass(frozen=True)
class ContextBreakdownResult:
    max_tokens: int
    used_tokens: int
    segments: dict[str, int]
    decision_saved: int = 0
    estimated: bool = False


def _empty_breakdown(*, max_tokens: int) -> ContextBreakdownResult:
    cap = max(0, max_tokens)
    return ContextBreakdownResult(
        max_tokens=cap,
        used_tokens=0,
        segments=dict.fromkeys(SEGMENT_KEYS, 0),
        estimated=True,
    )


def _usage_to_breakdown(usage: Any, *, fallback_max_tokens: int) -> ContextBreakdownResult:
    raw_segments = getattr(usage, "segments", None) or {}
    segments = {key: int(raw_segments.get(key, 0) or 0) for key in SEGMENT_KEYS}
    current_budget = _token_int(getattr(usage, "budget_version", 0)) >= 2
    cap = (
        max(0, int(getattr(usage, "max_tokens", fallback_max_tokens) or 0))
        if current_budget
        else max(0, fallback_max_tokens)
    )
    raw_used = _token_int(getattr(usage, "input_tokens", 0)) or _token_int(
        getattr(usage, "used_tokens", 0)
    )
    used = min(raw_used, cap) if cap else raw_used
    saved = _token_int(getattr(usage, "decision_saved", 0))
    return ContextBreakdownResult(
        max_tokens=cap,
        used_tokens=used,
        segments=segments,
        decision_saved=saved,
        estimated=getattr(usage, "estimated", True) is not False or not current_budget,
    )


def _from_stream_input_tokens(input_tokens: int, *, max_tokens: int) -> ContextBreakdownResult:
    """Minimal fallback when harness has no persisted breakdown yet."""
    cap = max(0, max_tokens)
    used = min(max(0, input_tokens), cap) if cap else max(0, input_tokens)
    segments = dict.fromkeys(SEGMENT_KEYS, 0)
    segments["conversation"] = used
    return ContextBreakdownResult(
        max_tokens=cap, used_tokens=used, segments=segments, estimated=True
    )


def _persisted_context(
    message_repo: Any, thread_id: str, executor_id: str, room: bool, fallback_max_tokens: int
) -> ContextBreakdownResult | None:
    reader = getattr(message_repo, "recent_context_candidates", None)
    if not callable(reader):
        return None
    for row in reader(thread_id):
        try:
            wire = json.loads(row.message_json)
            data = wire.get("data", wire)
            extra = data.get("additional_kwargs") or {}
            speaker = str(extra.get("speaker_agent_id") or "")
            if (speaker and speaker != executor_id) or (room and not speaker):
                continue
            snapshot = extra.get("context_usage")
            if not isinstance(snapshot, dict):
                continue
            if _token_int(snapshot.get("budget_version")) >= 2:
                if (
                    snapshot.get("thread_id") != thread_id
                    or snapshot.get("agent_id") != executor_id
                ):
                    continue
            elif snapshot.get("thread_id") not in (None, "", thread_id) or snapshot.get(
                "agent_id"
            ) not in (None, "", executor_id):
                continue
            return _usage_to_breakdown(
                SimpleNamespace(**snapshot), fallback_max_tokens=fallback_max_tokens
            )
        except (ValueError, TypeError, AttributeError):
            continue
    return None


def _usage_has_segments(usage: Any) -> bool:
    if usage is None:
        return False
    used = int(getattr(usage, "used_tokens", 0) or 0)
    inp = int(getattr(usage, "input_tokens", 0) or 0)
    raw = getattr(usage, "segments", None) or {}
    return used > 0 or inp > 0 or any(int(raw.get(k, 0) or 0) > 0 for k in SEGMENT_KEYS)


def _token_int(value: Any) -> int:
    if isinstance(value, bool) or value is None:
        return 0
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 0
    return n if n > 0 else 0


def _as_mapping(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        out = dump()
        return out if isinstance(out, dict) else None
    if value is not None and hasattr(value, "items"):
        try:
            return dict(value)
        except Exception:
            return None
    return None


def _io_from_mapping(data: dict[str, Any] | None) -> tuple[int, int]:
    if not data:
        return 0, 0
    nested = _as_mapping(data.get("token_usage") or data.get("usage"))
    src = nested or data
    inp = (
        _token_int(src.get("input_tokens"))
        or _token_int(src.get("prompt_tokens"))
        or _token_int(src.get("used_tokens"))
    )
    out = _token_int(src.get("output_tokens")) or _token_int(src.get("completion_tokens"))
    return inp, out


def _additional_kwargs(msg: Any) -> dict[str, Any] | None:
    kwargs = getattr(msg, "additional_kwargs", None)
    if kwargs is None and isinstance(msg, dict):
        kwargs = msg.get("additional_kwargs") or msg.get("kwargs")
    return _as_mapping(kwargs)


def usage_dict_from_message(msg: Any) -> dict[str, Any] | None:
    """Normalize LangChain token counts for history + the context ring.

    Stock occupancy lives on ``additional_kwargs['context_usage']``. Billing
    counts may also sit on ``usage_metadata`` / ``response_metadata``.
    """
    if isinstance(msg, dict) and "kwargs" in msg and "lc" in msg:
        msg = msg.get("kwargs") or msg

    kwargs = _additional_kwargs(msg)
    stamped = kwargs.get("context_usage") if kwargs else None
    inp, out = _io_from_mapping(_as_mapping(stamped))

    usage = getattr(msg, "usage_metadata", None)
    if usage is None and isinstance(msg, dict):
        usage = msg.get("usage_metadata")
    mapped_usage = _as_mapping(usage)
    if inp == 0 and out == 0:
        inp, out = _io_from_mapping(mapped_usage)

    rm = getattr(msg, "response_metadata", None)
    if rm is None and isinstance(msg, dict):
        rm = msg.get("response_metadata")
    mapped_response = _as_mapping(rm)
    if inp == 0 and out == 0:
        inp, out = _io_from_mapping(mapped_response)

    saved = _token_int(stamped.get("decision_saved")) if isinstance(stamped, dict) else 0
    if inp == 0 and out == 0 and saved == 0:
        return None
    payload: dict[str, Any] = {
        "input_tokens": inp,
        "output_tokens": out,
        "total_tokens": inp + out,
    }
    wire = (
        _as_mapping(mapped_response.get("token_usage") or mapped_response.get("usage"))
        if mapped_response
        else None
    )
    merged = {**(wire or {}), **(mapped_usage or {})}
    if merged:
        details = merged.get("input_token_details") or merged.get("prompt_tokens_details")
        if details is not None:
            payload["input_token_details"] = details
        out_details = merged.get("output_token_details") or merged.get("completion_tokens_details")
        if out_details is not None:
            payload["output_token_details"] = out_details
        cache_read = _token_int(merged.get("cache_read_tokens")) or _token_int(
            merged.get("prompt_cache_hit_tokens")
        )
        cache_write = _token_int(merged.get("cache_write_tokens"))
        uncached_raw = merged.get("uncached_input_tokens")
        uncached = (
            _token_int(uncached_raw)
            if uncached_raw is not None
            else max(0, inp - cache_read - cache_write)
        )
        payload.update(
            {
                "uncached_input_tokens": uncached,
                "cache_read_tokens": cache_read,
                "cache_write_tokens": cache_write,
                "reasoning_tokens": _token_int(merged.get("reasoning_tokens")),
                "model_calls": 1,
            }
        )
    if saved:
        payload["decision_saved"] = saved
    return payload


async def compute_context_breakdown(
    registry: Any,
    *,
    agent_id: str,
    thread_id: str,
    max_tokens: int,
    input_tokens: int | None = None,
    mcp_servers: list[str] | None = None,
    skills: list[str] | None = None,
    usage_repo: Any | None = None,
    message_repo: Any | None = None,
) -> ContextBreakdownResult:
    """Return a non-blocking context snapshot or a token-ledger fallback.

    ``mcp_servers`` / ``skills`` are accepted for dashboard query compatibility
    but unused — the live harness snapshot already reflects the filtered request.
    This endpoint deliberately never falls back to checkpoint history: opening
    the context popover must not decode a multi-gigabyte legacy checkpoint.
    """
    del mcp_servers, skills
    row = registry.get_row(agent_id)
    if row is None:
        raise ValueError(f"agent {agent_id!r} not found")

    principal = getattr(registry, "principal_agent_id", None)
    executor_id = await asyncio.to_thread(principal, agent_id) if callable(principal) else agent_id
    if not isinstance(executor_id, str) or not executor_id:
        executor_id = agent_id

    harness: Any = None
    try:
        harness = registry.get_agent(executor_id)
    except Exception:
        logger.debug("no live harness for context usage agent=%s", agent_id, exc_info=True)

    usage: Any = None
    middleware = getattr(harness, "_context_usage_mw", None) if harness is not None else None
    snapshot_getter = getattr(middleware, "get_snapshot", None)
    if callable(snapshot_getter):
        try:
            usage = snapshot_getter(thread_id)
        except Exception:
            logger.debug(
                "live context snapshot failed for thread=%s",
                thread_id,
                exc_info=True,
            )
            usage = None

    if _usage_has_segments(usage):
        return _usage_to_breakdown(usage, fallback_max_tokens=max_tokens)

    if message_repo is not None:
        try:
            persisted = await asyncio.to_thread(
                _persisted_context,
                message_repo,
                thread_id,
                executor_id,
                executor_id != agent_id,
                max_tokens,
            )
            if persisted is not None:
                return persisted
        except Exception:
            logger.debug(
                "persisted context metadata unavailable thread=%s", thread_id, exc_info=True
            )

    logged = 0
    if usage_repo is not None:
        last_fn = getattr(usage_repo, "last_thread_input_tokens", None)
        if callable(last_fn):
            try:
                logged = _token_int(
                    await asyncio.to_thread(last_fn, agent_id=executor_id, thread_id=thread_id)
                )
            except Exception:
                logger.debug(
                    "usage_log fallback failed for thread=%s",
                    thread_id,
                    exc_info=True,
                )
    # A team stream may carry a member's usage hint. It is not the primary
    # expert's context; never mix their budgets or token counters.
    fallback = logged or (_token_int(input_tokens) if executor_id == agent_id else 0)
    if fallback:
        return _from_stream_input_tokens(fallback, max_tokens=max_tokens)

    return _empty_breakdown(max_tokens=max_tokens)
