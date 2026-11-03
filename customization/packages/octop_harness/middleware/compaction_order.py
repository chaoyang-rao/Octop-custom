"""Place route changes outside compaction so every target is checked afresh."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from octop_harness.middleware.context_budget import ContextBudgetGuardMiddleware
from octop_harness.middleware.context_usage import ContextUsageMiddleware
from octop_harness.middleware.model_router import ModelRouterMiddleware
from octop_harness.middleware.model_settings import ModelSettingsMiddleware


def context_middleware_order(middleware: Sequence[Any]) -> list[Any]:
    """Preserve core order while routing and host context precede compaction."""
    routers = [mw for mw in middleware if isinstance(mw, ModelRouterMiddleware)]
    retries = [mw for mw in middleware if getattr(mw, "wraps_context_compaction", False) is True]
    settings = [mw for mw in middleware if isinstance(mw, ModelSettingsMiddleware)]
    context = [mw for mw in middleware if getattr(mw, "before_context_compaction", False) is True]
    front = [*routers, *retries, *settings, *context]
    moved = {id(mw) for mw in front}
    rest = [mw for mw in middleware if id(mw) not in moved]
    index = next((i for i, mw in enumerate(rest) if getattr(mw, "_lc_helper", None) is not None), None)
    if index is None:
        return list(middleware)
    ordered = [*rest[:index], *front, *rest[index:]]
    guards = [mw for mw in ordered if getattr(mw, "final_context_budget_guard", False) is True]
    if not guards:
        guards = [ContextBudgetGuardMiddleware()]
    usage = [mw for mw in ordered if isinstance(mw, ContextUsageMiddleware)]
    tail_ids = {id(mw) for mw in [*guards, *usage]}
    return [*[mw for mw in ordered if id(mw) not in tail_ids], *guards, *usage]
