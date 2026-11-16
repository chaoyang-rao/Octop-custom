"""Pinned publisher signature for the private desktop-pet component."""

from __future__ import annotations

import base64

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import Field

from octop.infra.enterprise_resources.models import StrictModel, canonical
from octop.infra.errors import ErrorCode, OctopError

PUBLIC_KEY = "OZtDL3eMhGZ7HaAf0s9I1oka+5B9V3suUG9ThhG/0aA="
BUNDLE_ID = "com.chaoyangrao.octop.companion"


class CompanionInstaller(StrictModel):
    filename: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*\.zip$")
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    size: int = Field(gt=0, le=2 * 1024**3)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    signature: str = Field(min_length=64, max_length=128)

    def signed_bytes(self) -> bytes:
        return canonical(self.model_dump(exclude={"signature"})).encode()

    def verify(self) -> None:
        try:
            Ed25519PublicKey.from_public_bytes(base64.b64decode(PUBLIC_KEY, validate=True)).verify(
                base64.b64decode(self.signature, validate=True), self.signed_bytes()
            )
        except (InvalidSignature, ValueError):
            raise OctopError.localized(ErrorCode.COMPANION_INSTALL_FAILED) from None
