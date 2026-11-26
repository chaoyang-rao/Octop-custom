"""Administrator publication and revocable, signed company desktop releases."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import time
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from packaging.version import Version

from octop.infra.auth.enterprise import center_for
from octop.infra.client_updates.github import companion_metadata, package_metadata, release_index
from octop.infra.client_updates.models import (
    ClientRelease,
    CompanionRelease,
    DeviceReport,
    SignedRelease,
    canonical,
    failure,
    fingerprint,
)
from octop.infra.connectors.enterprise_catalog import EnterpriseMcpCatalog
from octop.infra.crypto.fernet import decrypt_json, encrypt_json
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.users.identity import User

CATALOG_KEY = "enterprise.client_updates.catalog.v1"
SIGNER_KEY = "enterprise.client_updates.signer.v1"
REPORTS_KEY = "enterprise.client_updates.reports.v1"
_PURPOSE = "enterprise_client_update_signer"


def initialize_signer(services: Any, authority: str) -> dict[str, Any]:
    """Deployment-only bootstrap. Export public material, never the private key."""
    repo = services.secret_repo
    raw = repo.get(SIGNER_KEY)
    if raw is None:
        key = Ed25519PrivateKey.generate()
        material = {
            "authority": authority.rstrip("/"),
            "private": base64.b64encode(
                key.private_bytes(
                    serialization.Encoding.Raw,
                    serialization.PrivateFormat.Raw,
                    serialization.NoEncryption(),
                )
            ).decode(),
        }
        repo.set(SIGNER_KEY, encrypt_json(repo, _PURPOSE, material))
    else:
        material = decrypt_json(repo, _PURPOSE, raw)
        if material["authority"] != authority.rstrip("/"):
            raise failure(ErrorCode.CLIENT_UPDATE_INTEGRITY)
    key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(material["private"]))
    public = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    key_id = hashlib.sha256(public).hexdigest()[:16]
    return {
        "schema_version": 1,
        "authorities": {material["authority"]: {key_id: base64.b64encode(public).decode()}},
    }


class ClientUpdateCatalog:
    def __init__(self, server: Any) -> None:
        self.server = server
        self.settings = server.services.settings_repo
        self.secrets = server.services.secret_repo
        self.center = center_for(server)

    def _admin(self, user: User) -> None:
        EnterpriseMcpCatalog(self.server)._admin(user)

    def _read(self) -> tuple[str | None, dict[str, Any]]:
        raw = self.settings.get(CATALOG_KEY)
        try:
            state = (
                json.loads(raw)
                if raw
                else {"revision": 0, "draft": None, "published": None, "history": []}
            )
            if not isinstance(state, dict) or not isinstance(state["revision"], int):
                raise ValueError
            return raw, state
        except (ValueError, KeyError, TypeError):
            raise failure() from None

    def _sign(self, release: ClientRelease) -> SignedRelease:
        raw = self.secrets.get(SIGNER_KEY)
        if raw is None:
            raise failure(ErrorCode.CLIENT_UPDATE_NOT_CONFIGURED)
        try:
            material = decrypt_json(self.secrets, _PURPOSE, raw)
            if material["authority"] != release.authority:
                raise ValueError
            key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(material["private"]))
            public = key.public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw
            )
            data = canonical(release.model_dump(mode="json"))
            return SignedRelease(
                key_id=hashlib.sha256(public).hexdigest()[:16],
                payload=base64.b64encode(data).decode(),
                signature=base64.b64encode(key.sign(data)).decode(),
            )
        except (ValueError, KeyError, TypeError):
            raise failure(ErrorCode.CLIENT_UPDATE_INTEGRITY) from None

    def _origin(self) -> str:
        raw = self.secrets.get(SIGNER_KEY)
        if raw is None:
            raise failure(ErrorCode.CLIENT_UPDATE_NOT_CONFIGURED)
        return str(decrypt_json(self.secrets, _PURPOSE, raw)["authority"])

    def _save(
        self, user: User, raw: str | None, state: dict[str, Any], action: str
    ) -> dict[str, Any]:
        if not self.settings.compare_and_set(CATALOG_KEY, raw, canonical(state).decode()):
            raise failure(ErrorCode.CLIENT_UPDATE_CONFLICT)
        self.server.services.audit_repo.write(
            actor=user.username,
            action="enterprise.client_updates." + action,
            target=CATALOG_KEY,
            payload=str(state["revision"]),
        )
        return self.admin(user)

    def admin(self, user: User) -> dict[str, Any]:
        self._admin(user)
        raw, state = self._read()
        reports = json.loads(self.settings.get(REPORTS_KEY) or "{}")
        users = {
            row.id: row.display_name or row.username
            for row in self.server.services.user_repo.list()
        }
        return {
            "etag": fingerprint(raw),
            "revision": state["revision"],
            "signing_configured": bool(self.secrets.get(SIGNER_KEY)),
            "draft": state["draft"],
            "published": state["published"],
            "history": state["history"],
            "devices": [
                {**value, "display_name": users.get(value["user_id"], "")}
                for value in reports.values()
            ],
        }

    async def releases(self, user: User) -> list[dict[str, Any]]:
        await asyncio.to_thread(self._admin, user)
        result = []
        for row in await release_index():
            try:
                tag, version, commit, _, notes = package_metadata(row)
                companion = companion_metadata(row)
                result.append(
                    {
                        "tag": tag,
                        "version": version,
                        "source_commit": commit,
                        "notes": notes,
                        "companion_version": companion["version"] if companion else None,
                    }
                )
            except (OctopError, ValueError, TypeError, KeyError):
                continue
        return result

    async def import_release(self, user: User, tag: str, expected_etag: str) -> dict[str, Any]:
        await asyncio.to_thread(self._admin, user)
        raw, state = await asyncio.to_thread(self._read)
        if fingerprint(raw) != expected_etag:
            raise failure(ErrorCode.CLIENT_UPDATE_CONFLICT)
        chosen = next((row for row in await release_index() if row.get("tag_name") == tag), None)
        if chosen is None:
            raise failure()
        tag, version, commit, packages, notes = package_metadata(chosen)
        companion = companion_metadata(chosen)
        state["draft"] = {
            "version": version,
            "tag": tag,
            "source_commit": commit,
            "notes": notes,
            "packages": [item.model_dump(mode="json") for item in packages],
            "companion": companion,
        }
        return await asyncio.to_thread(self._save, user, raw, state, "import")

    def publish(
        self, user: User, expected_etag: str, allowed_subjects: list[str]
    ) -> dict[str, Any]:
        self._admin(user)
        raw, state = self._read()
        if fingerprint(raw) != expected_etag:
            raise failure(ErrorCode.CLIENT_UPDATE_CONFLICT)
        draft = state["draft"]
        if not draft:
            raise failure()
        draft = dict(draft)
        companion_draft = draft.pop("companion", None)
        eligible = {item.subject for item in EnterpriseMcpCatalog(self.server).members(user)}
        if not set(allowed_subjects) <= eligible:
            raise failure()
        for previous in state["history"]:
            value = previous["release"]
            if Version(draft["version"]) < Version(value["version"]):
                raise failure(ErrorCode.CLIENT_UPDATE_CONFLICT)
            if draft["version"] == value["version"] and draft["packages"] != value["packages"]:
                raise failure(ErrorCode.CLIENT_UPDATE_INTEGRITY)
        release = ClientRelease(
            **draft,
            authority=self._origin(),
            revision=state["revision"] + 1,
            published_at=int(time.time()),
            allowed_subjects=allowed_subjects,
        )
        envelope = self._sign(release)
        companion_published = None
        if companion_draft:
            for previous in state["history"]:
                old = previous.get("companion")
                if old and (
                    Version(companion_draft["version"]) < Version(old["version"])
                    or (
                        companion_draft["version"] == old["version"]
                        and companion_draft["packages"] != old["packages"]
                    )
                ):
                    raise failure(ErrorCode.CLIENT_UPDATE_CONFLICT)
            companion = CompanionRelease(
                **companion_draft,
                authority=release.authority,
                revision=release.revision,
                published_at=release.published_at,
                allowed_subjects=allowed_subjects,
            )
            companion_published = {
                "release": companion.model_dump(mode="json"),
                "envelope": self._sign(companion).model_dump(mode="json"),
            }
        state.update(
            revision=release.revision,
            published={
                "release": release.model_dump(mode="json"),
                "envelope": envelope.model_dump(mode="json"),
                "companion": companion_published,
            },
        )
        state["history"] = (
            [
                {
                    "release": release.model_dump(mode="json"),
                    "published_by": user.username,
                    "companion": companion_published["release"] if companion_published else None,
                }
            ]
            + state["history"]
        )[:30]
        return self._save(user, raw, state, "publish")

    def withdraw(self, user: User, expected_etag: str) -> dict[str, Any]:
        self._admin(user)
        raw, state = self._read()
        if fingerprint(raw) != expected_etag or state["published"] is None:
            raise failure(ErrorCode.CLIENT_UPDATE_CONFLICT)
        release = ClientRelease.model_validate(state["published"]["release"]).model_copy(
            update={"enabled": False, "revision": state["revision"] + 1}
        )
        companion_published = state["published"].get("companion")
        if companion_published:
            companion = CompanionRelease.model_validate(companion_published["release"]).model_copy(
                update={"enabled": False, "revision": release.revision}
            )
            companion_published = {
                "release": companion.model_dump(mode="json"),
                "envelope": self._sign(companion).model_dump(mode="json"),
            }
        state.update(
            revision=release.revision,
            published={
                "release": release.model_dump(mode="json"),
                "envelope": self._sign(release).model_dump(mode="json"),
                "companion": companion_published,
            },
        )
        return self._save(user, raw, state, "withdraw")

    def member(self, user: User) -> dict[str, Any]:
        subject = self.center.require_employee(user)
        _, state = self._read()
        published = state["published"]
        if not published:
            return {"revision": state["revision"], "envelope": None}
        release = ClientRelease.model_validate(published["release"])
        permitted = not release.allowed_subjects or subject in release.allowed_subjects
        companion = published.get("companion")
        return {
            "revision": state["revision"],
            "envelope": published["envelope"] if permitted else None,
            "companion_envelope": companion["envelope"] if permitted and companion else None,
        }

    def report(self, user: User, token: str, report: DeviceReport) -> dict[str, bool]:
        profile = self.center.profile(token)
        session = self.center.devices.authenticate(token)
        if session.user_id != user.id or session.scopes != ("enterprise",):
            raise failure(ErrorCode.ENTERPRISE_ACCESS_DENIED)
        device_id = profile["device_id"]
        if report.product == "octop-companion":
            device_id += ":octop-companion"
        value = {
            **report.model_dump(mode="json"),
            "device_id": device_id,
            "user_id": user.id,
            "last_seen_at": int(time.time()),
        }
        for _ in range(5):
            raw = self.settings.get(REPORTS_KEY)
            reports = json.loads(raw or "{}")
            if device_id not in reports and len(reports) >= 10000:
                raise failure()
            previous = reports.get(device_id)
            reports[device_id] = value
            if self.settings.compare_and_set(REPORTS_KEY, raw, canonical(reports).decode()):
                if (
                    previous is None
                    or previous.get("phase") != value["phase"]
                    or previous.get("current_version") != value["current_version"]
                ):
                    self.server.services.audit_repo.write(
                        actor=user.username,
                        action="enterprise.client_updates.report",
                        target=device_id,
                        payload=canonical(report.model_dump(mode="json")).decode(),
                    )
                return {"ok": True}
        raise failure(ErrorCode.CLIENT_UPDATE_CONFLICT)
