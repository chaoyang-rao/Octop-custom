"""Immutable content-addressed bundles and CAS-controlled company publication."""

from __future__ import annotations

import time
from typing import Any

from pydantic import Field

from octop.infra.auth.enterprise import center_for
from octop.infra.connectors.enterprise_catalog import CatalogMember, EnterpriseMcpCatalog
from octop.infra.enterprise_resources.models import (
    NAMESPACE,
    ResourceDefinition,
    ResourceEntry,
    ResourceSnapshot,
    StrictModel,
    canonical,
    conflict,
    digest,
    invalid,
    snapshot,
    validate_snapshot,
)
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.mobile_access.access import MobileUser
from octop.infra.users.identity import User
from octop.infra.users.permissions import user_has_permission

CATALOG_KEY = "enterprise.resources.catalog.v1"


class HistoryVersion(StrictModel):
    snapshot: ResourceSnapshot
    published_by: str


class CatalogDocument(StrictModel):
    draft: list[ResourceEntry] = Field(default_factory=list)
    published: ResourceSnapshot = Field(default_factory=lambda: snapshot(0, 0, []))
    history: list[HistoryVersion] = Field(default_factory=list)


class ResourceAdminState(StrictModel):
    etag: str
    draft: list[ResourceEntry]
    published: ResourceSnapshot
    history: list[dict[str, Any]]


class ResourceCatalog:
    def __init__(self, server: Any) -> None:
        self.server = server
        self.settings = server.services.settings_repo
        self.files = server.services.control_file_repo
        self.center = center_for(server)

    def _admin(self, user: User) -> None:
        self.center.require_employee(user)
        if isinstance(user, MobileUser) or not user.is_admin:
            raise OctopError.localized(ErrorCode.ENTERPRISE_ACCESS_DENIED)

    def _read(self) -> tuple[str | None, CatalogDocument]:
        raw = self.settings.get(CATALOG_KEY)
        try:
            document = CatalogDocument.model_validate_json(raw) if raw else CatalogDocument()
            validate_snapshot(document.published.model_dump(mode="json"))
            for record in document.history:
                validate_snapshot(record.snapshot.model_dump(mode="json"))
            return raw, document
        except (ValueError, TypeError):
            raise invalid() from None

    @staticmethod
    def _etag(raw: str | None) -> str:
        return digest(raw or "")

    def _view(self, raw: str | None, document: CatalogDocument) -> ResourceAdminState:
        return ResourceAdminState(
            etag=self._etag(raw),
            draft=document.draft,
            published=document.published,
            history=[
                {
                    "revision": h.snapshot.revision,
                    "published_at": h.snapshot.published_at,
                    "published_by": h.published_by,
                    "checksum": h.snapshot.checksum,
                }
                for h in reversed(document.history)
            ],
        )

    def _edit(self, expected: str) -> tuple[str | None, CatalogDocument]:
        raw, document = self._read()
        if expected != self._etag(raw):
            raise conflict()
        return raw, document

    def _save(
        self, user: User, raw: str | None, doc: CatalogDocument, action: str
    ) -> ResourceAdminState:
        value = canonical(doc.model_dump(mode="json"))
        if not self.settings.compare_and_set(CATALOG_KEY, raw, value):
            raise conflict()
        self.server.services.audit_repo.write(
            actor=user.username,
            action="enterprise.resources." + action,
            target=CATALOG_KEY,
            payload=str(doc.published.revision),
        )
        return self._view(value, doc)

    def admin(self, user: User) -> ResourceAdminState:
        self._admin(user)
        return self._view(*self._read())

    def members(self, user: User) -> list[CatalogMember]:
        self._admin(user)
        return EnterpriseMcpCatalog(self.server).members(user)

    def _bundle(self, content_digest: str) -> ResourceDefinition:
        raw = self.files.get(NAMESPACE, content_digest, "bundle.json")
        try:
            bundle = ResourceDefinition.model_validate_json(raw or b"")
            if bundle.content_digest() != content_digest:
                raise ValueError
            return bundle
        except (ValueError, TypeError):
            raise invalid() from None

    def save_entry(
        self, user: User, resource: ResourceDefinition, expected: str
    ) -> ResourceAdminState:
        self._admin(user)
        raw, doc = self._edit(expected)
        previous = [*doc.draft, *(e for h in doc.history for e in h.snapshot.entries)]
        if any(e.resource_id == resource.resource_id and e.kind != resource.kind for e in previous):
            raise invalid()
        payload = resource.model_dump(mode="json", exclude={"allowed_subjects", "enabled"})
        content_digest = resource.content_digest()
        existing = self.files.get(NAMESPACE, content_digest, "bundle.json")
        encoded = canonical(payload).encode()
        if existing is not None and existing != encoded:
            raise invalid()
        if existing is None:
            self.files.replace_tree(NAMESPACE, content_digest, [("bundle.json", encoded)])
        entry = ResourceEntry(
            resource_id=resource.resource_id,
            kind=resource.kind,
            display_name=resource.display_name,
            description=resource.description,
            enabled=resource.enabled,
            allowed_subjects=resource.allowed_subjects,
            digest=content_digest,
        )
        doc.draft = sorted(
            [e for e in doc.draft if e.resource_id != resource.resource_id] + [entry],
            key=lambda e: e.resource_id,
        )
        if len(doc.draft) > 200:
            raise invalid()
        return self._save(user, raw, doc, "save_draft")

    def remove_entry(self, user: User, resource_id: str, expected: str) -> ResourceAdminState:
        self._admin(user)
        raw, doc = self._edit(expected)
        doc.draft = [e for e in doc.draft if e.resource_id != resource_id]
        return self._save(user, raw, doc, "remove_draft")

    def _publish(
        self,
        user: User,
        raw: str | None,
        doc: CatalogDocument,
        entries: list[ResourceEntry],
        action: str,
    ) -> ResourceAdminState:
        available = {e.resource_id: e for e in entries if e.enabled}
        for entry in entries:
            if not entry.enabled:
                continue
            bundle = self._bundle(entry.digest)
            if any(
                ref not in available or available[ref].kind != "skill" for ref in bundle.skill_refs
            ):
                raise invalid()
            for ref in bundle.skill_refs:
                visible = available[ref].allowed_subjects
                if visible and (
                    not entry.allowed_subjects or not set(entry.allowed_subjects) <= set(visible)
                ):
                    raise invalid()
        doc.published = snapshot(doc.published.revision + 1, int(time.time()), entries)
        doc.history.append(
            HistoryVersion(snapshot=doc.published.model_copy(deep=True), published_by=user.username)
        )
        return self._save(user, raw, doc, action)

    def publish(self, user: User, expected: str) -> ResourceAdminState:
        self._admin(user)
        raw, doc = self._edit(expected)
        return self._publish(user, raw, doc, doc.draft, "publish")

    def rollback(self, user: User, revision: int, expected: str) -> ResourceAdminState:
        self._admin(user)
        raw, doc = self._edit(expected)
        previous = next((h for h in doc.history if h.snapshot.revision == revision), None)
        if previous is None:
            raise OctopError.localized(ErrorCode.NOT_FOUND)
        return self._publish(user, raw, doc, previous.snapshot.entries, "rollback")

    def member(self, user: User) -> ResourceSnapshot:
        subject = self.center.require_employee(user)
        principal = user
        if isinstance(user, MobileUser):
            if user.device_scopes != ("enterprise",):
                raise OctopError.localized(ErrorCode.ENTERPRISE_ACCESS_DENIED)
            owner = self.server.user_manager.get_by_id(user.id)
            if owner is None:
                raise OctopError.localized(ErrorCode.ENTERPRISE_ACCESS_DENIED)
            # Device permissions intentionally exclude management capabilities.
            # Directory eligibility follows its current owner without widening
            # the credential's strictly read-only HTTP scope.
            principal = owner
        _, doc = self._read()
        entries = [
            e.model_copy(update={"allowed_subjects": []})
            for e in doc.published.entries
            if (not e.allowed_subjects or subject in e.allowed_subjects)
            and user_has_permission(principal, "experts" if e.kind == "expert" else "skills")
        ]
        return snapshot(doc.published.revision, doc.published.published_at, entries)

    def bundle(self, user: User, content_digest: str) -> ResourceDefinition:
        self.center.require_employee(user)
        _, doc = self._read()
        if user.is_admin and not isinstance(user, MobileUser):
            allowed = {e.digest for e in doc.draft} | {
                e.digest for h in doc.history for e in h.snapshot.entries
            }
        else:
            allowed = {e.digest for e in self.member(user).entries if e.enabled}
        if content_digest not in allowed:
            raise OctopError.localized(ErrorCode.ENTERPRISE_ACCESS_DENIED)
        return self._bundle(content_digest)
