"""Authenticated private component delivery; never publishes internal artwork."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from octop.infra.enterprise_resources.member_access import access_for
from octop.infra.enterprise_resources.models import canonical
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.setup.companion_package import CompanionInstaller
from octop.infra.users.identity import User

INSTALLER_KEY = "enterprise.companion.installer.v1"


def installer_directory(server: Any) -> Path:
    return Path(server.paths.root) / "companion" / "releases"


def installer_for(server: Any, user: User) -> tuple[CompanionInstaller, Path]:
    if not access_for(server).allows_companion(user):
        raise OctopError.localized(ErrorCode.COMPANION_ACCESS_DENIED)
    raw = server.services.settings_repo.get(INSTALLER_KEY)
    if raw is None:
        raise OctopError.localized(ErrorCode.COMPANION_NOT_AVAILABLE)
    metadata = CompanionInstaller.model_validate_json(raw)
    metadata.verify()
    path = installer_directory(server) / metadata.filename
    if path.is_symlink() or not path.is_file() or path.stat().st_size != metadata.size:
        raise OctopError.localized(ErrorCode.COMPANION_NOT_AVAILABLE)
    return metadata, path


def register_installer(server: Any, user: User, metadata: CompanionInstaller) -> None:
    access_for(server)._admin(user)
    metadata.verify()
    path = installer_directory(server) / metadata.filename
    if path.is_symlink() or not path.is_file() or path.stat().st_size != metadata.size:
        raise OctopError.localized(ErrorCode.COMPANION_INSTALL_FAILED)
    with path.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != metadata.sha256:
        raise OctopError.localized(ErrorCode.COMPANION_INSTALL_FAILED)
    old = server.services.settings_repo.get(INSTALLER_KEY)
    if old:
        previous = CompanionInstaller.model_validate_json(old)
        before = tuple(int(x) for x in previous.version.split("."))
        after = tuple(int(x) for x in metadata.version.split("."))
        if after < before or after == before and previous.sha256 != metadata.sha256:
            raise OctopError.localized(ErrorCode.ENTERPRISE_ACCESS_POLICY_CONFLICT)
    server.services.settings_repo.set(INSTALLER_KEY, canonical(metadata.model_dump(mode="json")))
    server.services.audit_repo.write(
        actor=user.username,
        action="enterprise.companion.installer.publish",
        target=metadata.filename,
        payload=metadata.sha256,
    )
