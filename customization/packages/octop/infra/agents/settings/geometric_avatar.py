"""Geometric expert portrait metadata; original files remain privately stored.

Public expert portraits always use geometry. Account portraits are independent.
"""

from __future__ import annotations

import hashlib
from typing import Any, Literal

AvatarShape = Literal[
    "blob", "pebble", "squircle", "droplet", "cloud", "star", "triangle", "diamond", "capsule"
]
AvatarColor = Literal[
    "black",
    "brown",
    "red",
    "orange",
    "yellow",
    "lemon",
    "green",
    "cyan",
    "blue",
    "violet",
    "magenta",
    "gray",
    "ink",
    "cocoa",
    "coral",
    "amber",
    "jade",
    "rose",
]
AVATAR_SHAPES = (
    "blob",
    "pebble",
    "squircle",
    "droplet",
    "cloud",
    "star",
    "triangle",
    "diamond",
    "capsule",
)
AVATAR_COLORS = {
    "black": "#000000",
    "brown": "#936439",
    "red": "#FF263C",
    "orange": "#FF6700",
    "yellow": "#FF9800",
    "lemon": "#FFD400",
    "green": "#00C972",
    "cyan": "#00BCA6",
    "blue": "#1084FE",
    "violet": "#9159FE",
    "magenta": "#FF309B",
    "gray": "#777777",
}
LEGACY_AVATAR_COLORS = {
    "ink": "black",
    "cocoa": "brown",
    "coral": "orange",
    "amber": "yellow",
    "jade": "cyan",
    "rose": "magenta",
}
# Existing experts without a saved color keep the same hue across the palette upgrade.
_LEGACY_FALLBACK_HUES = (
    "black",
    "cyan",
    "blue",
    "violet",
    "magenta",
    "yellow",
    "orange",
    "brown",
    "red",
)
_UNSET = object()


def valid_avatar_color(value: Any) -> bool:
    return isinstance(value, str) and (value in AVATAR_COLORS or value in LEGACY_AVATAR_COLORS)


def validate_avatar(value: Any) -> dict[str, Any]:
    if value is None:
        return {"shape": None, "color": None}
    if not isinstance(value, dict):
        raise ValueError("avatar must be an object")
    shape, color = value.get("shape"), value.get("color")
    if shape is not None and shape not in AVATAR_SHAPES:
        raise ValueError("invalid avatar shape")
    if color is not None and (not valid_avatar_color(color)):
        raise ValueError("invalid avatar color")
    return {**value, "shape": shape, "color": color}


def public_avatar_fields(config: dict[str, Any]) -> dict[str, str | None]:
    try:
        avatar = validate_avatar(config.get("avatar"))
    except ValueError:
        avatar = {"shape": None, "color": None}
    return {"avatar_shape": avatar["shape"], "avatar_color": avatar["color"]}


def merge_avatar_option(inherited: Any, overrides: Any) -> dict[str, Any]:
    """Overlay only supplied template fields; null explicitly clears a field."""
    if overrides is None:
        return validate_avatar(None)
    if not isinstance(overrides, dict):
        raise ValueError("avatar must be an object")
    return validate_avatar({**validate_avatar(inherited), **overrides})


def merge_avatar_config(
    config: dict[str, Any],
    *,
    previous: dict[str, Any] | None = None,
    shape: Any = _UNSET,
    color: Any = _UNSET,
) -> dict[str, Any]:
    """Merge only avatar metadata, preserving unrelated configuration verbatim."""
    out = dict(config)
    prior = previous or {}
    if "avatar" not in out and "avatar" in prior:
        out["avatar"] = prior["avatar"]
    if "avatar" not in out and shape is _UNSET and color is _UNSET:
        return out
    try:
        avatar = validate_avatar(out.get("avatar"))
    except ValueError:
        if shape is _UNSET and color is _UNSET:
            raise
        # A new explicit selection can repair old unvalidated metadata.
        avatar = {"shape": None, "color": None}
    if shape is not _UNSET:
        avatar["shape"] = shape
    if color is not _UNSET:
        avatar["color"] = color
    out["avatar"] = validate_avatar(avatar)
    return out


def avatar_response(
    config: dict[str, Any], uploaded_icon_url: str | None, *, identity: str = ""
) -> dict[str, Any]:
    """Project the geometric URL for all old icon consumers without changing storage."""
    fields = public_avatar_fields(config)
    shape, stored_color = fields["avatar_shape"], fields["avatar_color"]
    color = stored_color or "black"
    if not shape:
        digest = hashlib.sha256(
            str(
                identity or (uploaded_icon_url or "expert").split("?", 1)[0].split("#", 1)[0]
            ).encode()
        ).digest()
        shape = AVATAR_SHAPES[digest[0] % len(AVATAR_SHAPES)]
        color = stored_color or _LEGACY_FALLBACK_HUES[digest[1] % len(_LEGACY_FALLBACK_HUES)]
        fields = {"avatar_shape": shape, "avatar_color": color}
    palette_color = LEGACY_AVATAR_COLORS.get(color, color)
    icon_url = f"/expert-avatars/v3/{shape}-{palette_color}.svg"
    return {**fields, "icon_url": icon_url, "uploaded_icon_url": uploaded_icon_url}


def is_generated_avatar_icon_url(value: Any) -> bool:
    """Recognize only reserved local projections, including cache queries."""
    if not isinstance(value, str):
        return False
    path = value.strip().split("?", 1)[0].split("#", 1)[0]
    prefix = next(
        (
            candidate
            for candidate in ("/expert-avatars/v1/", "/expert-avatars/v2/", "/expert-avatars/v3/")
            if path.startswith(candidate)
        ),
        None,
    )
    if prefix is None or not path.endswith(".svg"):
        return False
    parts = path[len(prefix) : -4].rsplit("-", 1)
    if len(parts) != 2 or parts[0] not in AVATAR_SHAPES:
        return False
    if prefix == "/expert-avatars/v3/":
        return parts[1] in AVATAR_COLORS
    return parts[1] in LEGACY_AVATAR_COLORS or parts[1] in ("red", "blue", "violet")


def valid_avatar_or_none(value: Any) -> dict[str, Any] | None:
    """Ignore malformed historical/template metadata when reading a catalog."""
    if value is None:
        return None
    try:
        return validate_avatar(value)
    except ValueError:
        return None
