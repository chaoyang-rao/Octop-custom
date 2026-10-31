"""Conversation-local model choice; never changes host runner or permission mode."""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

from octop.infra.agents.native_cli.config import NativeCLIError, NativeSpec
from octop.infra.agents.native_cli.metadata import display_metadata


def _key(user_id: int, agent_id: str, thread_id: str, runner: str) -> str:
    digest = hashlib.sha256(f"{user_id}:{agent_id}:{thread_id}:{runner}".encode()).hexdigest()
    return "native_cli.model_choice." + digest


def _selection_context(
    manager: Any, agent_id: str, user_id: int, thread_id: str | None, locale: str
) -> tuple[str, NativeSpec, dict[str, Any]]:
    row = manager.get_row(agent_id)
    principal_id = manager.principal_agent_id(agent_id)
    principal = manager.get_row(principal_id)
    user = manager._repos.user_repo.get(user_id)
    if (
        row is None
        or row.user_id != user_id
        or row.is_shared
        or principal is None
        or principal.user_id != user_id
        or principal.is_shared
        or user is None
        or user.disabled
        or user.role != "admin"
    ):
        raise NativeCLIError("actor_required", locale)
    if thread_id:
        thread = manager._repos.thread_repo.get(thread_id)
        if thread is None or thread.user_id != user_id or thread.agent_id != agent_id:
            raise NativeCLIError("thread_not_owned", locale)
    spec = NativeSpec.from_config(manager.get_config(principal_id))
    if not spec.enabled:
        raise NativeCLIError("not_configured", locale)
    raw = manager._repos.settings_repo.get(
        manager.native_cli.capability_key(user_id, principal_id, spec.runner)
    )
    cached = json.loads(raw) if raw else {}
    return principal_id, spec, cached if isinstance(cached, dict) else {}


async def model_choices(
    manager: Any,
    *,
    agent_id: str,
    user_id: int,
    thread_id: str | None = None,
    locale: str = "en",
) -> dict[str, Any]:
    def read() -> dict[str, Any]:
        _, spec, cached = _selection_context(manager, agent_id, user_id, thread_id, locale)
        selected = (
            manager._repos.settings_repo.get(_key(user_id, agent_id, thread_id, spec.runner))
            if thread_id
            else None
        )
        effective = selected if selected is not None else spec.model_id
        return {
            "runner": spec.runner,
            "effective_model_id": effective,
            "configured_model_id": spec.model_id,
            "models": cached.get("models") or [],
            "has_capabilities": bool(cached),
        }

    return await asyncio.to_thread(read)


async def prepare_model_choice(
    manager: Any,
    *,
    agent_id: str,
    user_id: int,
    thread_id: str,
    selected: str | None,
    locale: str = "en",
) -> tuple[str, dict[str, Any]]:
    """Validate/save the next turn's choice and return an immutable turn snapshot."""

    def prepare() -> tuple[str, dict[str, Any]]:
        _, spec, cached = _selection_context(manager, agent_id, user_id, thread_id, locale)
        key = _key(user_id, agent_id, thread_id, spec.runner)
        if selected is not None:
            if len(selected) > 200 or (
                selected and selected not in {c["value"] for c in cached.get("models", [])}
            ):
                raise NativeCLIError("model_unavailable", locale)
            manager._repos.settings_repo.set(key, selected)
        stored = manager._repos.settings_repo.get(key)
        effective = stored if stored is not None else spec.model_id
        if stored and stored not in {c["value"] for c in cached.get("models", [])}:
            raise NativeCLIError("model_unavailable", locale)
        return effective, display_metadata(spec.runner, effective, locale=locale)

    return await asyncio.to_thread(prepare)
