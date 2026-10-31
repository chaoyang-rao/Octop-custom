"""Native references are intercepted before any HTTP provider construction."""

from __future__ import annotations

from typing import Any

from octop_harness.llm.factory import ChatModelFactory

from octop.infra.agents.native_cli.config import (
    NativeCLIError,
    NativeProviderConfig,
    native_provider,
)
from octop.infra.agents.native_cli.model import NativeACPChatModel
from octop.infra.agents.native_cli.runtime import NativeRuntime


class NativeRoutingFactory(ChatModelFactory):
    def __init__(self, providers: list[Any], *, runtime: NativeRuntime, agent_owner: Any) -> None:
        super().__init__(providers)
        self.native_runtime = runtime
        self.agent_owner = agent_owner

    def get_chat_model(self, model_ref: str, *, max_retries: int | None = None) -> Any:
        if model_ref.startswith("native_cli_"):
            provider, _, model = model_ref.partition("/")
            agent_id = provider.removeprefix("native_cli_")
            owner = self.agent_owner(agent_id)
            if not agent_id or model != "session" or not isinstance(owner, int) or owner <= 0:
                raise NativeCLIError("not_configured")
            cached = self._cache.get(model_ref)
            if cached is None:
                cached = NativeACPChatModel(
                    runtime=self.native_runtime, agent_id=agent_id, owner_id=owner
                )
                self._cache[model_ref] = cached
            return cached
        return super().get_chat_model(model_ref, max_retries=max_retries)

    def _build(self, provider: Any, model: Any, *, max_retries: int | None = None) -> Any:
        if isinstance(provider, NativeProviderConfig) or str(provider.id).startswith("native_cli_"):
            raise NativeCLIError("not_configured")
        return super()._build(provider, model, max_retries=max_retries)

    def ensure_native_provider(self, agent_id: str) -> None:
        provider = native_provider(agent_id)
        self._providers[provider.id] = provider

    def close(self) -> None:
        self.native_runtime.close()
        super().close()

    async def aclose(self) -> None:
        await self.native_runtime.aclose()
        await super().aclose()
