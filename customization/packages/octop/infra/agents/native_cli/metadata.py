"""Human model labels and explicit CLI-statistics provenance."""

from __future__ import annotations

import json
from typing import Any

from octop.i18n import tr
from octop.infra.agents.native_cli.config import NativeSpec

_NAMES = {
    "codex": "Codex",
    "managed_codex": "Codex ACP",
    "managed_opencode": "OpenCode",
    "managed_pi": "Pi",
    "managed_claude": "Claude Code",
    "managed_cline": "Cline",
    "managed_grok": "Grok CLI",
    "managed_gemini": "Gemini CLI",
    "managed_cursor": "Cursor CLI",
    "claude_code": "Claude Code",
    "opencode": "OpenCode",
    "pi": "Pi",
    "cline": "Cline",
    "grok": "Grok CLI",
    "gemini_cli": "Gemini CLI",
    "cursor_cli": "Cursor CLI",
    "kimi_code": "Kimi Code",
    "codebuddy": "CodeBuddy",
}


def display_metadata(
    runner: str,
    model_id: str,
    *,
    reported_model: str = "",
    locale: str = "en",
    usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    chosen = reported_model or model_id
    label = f"{_NAMES.get(runner, runner)} · {chosen or tr('nativeCli.cliDefaultModel', locale)}"
    stats = usage or {}
    used = stats.get("used")
    size = stats.get("size")
    known = (
        isinstance(used, int)
        and not isinstance(used, bool)
        and isinstance(size, int)
        and not isinstance(size, bool)
        and size > 0
        and used >= 0
    )
    return {
        "execution_backend": "native_cli",
        "model_provider": "native_cli",
        "model_display_name": label,
        "cli_runner": runner,
        "cli_model_id": chosen or None,
        "model_source": "cli_reported"
        if reported_model
        else "cli_configured"
        if model_id
        else "cli_default",
        "usage_source": "cli",
        "usage_reported": False,
        "context_source": "cli",
        "context_reported": known,
        "context_used_tokens": used if known else None,
        "context_max_tokens": size if known else None,
    }


def native_metadata(manager: Any, agent_id: str) -> dict[str, Any] | None:
    ref = manager.native_execution_ref(agent_id)
    if not ref:
        return None
    target = ref.partition("/")[0].removeprefix("native_cli_")
    row = manager.get_row(target)
    if row is None or row.user_id is None:
        return None
    spec = NativeSpec.from_config(manager.get_config(target))
    user = manager._repos.user_repo.get(row.user_id)
    locale = str(user.locale or "en") if user else "en"
    key = manager.native_cli.capability_key(row.user_id, target, spec.runner)
    raw = manager._repos.settings_repo.get(key)
    caps = json.loads(raw) if raw else {}
    reported = (
        str(caps.get("current_model") or "")
        if caps.get("configured_model_id") == spec.model_id
        else ""
    )
    return display_metadata(spec.runner, spec.model_id, reported_model=reported, locale=locale)
