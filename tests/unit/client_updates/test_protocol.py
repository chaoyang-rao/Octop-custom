"""Publication authenticity, bounded metadata and administrator/device separation."""

from __future__ import annotations

import base64
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from octop.infra.client_updates.catalog import ClientUpdateCatalog, initialize_signer
from octop.infra.client_updates.github import (
    companion_metadata,
    github_download_host,
    package_metadata,
)
from octop.infra.client_updates.models import (
    PLATFORMS,
    ClientPackage,
    ClientRelease,
    SignedRelease,
    asset_name,
    canonical,
    companion_asset_name,
    release_asset_url,
    verify_release,
)
from octop.infra.errors import OctopError
from octop.infra.mobile_access.access import MobileUser
from octop.infra.users.identity import User

ORIGIN = "https://company.example"
VERSION = "1.0.3b3.post2026111801"
TAG = "custom-1.0.3b3-20261118.1"


class Settings:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def compare_and_set(self, key: str, before: str | None, after: str) -> bool:
        if self.values.get(key) != before:
            return False
        self.values[key] = after
        return True


class Secrets:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}

    def get(self, key: str) -> bytes | None:
        return self.values.get(key)

    def set(self, key: str, value: bytes) -> None:
        self.values[key] = value

    def get_or_create(self, key: str, create: object) -> bytes:
        if key not in self.values:
            assert callable(create)
            self.values[key] = create()
        return self.values[key]


def packages() -> list[ClientPackage]:
    return [
        ClientPackage(
            platform=p,
            filename=asset_name(p, VERSION),
            url=release_asset_url(TAG, asset_name(p, VERSION)),
            sha256="a" * 64,
            size=100000001,
        )
        for p in PLATFORMS
    ]


@pytest.fixture
def company(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[ClientUpdateCatalog, User, dict[str, dict[str, str]]]:
    admin = User(id=1, username="publisher", role="admin", display_name="Publisher", locale="zh")
    employee = replace(admin, id=2, username="member", role="user")
    center = SimpleNamespace(require_employee=lambda user: str(user.id).zfill(64))
    monkeypatch.setattr("octop.infra.auth.enterprise.center_for", lambda server: center)
    monkeypatch.setattr("octop.infra.client_updates.catalog.center_for", lambda server: center)
    services = SimpleNamespace(
        settings_repo=Settings(),
        secret_repo=Secrets(),
        user_repo=SimpleNamespace(list=lambda **kwargs: [admin, employee]),
        audit_repo=SimpleNamespace(write=lambda **kwargs: None),
    )
    server = SimpleNamespace(
        services=services,
        user_manager=SimpleNamespace(
            get_by_id=lambda identifier: admin if identifier == 1 else employee
        ),
    )
    trust = initialize_signer(services, ORIGIN)["authorities"]
    return ClientUpdateCatalog(server), admin, trust


def publish(
    company: tuple[ClientUpdateCatalog, User, dict[str, dict[str, str]]],
    *,
    companion: bool = False,
) -> tuple[SignedRelease, ClientRelease]:
    catalog, admin, _ = company
    _, state = catalog._read()
    state["draft"] = {
        "version": VERSION,
        "tag": TAG,
        "source_commit": "b" * 40,
        "notes": "Changes",
        "packages": [p.model_dump() for p in packages()],
    }
    if companion:
        state["draft"]["companion"] = {
            "version": "0.10.0",
            "tag": TAG,
            "source_commit": "b" * 40,
            "notes": "Companion update",
            "packages": companion_packages(),
        }
    catalog.settings.compare_and_set(
        "enterprise.client_updates.catalog.v1", None, canonical(state).decode()
    )
    result = catalog.publish(admin, catalog.admin(admin)["etag"], [])
    return SignedRelease.model_validate(
        result["published"]["envelope"]
    ), ClientRelease.model_validate(result["published"]["release"])


def companion_packages() -> list[dict[str, object]]:
    return [
        {
            **p.model_dump(),
            "filename": companion_asset_name(p.platform, "0.10.0"),
            "url": release_asset_url(TAG, companion_asset_name(p.platform, "0.10.0")),
        }
        for p in packages()
    ]


def test_joint_publication_keeps_legacy_signature_and_separate_product_identity(
    company: tuple[ClientUpdateCatalog, User, dict[str, dict[str, str]]],
) -> None:
    catalog, admin, trust = company
    desktop_envelope, desktop = publish(company, companion=True)
    assert verify_release(desktop_envelope, ORIGIN, trust) == desktop
    legacy_payload = json.loads(base64.b64decode(desktop_envelope.payload))
    assert "product" not in legacy_payload and "companion" not in legacy_payload
    companion = catalog.admin(admin)["published"]["companion"]
    envelope = SignedRelease.model_validate(companion["envelope"])
    release = verify_release(envelope, ORIGIN, trust, product="octop-companion")
    assert release.version == "0.10.0" and release.revision == desktop.revision
    with pytest.raises(OctopError):
        verify_release(envelope, ORIGIN, trust)
    with pytest.raises(OctopError):
        verify_release(desktop_envelope, ORIGIN, trust, product="octop-companion")
    withdrawn = catalog.withdraw(admin, catalog.admin(admin)["etag"])
    revoked = verify_release(
        SignedRelease.model_validate(withdrawn["published"]["companion"]["envelope"]),
        ORIGIN,
        trust,
        product="octop-companion",
    )
    assert not revoked.enabled and revoked.revision == withdrawn["revision"]
    assert withdrawn["history"][0]["companion"]["version"] == "0.10.0"


def test_joint_import_requires_all_companion_platforms_with_digests() -> None:
    all_packages = [p.model_dump() for p in packages()] + companion_packages()
    raw = {
        "tag_name": TAG,
        "target_commitish": "b" * 40,
        "assets": [
            {
                "name": p["filename"],
                "size": p["size"],
                "browser_download_url": p["url"],
                "digest": "sha256:" + str(p["sha256"]),
            }
            for p in all_packages
        ],
    }
    assert companion_metadata(raw)["version"] == "0.10.0"  # type: ignore[index]
    raw["assets"].pop()
    with pytest.raises(OctopError):
        companion_metadata(raw)
    raw["assets"] = raw["assets"][:3]
    assert companion_metadata(raw) is None


def test_signer_stays_private_and_is_stable(
    company: tuple[ClientUpdateCatalog, User, dict[str, dict[str, str]]],
) -> None:
    catalog, _, trust = company
    assert initialize_signer(catalog.server.services, ORIGIN)["authorities"] == trust
    assert b'"private"' not in catalog.secrets.get("enterprise.client_updates.signer.v1")
    assert not any("private" in key for key in trust[ORIGIN])


def test_signed_release_round_trip_and_tamper_detection(
    company: tuple[ClientUpdateCatalog, User, dict[str, dict[str, str]]],
) -> None:
    envelope, release = publish(company)
    trust = company[2]
    assert verify_release(envelope, ORIGIN, trust) == release
    forged = json.loads(base64.b64decode(envelope.payload))
    forged["version"] = "1.0.3b3.post2099010101"
    with pytest.raises(OctopError):
        verify_release(
            envelope.model_copy(update={"payload": base64.b64encode(canonical(forged)).decode()}),
            ORIGIN,
            trust,
        )
    with pytest.raises(OctopError):
        verify_release(envelope, "https://other.example", trust)
    with pytest.raises(OctopError):
        verify_release(envelope.model_copy(update={"key_id": "0" * 16}), ORIGIN, trust)


def test_member_and_device_cannot_publish(
    company: tuple[ClientUpdateCatalog, User, dict[str, dict[str, str]]],
) -> None:
    catalog, admin, _ = company
    for user in [
        replace(admin, role="user"),
        MobileUser(id=1, username="device", role="admin", display_name="", locale="zh"),
    ]:
        with pytest.raises(OctopError):
            catalog.admin(user)


def test_withdraw_is_signed_and_does_not_delete_history(
    company: tuple[ClientUpdateCatalog, User, dict[str, dict[str, str]]],
) -> None:
    catalog, admin, trust = company
    _, published = publish(company)
    result = catalog.withdraw(admin, catalog.admin(admin)["etag"])
    release = verify_release(
        SignedRelease.model_validate(result["published"]["envelope"]), ORIGIN, trust
    )
    assert not release.enabled and release.revision > published.revision
    assert len(result["history"]) == 1


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/a",
        "https://evil.example/a",
        "https://github.com.evil.example/a",
        "https://user:pw@github.com/a",
        "https://github.com:8080/a",
    ],
)
def test_download_host_rejects_unsafe_destinations(url: str) -> None:
    assert not github_download_host(url)


def test_release_rejects_incomplete_platforms_and_arbitrary_urls() -> None:
    release = {
        "authority": ORIGIN,
        "revision": 1,
        "version": VERSION,
        "tag": TAG,
        "source_commit": "b" * 40,
        "published_at": 1,
        "packages": packages(),
    }
    with pytest.raises(ValidationError):
        ClientRelease(**{**release, "packages": packages()[:2]})
    altered = packages()
    altered[0] = altered[0].model_copy(update={"url": "https://evil.example/installer.zip"})
    with pytest.raises(ValidationError):
        ClientRelease(**{**release, "packages": altered})


def test_repository_asset_import_requires_complete_bytes_and_digests() -> None:
    raw = {
        "tag_name": TAG,
        "target_commitish": "b" * 40,
        "assets": [
            {
                "name": p.filename,
                "size": p.size,
                "browser_download_url": p.url,
                "digest": "sha256:" + p.sha256,
            }
            for p in packages()
        ],
    }
    assert package_metadata(raw)[1] == VERSION
    raw["assets"][0]["digest"] = None  # type: ignore[index]
    with pytest.raises(OctopError):
        package_metadata(raw)


def test_task_gate_prevents_new_work_until_released() -> None:
    from octop.infra.agents.manager import AgentManager

    manager = AgentManager.__new__(AgentManager)
    manager._active_invocations = {}
    manager._invocation_waiters = {}
    manager._runtime_update_holds = {}
    manager._history_backfills = {}
    manager._reclaim_holds = {}
    assert manager.try_begin_application_update()
    assert not manager.try_begin_application_update()
    manager.end_application_update()
    manager._active_invocations["expert"] = 1
    assert not manager.try_begin_application_update()


@pytest.mark.asyncio
async def test_gate_rejects_a_turn_before_incrementing_activity() -> None:
    from octop.infra.agents.manager import AgentManager

    manager = AgentManager.__new__(AgentManager)
    manager._application_update_gate = True
    manager._active_invocations = {}
    with pytest.raises(OctopError) as error:
        await manager._begin_invocation("expert", "thread")
    assert error.value.code.value == "CLIENT_UPDATE_IN_PROGRESS"
    assert manager._active_invocations == {}
