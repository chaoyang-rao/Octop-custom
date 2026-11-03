"""Last outbound-request guard, after every prompt/tool projection."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.exceptions import ContextOverflowError

from octop_harness.context_usage import breakdown_from_model_request


class ContextBudgetGuardMiddleware(AgentMiddleware[Any, Any]):
    final_context_budget_guard = True

    def _check(self, request: ModelRequest[Any]) -> None:
        profile = getattr(request.model, "profile", None)
        cap = profile.get("max_input_tokens", 0) if isinstance(profile, dict) else 0
        if isinstance(cap, int) and cap > 0:
            count = sum(breakdown_from_model_request(request).values())
            if count > int(cap * 0.95):
                raise ContextOverflowError("context_length_exceeded: final model request exceeds its input budget")

    def wrap_model_call(
        self, request: ModelRequest[Any], handler: Callable[[ModelRequest[Any]], ModelResponse[Any]]
    ) -> ModelResponse[Any]:
        self._check(request)
        return handler(request)

    async def awrap_model_call(
        self, request: ModelRequest[Any], handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]]
    ) -> ModelResponse[Any]:
        self._check(request)
        return await handler(request)
