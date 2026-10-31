"""Bounded advertised CLI choices, never authentication/profile contents."""

from __future__ import annotations

import time
from typing import Any


def capabilities_snapshot(
    agent: Any, setup: Any, *, options: Any = None, mode_id: str = ""
) -> dict[str, Any]:
    prompt = getattr(agent, "prompt_capabilities", None)
    raw_options = options if options is not None else getattr(setup, "config_options", None) or []
    output = []
    models = []
    current_model = ""

    def choices(items: list[Any]) -> list[dict[str, str]]:
        result = []
        for item in items[:300]:
            nested = getattr(item, "options", None)
            if isinstance(nested, list):
                result.extend(choices(nested))
            else:
                value = getattr(item, "value", None)
                if isinstance(value, str):
                    result.append(
                        {"value": value[:200], "name": str(getattr(item, "name", value))[:200]}
                    )
        return result[:300]

    for option in raw_options[:50]:
        identifier = str(getattr(option, "id", ""))[:100]
        values = choices(getattr(option, "options", []) or [])
        value = getattr(option, "current_value", None)
        current = value if isinstance(value, bool) else str(value or "")[:200]
        row = {
            "id": identifier,
            "name": str(getattr(option, "name", identifier))[:200],
            "category": str(getattr(option, "category", "") or ""),
            "type": str(getattr(option, "type", "") or ""),
            "current_value": current,
            "options": values,
        }
        output.append(row)
        if row["category"] == "model" or identifier == "model":
            models = values
            current_model = str(current) if isinstance(current, str) else ""
    modes_obj = getattr(setup, "modes", None)
    modes = [
        {"value": str(item.id)[:100], "name": str(item.name)[:200]}
        for item in (getattr(modes_obj, "available_modes", None) or [])[:50]
    ]
    return {
        "image": bool(getattr(prompt, "image", False)),
        "audio": bool(getattr(prompt, "audio", False)),
        "embedded_context": bool(getattr(prompt, "embedded_context", False)),
        "models": models,
        "modes": modes,
        "config_options": output,
        "current_model": current_model,
        "current_mode": mode_id or str(getattr(modes_obj, "current_mode_id", "") or ""),
        "read_at": int(time.time()),
    }
