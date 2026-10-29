"""Public avatar fields shared by agent create/update and template installers."""
from __future__ import annotations
from typing import Any
from pydantic import model_validator
from octop.api.common.agent_runtime import AgentRuntimeFields
from octop.infra.agents.settings.geometric_avatar import (
    AvatarColor, AvatarShape, merge_avatar_config, validate_avatar,
)


class AgentAvatarFields(AgentRuntimeFields):
    avatar_shape: AvatarShape | None = None
    avatar_color: AvatarColor | None = None

    @model_validator(mode="after")
    def validate_nested_avatar(self) -> "AgentAvatarFields":
        config = getattr(self, "config", None)
        if isinstance(config, dict) and "avatar" in config:
            validate_avatar(config["avatar"])
        return self


def avatar_config_from_body(
    body: AgentAvatarFields, config: dict[str, Any], *, previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    updates = {}
    if "avatar_shape" in body.model_fields_set:
        updates["shape"] = body.avatar_shape
    if "avatar_color" in body.model_fields_set:
        updates["color"] = body.avatar_color
    return merge_avatar_config(config, previous=previous, **updates)


def avatar_option_from_body(body: AgentAvatarFields) -> dict[str, Any] | None:
    # Installers must distinguish omitted fields from explicit null so a
    # color-only override keeps the template's shape (and vice versa).
    option = {}
    if "avatar_shape" in body.model_fields_set:
        option["shape"] = body.avatar_shape
    if "avatar_color" in body.model_fields_set:
        option["color"] = body.avatar_color
    return option if option else None
