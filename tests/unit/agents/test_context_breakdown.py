"""Tests for Octop context-usage adapter over octop-harness."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from octop.infra.agents.threads.context_breakdown import (
    SEGMENT_KEYS,
    compute_context_breakdown,
)


def test_segment_keys_stable() -> None:
    assert "conversation" in SEGMENT_KEYS
    assert "system_prompt" in SEGMENT_KEYS
    assert "skills" in SEGMENT_KEYS


@pytest.mark.asyncio
async def test_team_reads_actual_primary_snapshot_for_the_same_room() -> None:
    usage = SimpleNamespace(
        used_tokens=220000,
        max_tokens=1000000,
        segments={"conversation": 220000},
        budget_version=2,
    )
    lookups = []

    def get_agent(agent_id):
        lookups.append(agent_id)
        return SimpleNamespace(
            _context_usage_mw=SimpleNamespace(
                get_snapshot=lambda _: usage if agent_id == "primary" else None
            )
        )

    registry = SimpleNamespace(
        get_row=lambda _: SimpleNamespace(),
        get_agent=get_agent,
        principal_agent_id=lambda _: "primary",
    )
    result = await compute_context_breakdown(
        registry, agent_id="team", thread_id="room", max_tokens=128000, input_tokens=220000
    )
    assert result.max_tokens == 1000000
    assert result.used_tokens == 220000
    assert lookups == ["primary"]


@pytest.mark.asyncio
async def test_unknown_capacity_keeps_uncapped_input_tokens_without_a_fake_default() -> None:
    registry = _registry(None)
    result = await compute_context_breakdown(
        registry, agent_id="expert", thread_id="room", max_tokens=0, input_tokens=220000
    )
    assert result.max_tokens == 0
    assert result.used_tokens == 220000


@pytest.mark.asyncio
async def test_cold_team_context_uses_primary_stamp_not_newer_member_usage() -> None:
    def row(speaker, capacity, used):
        return SimpleNamespace(
            message_json=json.dumps(
                {
                    "type": "ai",
                    "data": {
                        "additional_kwargs": {
                            "speaker_agent_id": speaker,
                            "context_usage": {
                                "budget_version": 2,
                                "max_tokens": capacity,
                                "agent_id": speaker,
                                "thread_id": "room",
                                "used_tokens": used,
                                "input_tokens": used,
                                "segments": {"conversation": used},
                                "estimated": False,
                            },
                        }
                    },
                }
            )
        )

    registry = _registry(None)
    registry.principal_agent_id.return_value = "primary"
    messages = SimpleNamespace(
        recent_context_candidates=lambda _: [
            row("member", 32000, 3000),
            row("primary", 1000000, 220000),
        ]
    )
    result = await compute_context_breakdown(
        registry,
        agent_id="team",
        thread_id="room",
        max_tokens=128000,
        input_tokens=3000,
        message_repo=messages,
    )
    assert result.max_tokens == 1000000 and result.used_tokens == 220000
    assert result.estimated is False
    registry.get_agent.return_value.aget_history.assert_not_called()


@pytest.mark.asyncio
async def test_team_without_primary_usage_does_not_adopt_member_hint() -> None:
    registry = _registry(None)
    registry.principal_agent_id.return_value = "primary"
    result = await compute_context_breakdown(
        registry, agent_id="team", thread_id="room", max_tokens=1000000, input_tokens=3000
    )
    assert result.used_tokens == 0


@pytest.mark.asyncio
async def test_legacy_stamp_restores_uncapped_input_but_uses_verified_route_capacity() -> None:
    wire = {
        "type": "ai",
        "data": {
            "additional_kwargs": {
                "context_usage": {
                    "max_tokens": 128000,
                    "used_tokens": 128000,
                    "input_tokens": 220000,
                    "segments": {"conversation": 220000},
                }
            }
        },
    }
    messages = SimpleNamespace(
        recent_context_candidates=lambda _: [SimpleNamespace(message_json=json.dumps(wire))]
    )
    result = await compute_context_breakdown(
        _registry(None),
        agent_id="expert",
        thread_id="room",
        max_tokens=1000000,
        message_repo=messages,
    )
    assert result.max_tokens == 1000000 and result.used_tokens == 220000
    assert result.estimated is True


def test_segment_keys_match_harness_when_available() -> None:
    pytest.importorskip("octop_harness.context_usage")
    from octop_harness.context_usage import SEGMENT_KEYS as HARNESS_KEYS

    assert SEGMENT_KEYS == HARNESS_KEYS


def _usage(
    *,
    used: int,
    segments: dict[str, int],
    source: str = "model_request",
    max_tokens: int = 128_000,
) -> SimpleNamespace:
    obj = SimpleNamespace(
        max_tokens=max_tokens,
        used_tokens=used,
        input_tokens=used,
        output_tokens=0,
        segments=segments,
        source=source,
        budget_version=2,
        estimated=False,
    )

    def with_max_tokens(cap: int) -> SimpleNamespace:
        return SimpleNamespace(
            max_tokens=cap,
            used_tokens=obj.used_tokens,
            input_tokens=obj.input_tokens,
            output_tokens=obj.output_tokens,
            segments=dict(obj.segments),
            source=obj.source,
            with_max_tokens=with_max_tokens,
        )

    obj.with_max_tokens = with_max_tokens  # type: ignore[attr-defined]
    return obj


def _registry(usage: object | None, *, history: list[object] | None = None) -> MagicMock:
    registry = MagicMock()
    registry.get_row.return_value = MagicMock()
    harness = MagicMock()
    harness._context_usage_mw = (
        None if usage is None else SimpleNamespace(get_snapshot=MagicMock(return_value=usage))
    )
    harness.aget_context_usage = AsyncMock(side_effect=AssertionError("must not read checkpoint"))
    harness.aget_history = AsyncMock(return_value=list(history or []))
    registry.get_agent.return_value = harness
    return registry


@pytest.mark.asyncio
async def test_prefers_harness_snapshot() -> None:
    usage = _usage(
        used=9_000,
        max_tokens=1_000_000,
        segments={
            "system_prompt": 1_000,
            "skills": 2_000,
            "tool_definitions": 1_500,
            "conversation": 4_500,
        },
    )
    result = await compute_context_breakdown(
        _registry(usage),
        agent_id="agt",
        thread_id="t1",
        max_tokens=100_000,
        input_tokens=9999,
    )
    assert result.max_tokens == 1_000_000
    assert result.used_tokens == 9_000
    assert result.segments["skills"] == 2_000
    assert result.segments["conversation"] == 4_500


@pytest.mark.asyncio
async def test_fallback_to_stream_input_tokens_when_empty() -> None:
    empty = _usage(used=0, segments={}, source="empty")
    result = await compute_context_breakdown(
        _registry(empty),
        agent_id="agt",
        thread_id="t1",
        max_tokens=128_000,
        input_tokens=9_000,
    )
    assert result.used_tokens == 9_000
    assert result.segments["conversation"] == 9_000
    assert result.segments["skills"] == 0
    assert result.segments["system_prompt"] == 0


@pytest.mark.asyncio
async def test_fallback_when_harness_lacks_getter() -> None:
    result = await compute_context_breakdown(
        _registry(None),
        agent_id="agt",
        thread_id="t1",
        max_tokens=128_000,
        input_tokens=4_200,
    )
    assert result.used_tokens == 4_200
    assert result.segments["conversation"] == 4_200


@pytest.mark.asyncio
async def test_missing_agent() -> None:
    registry = MagicMock()
    registry.get_row.return_value = None
    with pytest.raises(ValueError, match="not found"):
        await compute_context_breakdown(
            registry,
            agent_id="missing",
            thread_id="t",
            max_tokens=128_000,
        )


@pytest.mark.asyncio
async def test_empty_without_stream_tokens() -> None:
    empty = _usage(used=0, segments={}, source="empty")
    result = await compute_context_breakdown(
        _registry(empty),
        agent_id="agt",
        thread_id="t1",
        max_tokens=64_000,
    )
    assert result.used_tokens == 0
    assert all(v == 0 for v in result.segments.values())


@pytest.mark.asyncio
async def test_does_not_recover_response_metadata_from_checkpoint() -> None:
    empty = _usage(used=0, segments={}, source="empty")
    history = [
        {
            "role": "assistant",
            "content": "ok",
            "response_metadata": {"token_usage": {"prompt_tokens": 8800, "completion_tokens": 40}},
        },
    ]
    result = await compute_context_breakdown(
        _registry(empty, history=history),
        agent_id="agt",
        thread_id="t1",
        max_tokens=128_000,
    )
    assert result.used_tokens == 0


@pytest.mark.asyncio
async def test_does_not_read_checkpoint_context_stamp() -> None:
    empty = _usage(used=0, segments={}, source="empty")
    history = [
        {
            "role": "assistant",
            "content": "ok",
            "additional_kwargs": {
                "context_usage": {
                    "max_tokens": 128_000,
                    "used_tokens": 15_400,
                    "input_tokens": 15_400,
                    "output_tokens": 80,
                    "segments": {
                        "system_prompt": 2_000,
                        "conversation": 13_400,
                    },
                }
            },
        },
    ]
    result = await compute_context_breakdown(
        _registry(empty, history=history),
        agent_id="agt",
        thread_id="t1",
        max_tokens=1_000_000,
    )
    assert result.max_tokens == 1_000_000
    assert result.used_tokens == 0


@pytest.mark.asyncio
async def test_empty_snapshot_uses_usage_ledger_without_checkpoint() -> None:
    empty = _usage(used=0, segments={}, source="empty")
    history = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "ok",
            "usage_metadata": {"input_tokens": 4200, "output_tokens": 12},
        },
    ]
    registry = _registry(empty, history=history)
    usage_repo = MagicMock()
    usage_repo.last_thread_input_tokens.return_value = 4200
    result = await compute_context_breakdown(
        registry,
        agent_id="agt",
        thread_id="t1",
        max_tokens=128_000,
        usage_repo=usage_repo,
    )
    assert result.used_tokens == 4200
    assert result.segments["conversation"] == 4200
    registry.get_agent.return_value.aget_history.assert_not_awaited()


@pytest.mark.asyncio
async def test_live_harness_missing_falls_back_to_query_hint() -> None:
    registry = MagicMock()
    registry.get_row.return_value = MagicMock()
    registry.get_agent.side_effect = RuntimeError("agent not running")
    result = await compute_context_breakdown(
        registry,
        agent_id="agt",
        thread_id="t1",
        max_tokens=128_000,
        input_tokens=9_000,
    )
    assert result.used_tokens == 9_000
    assert result.segments["conversation"] == 9_000
