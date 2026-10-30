"""Real primary-expert execution scoped to a team room, never a second persona."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PrimaryRoom:
    team_id: str
    primary_id: str
    thread_id: str
    user_id: int | None


_CURRENT: ContextVar[PrimaryRoom | None] = ContextVar("octop_primary_room", default=None)


def current_primary_room() -> PrimaryRoom | None:
    return _CURRENT.get()


@contextmanager
def primary_room_scope(room: PrimaryRoom) -> Iterator[None]:
    token = _CURRENT.set(room)
    try:
        yield
    finally:
        _CURRENT.reset(token)


def request_user_id(request: dict[str, Any]) -> int | None:
    cfg = request.get("configurable") or {}
    raw = cfg.get("user", request.get("user_id"))
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int) and raw > 0:
        return raw
    if isinstance(raw, str) and raw.isdigit() and int(raw) > 0:
        return int(raw)
    return None


def primary_request(request: dict[str, Any], room: PrimaryRoom, peers: list[str]) -> dict[str, Any]:
    req = dict(request)
    req["agent_id"] = room.primary_id
    cfg = dict(req.get("configurable") or {})
    cfg.update(
        agent_id=room.primary_id,
        octop_team_id=room.team_id,
        octop_team_thread_id=room.thread_id,
        octop_team_primary_id=room.primary_id,
        peer_invoke_mode="async",
        team_peers=[peer for peer in peers if peer != room.primary_id],
    )
    if room.user_id is not None:
        cfg["user"] = str(room.user_id)
    req["configurable"] = cfg
    return req


def stamp_message(message: Any, room: PrimaryRoom) -> Any:
    if isinstance(message, dict):
        nested = message.get("data")
        data: dict[str, Any] = nested if isinstance(nested, dict) else message
        role = str(message.get("type") or data.get("role") or data.get("type") or "")
        if role not in {"ai", "assistant", "tool"}:
            return message
        extra = dict(data.get("additional_kwargs") or {})
        if extra.get("speaker_agent_id") not in (None, "", room.team_id, room.primary_id):
            return message
        extra["speaker_agent_id"] = room.primary_id
        stamped = {**data, "additional_kwargs": extra}
        return {**message, "data": stamped} if data is not message else stamped
    if getattr(message, "type", None) not in {"ai", "assistant", "tool"}:
        return message
    extra = dict(getattr(message, "additional_kwargs", {}) or {})
    if extra.get("speaker_agent_id") not in (None, "", room.team_id, room.primary_id):
        return message
    extra["speaker_agent_id"] = room.primary_id
    return message.model_copy(update={"additional_kwargs": extra})


def stamp_primary_chunk(chunk: Any, room: PrimaryRoom) -> Any:
    if not isinstance(chunk, dict):
        return chunk
    out = dict(chunk)
    # The room owns transport lifecycle; the expert owns authored content.
    out.update(agent_id=room.team_id, turn_owner_agent_id=room.team_id, speaker_agent_id=room.primary_id)
    if isinstance(out.get("messages"), list):
        out["messages"] = [stamp_message(msg, room) for msg in out["messages"]]
    data = out.get("data")
    if out.get("type") in {"state_update", "state_snapshot"} and isinstance(data, dict):
        data = dict(data)
        if isinstance(data.get("messages"), list):
            data["messages"] = [stamp_message(msg, room) for msg in data["messages"]]
        for key, value in list(data.items()):
            if isinstance(value, dict) and isinstance(value.get("messages"), list):
                data[key] = {
                    **value,
                    "messages": [stamp_message(msg, room) for msg in value["messages"]],
                }
        out["data"] = data
    return out
