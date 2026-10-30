"""Geometric expert portrait metadata; original files remain privately stored.

Public expert portraits always use geometry. Account portraits are independent.
"""
from __future__ import annotations

import hashlib
from typing import Any, Literal

AvatarShape = Literal["blob", "pebble", "squircle", "droplet", "cloud", "star", "triangle"]
AvatarColor = Literal["ink", "jade", "blue", "violet", "rose", "amber", "coral"]
AVATAR_SHAPES = ("blob", "pebble", "squircle", "droplet", "cloud", "star", "triangle")
AVATAR_COLORS = {
    "ink": "#252830", "jade": "#19B7A2", "blue": "#486BCD", "violet": "#825DC5",
    "rose": "#DB779A", "amber": "#DCAA46", "coral": "#E5805D",
}
_UNSET = object()


def validate_avatar(value: Any) -> dict[str, Any]:
    if value is None:
        return {"shape": None, "color": None}
    if not isinstance(value, dict):
        raise ValueError("avatar must be an object")
    shape, color = value.get("shape"), value.get("color")
    if shape is not None and shape not in AVATAR_SHAPES:
        raise ValueError("invalid avatar shape")
    if color is not None and (not isinstance(color, str) or color not in AVATAR_COLORS):
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
    config: dict[str, Any], *, previous: dict[str, Any] | None = None,
    shape: Any = _UNSET, color: Any = _UNSET,
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


def avatar_response(config: dict[str, Any], uploaded_icon_url: str | None, *, identity: str = "") -> dict[str, Any]:
    """Project the geometric URL for all old icon consumers without changing storage."""
    fields = public_avatar_fields(config)
    shape, color = fields["avatar_shape"], fields["avatar_color"] or "ink"
    if not shape:
        digest = hashlib.sha256(str(identity or (uploaded_icon_url or "expert").split("?", 1)[0].split("#", 1)[0]).encode()).digest()
        shape = AVATAR_SHAPES[digest[0] % len(AVATAR_SHAPES)]
        color = fields["avatar_color"] if fields["avatar_color"] in AVATAR_COLORS else tuple(AVATAR_COLORS)[digest[1] % len(AVATAR_COLORS)]
        fields = {"avatar_shape": shape, "avatar_color": color}
    icon_url = f"/expert-avatars/v2/{shape}-{color}.svg"
    return {**fields, "icon_url": icon_url, "uploaded_icon_url": uploaded_icon_url}


def is_generated_avatar_icon_url(value: Any) -> bool:
    """Recognize only reserved local projections, including cache queries."""
    if not isinstance(value, str):
        return False
    path = value.strip().split("?", 1)[0].split("#", 1)[0]
    prefix = next((candidate for candidate in ("/expert-avatars/v1/", "/expert-avatars/v2/")
                   if path.startswith(candidate)), None)
    if prefix is None or not path.endswith(".svg"):
        return False
    parts = path[len(prefix):-4].rsplit("-", 1)
    return len(parts) == 2 and parts[0] in AVATAR_SHAPES and parts[1] in AVATAR_COLORS


def valid_avatar_or_none(value: Any) -> dict[str, Any] | None:
    """Ignore malformed historical/template metadata when reading a catalog."""
    if value is None:
        return None
    try:
        return validate_avatar(value)
    except ValueError:
        return None
