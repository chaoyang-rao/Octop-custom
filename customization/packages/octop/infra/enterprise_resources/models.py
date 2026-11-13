"""Portable expert/skill content, deliberately excluding private runtime state."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import unicodedata
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from octop.infra.agents.settings.geometric_avatar import AVATAR_COLORS, AVATAR_SHAPES
from octop.infra.errors import ErrorCode, OctopError

MAX_BYTES = 8 * 1024 * 1024
NAMESPACE = "enterprise_resource_bundle"
ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,47}$"
PROMPT_FILES = frozenset(
    {"SOUL.md", "AGENTS.md", "IDENTITY.md", "TOOLS.md", "HEARTBEAT.md", "PROACTIVE.md"}
)
_PRIVATE = frozenset(
    {
        "auth",
        "credentials.json",
        "secrets",
        "sessions",
        "memory",
        "daily",
        "logs",
        "inbound",
        "uploads",
        "workspaces",
        "user.md",
    }
)


def invalid() -> OctopError:
    return OctopError.localized(ErrorCode.ENTERPRISE_RESOURCE_INVALID)


def conflict() -> OctopError:
    return OctopError.localized(ErrorCode.ENTERPRISE_RESOURCE_CONFLICT)


def canonical(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def safe_path(path: str) -> bool:
    parts = path.split("/")
    return bool(
        path
        and len(path) <= 240
        and not re.search(r'[\\:\x00-\x1f<>"|?*]', path)
        and all(part and part not in {".", ".."} and not part.startswith(".") for part in parts)
        and all(
            part.casefold() not in _PRIVATE
            and not part.casefold().startswith(("memory.", "credentials.", ".env"))
            for part in parts
        )
        and all(
            part == part.rstrip(" .")
            and not re.fullmatch(r"(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", part, re.I)
            for part in parts
        )
    )


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ResourceFile(StrictModel):
    path: str
    content_base64: str = Field(max_length=12 * 1024 * 1024, repr=False)

    @field_validator("path")
    @classmethod
    def valid_path(cls, value: str) -> str:
        if not safe_path(value):
            raise ValueError("unsafe resource path")
        return value

    @field_validator("content_base64")
    @classmethod
    def valid_content(cls, value: str) -> str:
        try:
            content = base64.b64decode(value, validate=True)
        except (ValueError, TypeError):
            raise ValueError("invalid resource content") from None
        if len(content) > MAX_BYTES:
            raise ValueError("resource too large")
        return base64.b64encode(content).decode()


class ResourceAvatar(StrictModel):
    shape: str
    color: str

    @model_validator(mode="after")
    def valid_avatar(self) -> ResourceAvatar:
        if self.shape not in AVATAR_SHAPES or self.color not in AVATAR_COLORS:
            raise ValueError("invalid avatar")
        return self


class ResourceDefinition(StrictModel):
    resource_id: str = Field(pattern=ID_PATTERN)
    kind: Literal["expert", "skill"]
    display_name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=2000)
    enabled: bool = True
    allowed_subjects: list[str] = Field(default_factory=list, max_length=1000)
    avatar: ResourceAvatar | None = None
    skill_refs: list[str] = Field(default_factory=list, max_length=100)
    mcp_refs: list[str] = Field(default_factory=list, max_length=100)
    files: list[ResourceFile] = Field(min_length=1, max_length=512)

    @model_validator(mode="after")
    def valid_bundle(self) -> ResourceDefinition:
        names = {unicodedata.normalize("NFC", f.path).casefold() for f in self.files}
        if (
            len(names) != len(self.files)
            or sum(len(base64.b64decode(f.content_base64)) for f in self.files) > MAX_BYTES
        ):
            raise ValueError("duplicate or oversized resource")
        if any(any(other.startswith(name + "/") for other in names) for name in names):
            raise ValueError("file/directory collision")
        if self.kind == "expert":
            if any(f.path not in PROMPT_FILES for f in self.files):
                raise ValueError("experts contain only managed prompt files")
            for f in self.files:
                base64.b64decode(f.content_base64).decode("utf-8")
        elif (
            "SKILL.md" not in {f.path for f in self.files}
            or self.skill_refs
            or self.mcp_refs
            or self.avatar
        ):
            raise ValueError("invalid skill bundle")
        if self.kind == "skill":
            next(
                base64.b64decode(f.content_base64).decode("utf-8")
                for f in self.files
                if f.path == "SKILL.md"
            )
        if any(not re.fullmatch(ID_PATTERN, name) for name in self.skill_refs):
            raise ValueError("invalid skill reference")
        if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name) for name in self.mcp_refs):
            raise ValueError("invalid MCP reference")
        if any(
            not value or len(value) > 128 or any(c.isspace() for c in value)
            for value in self.allowed_subjects
        ):
            raise ValueError("invalid subject")
        self.files.sort(key=lambda f: f.path)
        self.allowed_subjects = sorted(set(self.allowed_subjects))
        self.skill_refs = sorted(set(self.skill_refs))
        self.mcp_refs = sorted(set(self.mcp_refs))
        return self

    def content_files(self) -> dict[str, bytes]:
        return {f.path: base64.b64decode(f.content_base64) for f in self.files}

    def content_digest(self) -> str:
        # Visibility is catalogue metadata, never duplicated inside downloadable content.
        return digest(self.model_dump(mode="json", exclude={"allowed_subjects", "enabled"}))


class ResourceEntry(StrictModel):
    resource_id: str = Field(pattern=ID_PATTERN)
    kind: Literal["expert", "skill"]
    display_name: str
    description: str
    enabled: bool
    allowed_subjects: list[str] = Field(default_factory=list)
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class ResourceSnapshot(StrictModel):
    schema_version: Literal[1] = 1
    revision: int = Field(ge=0)
    published_at: int = Field(ge=0)
    checksum: str
    entries: list[ResourceEntry]


def snapshot(revision: int, published_at: int, entries: list[ResourceEntry]) -> ResourceSnapshot:
    values = {
        "schema_version": 1,
        "revision": revision,
        "published_at": published_at,
        "entries": [
            e.model_dump(mode="json") for e in sorted(entries, key=lambda e: e.resource_id)
        ],
    }
    return ResourceSnapshot.model_validate({**values, "checksum": digest(values)})


def validate_snapshot(raw: dict[str, Any]) -> ResourceSnapshot:
    try:
        parsed = ResourceSnapshot.model_validate(raw)
        if (
            len(parsed.entries) > 200
            or len({e.resource_id for e in parsed.entries}) != len(parsed.entries)
            or parsed.checksum != digest(parsed.model_dump(mode="json", exclude={"checksum"}))
        ):
            raise ValueError
        return parsed
    except (ValueError, TypeError):
        raise invalid() from None
