"""Declarative per-expert native execution, separate from ACP delegation tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from octop_harness.config import ModelConfig, ProviderConfig

from octop.i18n import tr


class NativeCLIError(Exception):
    def __init__(self, code: str, locale: str = "en") -> None:
        self.code = code
        super().__init__(tr(f"nativeCli.errors.{code}", locale))


@dataclass(frozen=True)
class NativeSpec:
    enabled: bool = False
    runner: str = ""
    model_id: str = ""
    mode_id: str = ""

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> NativeSpec:
        raw = config.get("native_cli")
        if not isinstance(raw, dict):
            return cls()
        enabled = raw.get("enabled", False)
        if not isinstance(enabled, bool):
            raise NativeCLIError("invalid_input")
        runner = str(raw.get("runner") or "").strip()
        model = str(raw.get("model_id") or "").strip()
        mode = str(raw.get("mode_id") or "").strip()
        if (enabled and not runner) or len(runner) > 100 or len(model) > 200 or len(mode) > 100:
            raise NativeCLIError("invalid_input")
        return cls(enabled, runner, model, mode)

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "runner": self.runner,
            "model_id": self.model_id,
            "mode_id": self.mode_id,
        }


def native_ref(agent_id: str) -> str:
    return f"native_cli_{agent_id}/session"


@dataclass
class NativeProviderConfig(ProviderConfig):
    """Internal provider descriptor; deliberately has no HTTP URL or API key."""

    def __post_init__(self) -> None:
        if (
            not self.id.startswith("native_cli_")
            or self.api_key
            or self.base_url != "native-cli://local"
        ):
            raise NativeCLIError("invalid_input")
        if len(self.models) != 1 or self.models[0].id != "session":
            raise NativeCLIError("invalid_input")


def native_provider(agent_id: str) -> ProviderConfig:
    return NativeProviderConfig(
        id=f"native_cli_{agent_id}",
        name="Native CLI",
        base_url="native-cli://local",
        api_key="",
        models=[ModelConfig(id="session", name="Native CLI", enabled=True)],
    )
