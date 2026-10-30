"""Creation defaults for the custom geometric expert portraits."""

from __future__ import annotations

import secrets
from typing import Any

from octop.infra.agents.settings.geometric_avatar import AVATAR_COLORS, AVATAR_SHAPES

SHAPES = AVATAR_SHAPES
COLORS = tuple(AVATAR_COLORS)


def created_avatar(config: dict[str, Any], occupied: list[dict[str, Any]]) -> dict[str, str]:
    """Keep an explicit choice; otherwise prefer an unused shape/color pair."""
    selected = config.get("avatar")
    if isinstance(selected, dict) and selected.get("shape") in SHAPES:
        return {"shape": selected["shape"], "color": selected["color"] if selected.get("color") in COLORS else secrets.choice(COLORS)}
    used = {
        (item.get("shape"), item.get("color")) for item in occupied if isinstance(item, dict)
    }
    choices = [(shape, color) for shape in SHAPES for color in COLORS]
    shape, color = secrets.choice([pair for pair in choices if pair not in used] or choices)
    return {"shape": shape, "color": color}
