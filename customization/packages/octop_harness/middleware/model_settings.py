"""Apply LLM generation settings from ``RunnableConfig.configurable``.

Hosts (e.g. Octop) map agent config onto these configurable keys before
``stream`` / ``invoke``. This middleware merges them into each model call.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from copy import copy
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse

from octop_harness.middleware.runtime import runtime_config

CONFIGURABLE_MODEL_SETTINGS = "model_settings"
CONFIGURABLE_MAX_INPUT_TOKENS = "max_input_tokens"


def apply_configurable_model_settings(request: ModelRequest) -> ModelRequest:
    """Merge host overrides into ``request.model_settings`` and context cap."""
    cfg = runtime_config(request)
    configurable = cfg.get("configurable") if isinstance(cfg, dict) else None
    if not isinstance(configurable, dict):
        return request

    updated = request
    overrides = configurable.get(CONFIGURABLE_MODEL_SETTINGS)
    if isinstance(overrides, dict) and overrides:
        merged = dict(getattr(request, "model_settings", None) or {})
        merged.update(overrides)
        updated = updated.override(model_settings=merged)

    max_input = configurable.get(CONFIGURABLE_MAX_INPUT_TOKENS)
    model = getattr(updated, "model", None)
    if model is not None:
        raw = getattr(model, "profile", None)
        profile = dict(raw) if isinstance(raw, dict) else {}
        base_input = getattr(model, "_harness_max_input_tokens", 0)
        context_window = getattr(model, "_harness_context_window", 0)
        if not isinstance(base_input, int) or base_input <= 0:
            base_input = profile.get("max_input_tokens", 0)
        if not isinstance(context_window, int) or context_window <= 0:
            context_window = profile.get("context_window", 0) or base_input
        base_input = base_input if isinstance(base_input, int) and base_input > 0 else 0
        context_window = context_window if isinstance(context_window, int) and context_window > 0 else 0
        limit = base_input
        if isinstance(max_input, int) and not isinstance(max_input, bool) and max_input > 0:
            limit = min(limit, max_input) if limit > 0 else max_input
        output = 0
        for key in ("max_tokens", "max_completion_tokens", "max_output_tokens"):
            value = (getattr(updated, "model_settings", None) or {}).get(key, getattr(model, key, None))
            if isinstance(value, int) and not isinstance(value, bool):
                output = max(output, value)
        if context_window > 0 and output > 0:
            available = max(context_window - output, 1)
            limit = min(limit, available) if limit > 0 else available
        if limit > 0:
            profile["max_input_tokens"] = limit
        else:
            profile.pop("max_input_tokens", None)
        # SDK clients may be shared; mutable prompt budgets must not be shared.
        clone = copy(model)
        object.__setattr__(clone, "profile", profile)
        object.__setattr__(clone, "_harness_max_input_tokens", base_input)
        object.__setattr__(clone, "_harness_context_window", context_window)
        object.__setattr__(clone, "_harness_request_budget", True)
        updated = updated.override(model=clone)
    return updated


class ModelSettingsMiddleware(AgentMiddleware[Any, Any]):
    """Inject ``temperature`` / ``top_p`` / ``max_tokens`` from configurable."""

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        return handler(apply_configurable_model_settings(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        return await handler(apply_configurable_model_settings(request))


__all__ = [
    "CONFIGURABLE_MAX_INPUT_TOKENS",
    "CONFIGURABLE_MODEL_SETTINGS",
    "ModelSettingsMiddleware",
    "apply_configurable_model_settings",
]
