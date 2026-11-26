"""The deliberately small signed desktop-update protocol; no commands or paths."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal, Self
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from packaging.version import InvalidVersion, Version
from pydantic import Field, field_validator, model_validator

from octop.infra.enterprise_resources.models import StrictModel
from octop.infra.errors import ErrorCode, OctopError

REPOSITORY = "chaoyang-rao/Octop-custom"
Platform = Literal["windows-amd64", "darwin-amd64", "darwin-arm64"]
Product = Literal["octop-desktop", "octop-companion"]
PLATFORMS: tuple[Platform, ...] = ("windows-amd64", "darwin-amd64", "darwin-arm64")
Phase = Literal[
    "idle",
    "available",
    "downloading",
    "downloaded",
    "waiting_idle",
    "applying",
    "backing_up",
    "ready_to_swap",
    "installing",
    "starting",
    "rolling_back",
    "candidate_ready",
    "accepted",
    "failed",
    "rolled_back",
    "cancelled",
]
PROTOCOL = 1
MAX_ARCHIVE = 2 * 1024**3


def failure(code: ErrorCode = ErrorCode.CLIENT_UPDATE_INVALID) -> OctopError:
    return OctopError.localized(code)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def valid_version(value: str) -> str:
    try:
        parsed = Version(value)
    except InvalidVersion:
        raise ValueError("Invalid custom version") from None
    if parsed.post is None or not re.fullmatch(r"[A-Za-z0-9.+-]{1,80}", value):
        raise ValueError("A custom post release is required")
    return value


def asset_name(platform: str, version: str) -> str:
    return f"OctopCustom-update-{platform}-{version}.zip"


def companion_asset_name(platform: str, version: str) -> str:
    return f"Dora-update-{platform}-{version}.zip"


def valid_companion_version(value: str) -> str:
    if not re.fullmatch(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)", value):
        raise ValueError("A stable companion version is required")
    return value


def release_asset_url(tag: str, name: str) -> str:
    return f"https://github.com/{REPOSITORY}/releases/download/{tag}/{name}"


class ClientPackage(StrictModel):
    platform: Platform
    filename: str = Field(min_length=1, max_length=180)
    url: str = Field(max_length=500)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size: int = Field(gt=0, le=MAX_ARCHIVE)


class ClientRelease(StrictModel):
    schema_version: Literal[1] = 1
    protocol: Literal[1] = 1
    authority: str = Field(max_length=300)
    revision: int = Field(ge=1)
    version: str
    tag: str = Field(pattern=r"^custom-[A-Za-z0-9.-]{1,90}$")
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    published_at: int = Field(ge=0)
    notes: str = Field(default="", max_length=20000)
    enabled: bool = True
    allowed_subjects: list[str] = Field(default_factory=list, max_length=10000)
    packages: list[ClientPackage] = Field(min_length=3, max_length=3)

    _version = field_validator("version")(valid_version)

    def package_name(self, platform: str) -> str:
        return asset_name(platform, self.version)

    @model_validator(mode="after")
    def validate_release(self) -> Self:
        parsed = urlsplit(self.authority)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or self.authority.endswith("/")
        ):
            raise ValueError("Invalid company origin")
        if {item.platform for item in self.packages} != set(PLATFORMS):
            raise ValueError("All three desktop packages are required")
        for item in self.packages:
            name = self.package_name(item.platform)
            if item.filename != name or item.url != release_asset_url(self.tag, name):
                raise ValueError("Only this repository's release assets are accepted")
        if any(not re.fullmatch(r"[0-9a-f]{64}", item) for item in self.allowed_subjects):
            raise ValueError("Invalid audience")
        return self


class CompanionRelease(ClientRelease):
    product: Literal["octop-companion"] = "octop-companion"

    _version = field_validator("version")(valid_companion_version)

    def package_name(self, platform: str) -> str:
        return companion_asset_name(platform, self.version)


class SignedRelease(StrictModel):
    key_id: str = Field(pattern=r"^[0-9a-f]{16}$")
    payload: str = Field(min_length=4, max_length=500000)
    signature: str = Field(min_length=80, max_length=100)


class DeviceReport(StrictModel):
    product: Product = "octop-desktop"
    platform: Platform
    device_name: str = Field(default="", max_length=80)
    current_version: str
    target_version: str | None = Field(default=None, max_length=80)
    protocol: Literal[1] = 1
    phase: Phase
    error_code: str | None = Field(default=None, pattern=r"^[A-Z_]{1,80}$")

    @model_validator(mode="after")
    def validate_version(self) -> Self:
        validator = valid_companion_version if self.product == "octop-companion" else valid_version
        validator(self.current_version)
        return self


def trust_document() -> dict[str, dict[str, str]]:
    try:
        value = json.loads(Path(__file__).with_name("trust.json").read_text())
        return dict(value["authorities"])
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def verify_release(
    envelope: SignedRelease,
    authority: str,
    trust: dict[str, dict[str, str]] | None = None,
    *,
    product: Product = "octop-desktop",
) -> ClientRelease:
    try:
        keys = (trust if trust is not None else trust_document())[authority]
        key = base64.b64decode(keys[envelope.key_id], validate=True)
        data = base64.b64decode(envelope.payload, validate=True)
        signature = base64.b64decode(envelope.signature, validate=True)
        Ed25519PublicKey.from_public_bytes(key).verify(signature, data)
        model = CompanionRelease if product == "octop-companion" else ClientRelease
        release = model.model_validate_json(data)
        if release.authority != authority or canonical(release.model_dump(mode="json")) != data:
            raise ValueError
        return release
    except (ValueError, KeyError, TypeError, InvalidSignature):
        raise failure(ErrorCode.CLIENT_UPDATE_INTEGRITY) from None
