"""Resolve one expert invocation's own thread and model reasoning preferences."""

from __future__ import annotations

from typing import Any

from octop.infra.agents.providers.reasoning import reasoning_request_parameters
from octop.infra.users.preferences import get_model_reasoning_from_json


def resolve_reasoning_overrides(
    capability: dict[str, Any] | None,
    *,
    model_ref: str,
    preferences_json: str | None,
    thread: Any = None,
    mode: Any = None,
    effort: Any = None,
) -> dict[str, Any]:
    preference = get_model_reasoning_from_json(preferences_json).get(model_ref)
    selected_mode = (
        mode
        if mode in ("auto", "enabled", "disabled")
        else getattr(thread, "reasoning_mode", None)
        or (preference.mode if preference is not None else None)
    )
    selected_effort = (
        effort.strip().lower()
        if isinstance(effort, str) and effort.strip()
        else getattr(thread, "reasoning_effort", None)
        or (preference.effort if preference is not None else None)
    )
    return reasoning_request_parameters(capability, mode=selected_mode, effort=selected_effort)
