"""Versioned, credential-free enterprise MCP definitions and filtered snapshots."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import time
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from octop.infra.errors import ErrorCode, OctopError
from octop.infra.users.identity import User

CATALOG_KEY = "enterprise.mcp.catalog.v1"
_ENTRY_ID = r"^[A-Za-z0-9_-]{1,64}$"


def _invalid() -> OctopError:
    return OctopError.localized(ErrorCode.ENTERPRISE_MCP_CATALOG_INVALID)


def _conflict() -> OctopError:
    return OctopError.localized(ErrorCode.ENTERPRISE_MCP_CATALOG_CONFLICT)


def _canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _validate_url(value: str) -> str:
    if any(char.isspace() or ord(char) < 32 for char in value) or "\\" in value:
        raise ValueError("invalid catalog URL")
    parsed = urlsplit(value)
    host = (parsed.hostname or "").lower().rstrip(".")
    try:
        host = host.encode("idna").decode("ascii").lower().rstrip(".")
    except UnicodeError:
        raise ValueError("invalid catalog host") from None
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or "?" in value
        or "#" in value
        or "%" in host
        or host
        in {"localhost", "localhost.localdomain", "host.docker.internal", "gateway.docker.internal"}
        or host.endswith(".localhost")
    ):
        raise ValueError("invalid catalog URL")
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError("invalid catalog port")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        # Reject ambiguous numeric IPv4 syntax that some network stacks resolve
        # as loopback (integer, shortened, octal, and hexadecimal forms).
        if all(re.fullmatch(r"(?:0x[0-9a-f]+|[0-9]+)", part, re.I) for part in host.split(".")):
            raise ValueError("ambiguous catalog host") from None
    else:
        mapped = address.ipv4_mapped if isinstance(address, ipaddress.IPv6Address) else None
        if (
            address.is_loopback
            or address.is_unspecified
            or address.is_link_local
            or (
                mapped is not None
                and (mapped.is_loopback or mapped.is_unspecified or mapped.is_link_local)
            )
        ):
            raise ValueError("local catalog host")
    return value


class CatalogEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    entry_id: str = Field(pattern=_ENTRY_ID)
    display_name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)
    url: str = Field(min_length=1, max_length=2048)
    auth_kind: Literal["none", "bearer", "basic"] = "none"
    enabled: bool = True
    allowed_subjects: list[str] = Field(default_factory=list, max_length=1000)

    @field_validator("url")
    @classmethod
    def valid_url(cls, value: str) -> str:
        return _validate_url(value)

    @field_validator("allowed_subjects")
    @classmethod
    def valid_subjects(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(
            not value or len(value) > 128 or any(c.isspace() for c in value) for value in normalized
        ):
            raise ValueError("invalid catalog subject")
        return sorted(set(normalized))


class CatalogSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: int = Field(default=1, ge=1, le=1)
    revision: int = Field(ge=0)
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    published_at: int = Field(ge=0)
    entries: list[CatalogEntry] = Field(max_length=1000)

    @field_validator("entries")
    @classmethod
    def unique_ids(cls, entries: list[CatalogEntry]) -> list[CatalogEntry]:
        if len({entry.entry_id for entry in entries}) != len(entries):
            raise ValueError("duplicate catalog entry")
        return entries


class CatalogDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    entries: list[CatalogEntry]


class CatalogVersionMeta(BaseModel):
    revision: int
    published_at: int
    published_by: str
    checksum: str


class CatalogAdminState(BaseModel):
    etag: str
    draft: CatalogDraft
    published: CatalogSnapshot
    history: list[CatalogVersionMeta]


class CatalogMember(BaseModel):
    subject: str
    display_name: str


class _HistoryRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    snapshot: CatalogSnapshot
    published_by: str


class _CatalogDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: int = Field(default=1, ge=1, le=1)
    draft: CatalogDraft
    published: CatalogSnapshot
    history: list[_HistoryRecord]


def validate_entries(entries: Any) -> list[CatalogEntry]:
    try:
        if not isinstance(entries, list) or len(entries) > 1000:
            raise ValueError("invalid entries")
        result = [
            entry if isinstance(entry, CatalogEntry) else CatalogEntry.model_validate(entry)
            for entry in entries
        ]
        if len({entry.entry_id for entry in result}) != len(result):
            raise ValueError("duplicate entry")
        return sorted(result, key=lambda entry: entry.entry_id)
    except (ValidationError, ValueError, TypeError):
        # Never echo invalid input: a rejected extra field may contain a token.
        raise _invalid() from None


def entry_fingerprint(entry: CatalogEntry | dict[str, Any]) -> str:
    parsed = entry if isinstance(entry, CatalogEntry) else validate_entries([entry])[0]
    return hashlib.sha256(
        _canonical(
            {"entry_id": parsed.entry_id, "url": parsed.url, "auth_kind": parsed.auth_kind}
        ).encode()
    ).hexdigest()


def snapshot_checksum(snapshot: CatalogSnapshot | dict[str, Any]) -> str:
    payload = (
        snapshot.model_dump(mode="json")
        if isinstance(snapshot, CatalogSnapshot)
        else dict(snapshot)
    )
    payload.pop("checksum", None)
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def build_snapshot(
    *, revision: int, published_at: int, entries: list[CatalogEntry] | list[dict[str, Any]]
) -> CatalogSnapshot:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "revision": revision,
        "published_at": published_at,
        "entries": [entry.model_dump(mode="json") for entry in validate_entries(entries)],
    }
    return CatalogSnapshot.model_validate({**payload, "checksum": snapshot_checksum(payload)})


def validate_snapshot(raw: dict[str, Any]) -> CatalogSnapshot:
    try:
        parsed = CatalogSnapshot.model_validate(raw)
        if parsed.checksum != snapshot_checksum(parsed):
            raise ValueError("catalog checksum mismatch")
        return parsed
    except (ValidationError, ValueError, TypeError):
        raise _invalid() from None


class EnterpriseMcpCatalog:
    """Own the central catalogue; member credentials never enter this document."""

    def __init__(self, server: Any) -> None:
        from octop.infra.auth.enterprise import center_for

        self.server = server
        self.settings = server.services.settings_repo
        self.center = center_for(server)

    def _admin(self, user: User) -> None:
        from octop.infra.mobile_access.access import MobileUser

        self.center.require_employee(user)
        if isinstance(user, MobileUser) or not user.is_admin:
            raise OctopError.localized(ErrorCode.ENTERPRISE_ACCESS_DENIED)

    def _read(self) -> tuple[str | None, _CatalogDocument]:
        raw = self.settings.get(CATALOG_KEY)
        if raw is None:
            return None, _CatalogDocument(
                draft=CatalogDraft(entries=[]),
                published=build_snapshot(revision=0, published_at=0, entries=[]),
                history=[],
            )
        try:
            document = _CatalogDocument.model_validate_json(raw)
            validate_entries(document.draft.entries)
            validate_snapshot(document.published.model_dump(mode="json"))
            for item in document.history:
                validate_snapshot(item.snapshot.model_dump(mode="json"))
            return raw, document
        except (ValidationError, ValueError, TypeError):
            raise _invalid() from None

    @staticmethod
    def _etag(raw: str | None) -> str:
        return hashlib.sha256((raw or "").encode("utf-8")).hexdigest()

    def _view(self, raw: str | None, document: _CatalogDocument) -> CatalogAdminState:
        return CatalogAdminState(
            etag=self._etag(raw),
            draft=document.draft,
            published=document.published,
            history=[
                CatalogVersionMeta(
                    revision=item.snapshot.revision,
                    published_at=item.snapshot.published_at,
                    published_by=item.published_by,
                    checksum=item.snapshot.checksum,
                )
                for item in document.history
            ],
        )

    def get_admin(self, user: User) -> CatalogAdminState:
        self._admin(user)
        raw, document = self._read()
        return self._view(raw, document)

    def members(self, user: User) -> list[CatalogMember]:
        self._admin(user)
        members: list[CatalogMember] = []
        for row in self.server.services.user_repo.list(include_disabled=False):
            candidate = self.server.user_manager.get_by_id(row.id)
            if candidate is None:
                continue
            try:
                subject = self.center.require_employee(candidate)
            except OctopError as exc:
                if exc.code in {
                    ErrorCode.ENTERPRISE_ACCESS_DENIED,
                    ErrorCode.ENTERPRISE_FEISHU_REQUIRED,
                }:
                    continue
                raise
            members.append(CatalogMember(subject=subject, display_name=candidate.label))
        return sorted(members, key=lambda member: (member.display_name.casefold(), member.subject))

    def _save(
        self, user: User, raw: str | None, document: _CatalogDocument, action: str
    ) -> CatalogAdminState:
        serialized = _canonical(document.model_dump(mode="json"))
        if not self.settings.compare_and_set(CATALOG_KEY, raw, serialized):
            raise _conflict()
        self.server.services.audit_repo.write(
            actor=user.username,
            action="enterprise.mcp_catalog." + action,
            target=CATALOG_KEY,
            payload=str(document.published.revision),
        )
        return self._view(serialized, document)

    def _edit(self, expected_etag: str) -> tuple[str | None, _CatalogDocument]:
        raw, document = self._read()
        if self._etag(raw) != expected_etag:
            raise _conflict()
        return raw, document.model_copy(deep=True)

    def save_draft(self, user: User, entries: Any, expected_etag: str) -> CatalogAdminState:
        self._admin(user)
        parsed = validate_entries(entries)
        raw, document = self._edit(expected_etag)
        document.draft = CatalogDraft(entries=parsed)
        return self._save(user, raw, document, "save_draft")

    def _publish(
        self,
        user: User,
        raw: str | None,
        document: _CatalogDocument,
        entries: list[CatalogEntry],
        action: str,
    ) -> CatalogAdminState:
        snapshot = build_snapshot(
            revision=document.published.revision + 1, published_at=int(time.time()), entries=entries
        )
        document.published = snapshot
        document.history.append(
            _HistoryRecord(snapshot=snapshot.model_copy(deep=True), published_by=user.username)
        )
        return self._save(user, raw, document, action)

    def publish(self, user: User, expected_etag: str) -> CatalogAdminState:
        self._admin(user)
        raw, document = self._edit(expected_etag)
        return self._publish(user, raw, document, document.draft.entries, "publish")

    def rollback(self, user: User, revision: int, expected_etag: str) -> CatalogAdminState:
        self._admin(user)
        raw, document = self._edit(expected_etag)
        previous = next(
            (item for item in document.history if item.snapshot.revision == revision), None
        )
        if previous is None:
            raise OctopError.localized(ErrorCode.NOT_FOUND)
        # Rolling back published configuration does not erase an unpublished draft.
        return self._publish(user, raw, document, previous.snapshot.entries, "rollback")

    def snapshot_for(self, user: User) -> CatalogSnapshot:
        subject = self.center.require_employee(user)
        _, document = self._read()
        entries = [
            entry.model_copy(update={"allowed_subjects": []}, deep=True)
            for entry in document.published.entries
            if not entry.allowed_subjects or subject in entry.allowed_subjects
        ]
        return build_snapshot(
            revision=document.published.revision,
            published_at=document.published.published_at,
            entries=entries,
        )
