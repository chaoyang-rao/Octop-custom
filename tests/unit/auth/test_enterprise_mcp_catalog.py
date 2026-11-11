"""Credential-free catalogue publication, immutable versions, and employee filtering."""

import asyncio
import json
import secrets
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from octop.api.deps import current_user, get_server
from octop.api.routers.enterprise_mcp_admin import router
from octop.config import OctopConfig
from octop.infra.auth.enterprise import EnterpriseCenter, record_company_identity
from octop.infra.auth.sso.crypto import encrypt_secret
from octop.infra.connectors.enterprise_catalog import (
    CATALOG_KEY,
    EnterpriseMcpCatalog,
    build_snapshot,
    entry_fingerprint,
    validate_entries,
    validate_snapshot,
)
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import build_shared_services
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.mobile_access.access import MobileUser
from octop.infra.users.identity import Role, User
from octop.infra.users.manager import UserManager
from octop.infra.utils.paths import PathLayout


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    monkeypatch.setenv("OCTOP_HOME", str(tmp_path))
    paths = PathLayout(tmp_path)
    paths.ensure_root()
    pool = SqlitePool(paths.db)
    run_migrations(pool)
    config = OctopConfig(enterprise_center_enabled=True)
    services = build_shared_services(db=pool, paths=paths, config=config)
    services.secret_repo.get_or_create("jwt", lambda: secrets.token_bytes(32))
    server = SimpleNamespace(services=services, user_manager=UserManager(services), config=config)
    provider = services.sso_repo.upsert_by_kind(
        "feishu",
        enabled=True,
        display_name="Company",
        issuer="",
        client_id="company-app",
        client_secret_enc=encrypt_secret(services.secret_repo, "synthetic-secret"),
        scopes="",
        dashboard_origin=None,
    )
    services.settings_repo.set("enterprise.tenant_key", "company-tenant")

    async def employee(subject, admin=False):
        user = await server.user_manager.resolve_or_create_sso_user(
            provider_id=provider.id, subject=subject, claims={"name": subject}
        )
        record_company_identity(services, user.id, provider.client_id, subject, "company-tenant")
        if admin:
            await server.user_manager.set_role(user.username, Role.ADMIN)
            user = replace(user, role=Role.ADMIN)
        return user

    admin = asyncio.run(employee("publisher", admin=True))
    alice = asyncio.run(employee("alice"))
    bob = asyncio.run(employee("bob"))
    yield SimpleNamespace(
        server=server, service=EnterpriseMcpCatalog(server), admin=admin, alice=alice, bob=bob
    )
    pool.close()


def entry(entry_id="quality", **changes):
    return {
        "entry_id": entry_id,
        "display_name": "Quality",
        "description": "Read only",
        "url": "https://quality.example/mcp",
        "auth_kind": "bearer",
        "enabled": True,
        "allowed_subjects": [],
        **changes,
    }


def publish(catalog, entries):
    admin = catalog.service.get_admin(catalog.admin)
    draft = catalog.service.save_draft(catalog.admin, entries, admin.etag)
    return catalog.service.publish(catalog.admin, draft.etag)


def test_draft_is_not_visible_until_publish_and_history_remains_immutable(catalog):
    initial = catalog.service.get_admin(catalog.admin)
    assert initial.published.revision == 0
    assert initial.published.entries == []
    draft = catalog.service.save_draft(catalog.admin, [entry()], initial.etag)
    assert catalog.service.snapshot_for(catalog.alice).entries == []
    first = catalog.service.publish(catalog.admin, draft.etag)
    original = first.published.model_dump()
    second = publish(catalog, [entry(url="https://quality.example/new-mcp")])
    rolled_back = catalog.service.rollback(catalog.admin, 1, second.etag)
    assert rolled_back.published.revision == 3
    assert rolled_back.published.entries[0].url == original["entries"][0]["url"]
    assert rolled_back.draft.entries[0].url == "https://quality.example/new-mcp"
    stored = json.loads(catalog.server.services.settings_repo.get(CATALOG_KEY))
    assert stored["history"][0]["snapshot"] == original
    assert [item.revision for item in rolled_back.history] == [1, 2, 3]
    assert all(item.published_by == catalog.admin.username for item in rolled_back.history)


def test_member_scope_is_filtered_but_disabled_entries_and_own_credentials_are_not_erased(catalog):
    subject = EnterpriseCenter(catalog.server).require_employee(catalog.alice)
    published = publish(
        catalog,
        [entry("available-to-all", enabled=False), entry("alice-only", allowed_subjects=[subject])],
    )
    alice = catalog.service.snapshot_for(catalog.alice)
    bob = catalog.service.snapshot_for(catalog.bob)
    assert alice.revision == bob.revision == published.published.revision
    assert [item.entry_id for item in alice.entries] == ["alice-only", "available-to-all"]
    assert [item.entry_id for item in bob.entries] == ["available-to-all"]
    assert bob.entries[0].enabled is False
    assert alice.entries[0].allowed_subjects == []
    assert alice.checksum != bob.checksum
    assert validate_snapshot(alice.model_dump()).checksum == alice.checksum


def test_non_admin_and_device_grants_cannot_manage_catalogue(catalog):
    device = MobileUser(**catalog.admin.__dict__, device_id="device", device_scopes=("enterprise",))
    state = catalog.service.get_admin(catalog.admin)
    for user in [catalog.alice, device]:
        operations = [
            lambda user=user: catalog.service.get_admin(user),
            lambda user=user: catalog.service.save_draft(user, [entry()], state.etag),
            lambda user=user: catalog.service.publish(user, state.etag),
            lambda user=user: catalog.service.rollback(user, 1, state.etag),
        ]
        for operation in operations:
            with pytest.raises(OctopError) as failure:
                operation()
            assert failure.value.code == ErrorCode.ENTERPRISE_ACCESS_DENIED
    outsider = User(999, "outsider", Role.USER, "Outsider")
    with pytest.raises(OctopError):
        catalog.service.snapshot_for(outsider)
    assert catalog.server.services.settings_repo.get(CATALOG_KEY) is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("headers", {"Authorization": "synthetic-personal-token"}),
        ("env", {"API_KEY": "synthetic-personal-token"}),
        ("command", "ssh"),
        ("args", ["private-host"]),
        ("oauth", {"access_token": "synthetic-personal-token"}),
        ("password", "synthetic-personal-token"),
    ],
)
def test_secret_and_executable_fields_are_rejected_without_storage(catalog, field, value):
    state = catalog.service.get_admin(catalog.admin)
    with pytest.raises(OctopError) as failure:
        catalog.service.save_draft(catalog.admin, [entry(**{field: value})], state.etag)
    assert failure.value.code == ErrorCode.ENTERPRISE_MCP_CATALOG_INVALID
    assert "synthetic-personal-token" not in str(failure.value)
    assert catalog.server.services.settings_repo.get(CATALOG_KEY) is None


@pytest.mark.parametrize(
    "url",
    [
        "http://quality.example/mcp",
        "file:///private/file",
        "https://localhost/mcp",
        "https://localhost./mcp",
        "https://ｌｏｃａｌｈｏｓｔ/mcp",
        "https://１２７.０.０.１/mcp",
        "https://local\u200bhost/mcp",
        "https://localhost\u3002/mcp",
        "https://service.localhost/mcp",
        "https://127.0.0.1/mcp",
        "https://[::1]/mcp",
        "https://[::]/mcp",
        "https://[::ffff:127.0.0.1]/mcp",
        "https://0.0.0.0/mcp",
        "https://169.254.169.254/mcp",
        "https://127.1/mcp",
        "https://2130706433/mcp",
        "https://0x7f000001/mcp",
        "https://0177.0.0.1/mcp",
        "https://user:pass@quality.example/mcp",
        "https://@quality.example/mcp",
        "https://quality.example/mcp?token=secret",
        "https://quality.example/mcp?",
        "https://quality.example/mcp#token",
        "https://quality.example/mcp#",
        "https://quality.example:70000/mcp",
        "https://quality.example\\localhost/mcp",
    ],
)
def test_malicious_and_machine_local_catalogue_urls_are_rejected(url):
    with pytest.raises(OctopError):
        validate_entries([entry(url=url)])


def test_private_company_https_and_fingerprints_bind_only_connection_identity():
    original = validate_entries([entry(url="https://10.10.0.5:8443/mcp")])[0]
    assert entry_fingerprint(original) == entry_fingerprint(
        entry(url=original.url, display_name="Renamed", enabled=False)
    )
    assert entry_fingerprint(original) != entry_fingerprint(
        entry(url="https://quality.example/mcp")
    )
    assert entry_fingerprint(original) != entry_fingerprint(
        entry(url=original.url, auth_kind="basic")
    )


def test_duplicate_entries_and_tampered_or_unsupported_snapshots_are_rejected():
    with pytest.raises(OctopError):
        validate_entries([entry(), entry()])
    raw = build_snapshot(revision=1, published_at=1, entries=[entry()]).model_dump()
    assert validate_snapshot(raw).revision == 1
    for patch in [
        {"schema_version": 2},
        {"revision": -1},
        {"revision": True},
        {"checksum": "0" * 64},
        {"password": "secret"},
        {"entries": [entry(), entry()]},
    ]:
        with pytest.raises(OctopError):
            validate_snapshot({**raw, **patch})


def test_concurrent_publication_has_one_winner_and_stale_drafts_do_not_overwrite(catalog):
    state = catalog.service.get_admin(catalog.admin)
    draft = catalog.service.save_draft(catalog.admin, [entry()], state.etag)
    barrier = Barrier(2)

    def write():
        barrier.wait(timeout=5)
        try:
            return catalog.service.publish(catalog.admin, draft.etag)
        except OctopError as failure:
            return failure

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: write(), range(2)))
    assert sum(isinstance(result, OctopError) for result in results) == 1
    failure = next(result for result in results if isinstance(result, OctopError))
    assert failure.code == ErrorCode.ENTERPRISE_MCP_CATALOG_CONFLICT
    published = catalog.service.get_admin(catalog.admin)
    assert published.published.revision == 1
    assert len(published.history) == 1
    with pytest.raises(OctopError) as stale:
        catalog.service.save_draft(catalog.admin, [entry("other")], draft.etag)
    assert stale.value.status == 409
    assert catalog.service.get_admin(catalog.admin).draft.entries[0].entry_id == "quality"


async def test_api_returns_typed_state_and_never_echoes_rejected_credentials(catalog):
    app = FastAPI()
    app.include_router(router, prefix="/api")
    identity = {"user": catalog.admin}
    app.dependency_overrides[current_user] = lambda: identity["user"]
    app.dependency_overrides[get_server] = lambda: catalog.server

    @app.exception_handler(OctopError)
    async def handle_error(request, error):
        return JSONResponse(status_code=error.status, content=error.to_envelope())

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://center.example"
    ) as client:
        state = await client.get("/api/enterprise/mcp/admin/catalog")
        assert state.status_code == 200
        assert state.headers["Cache-Control"] == "no-store"
        body = {
            "entries": [entry(headers={"Authorization": "never-echo-this-token"})],
            "expected_etag": state.json()["etag"],
        }
        rejected = await client.put("/api/enterprise/mcp/admin/draft", json=body)
        assert rejected.status_code == 400
        assert "never-echo-this-token" not in rejected.text
        body["entries"] = [entry()]
        saved = await client.put("/api/enterprise/mcp/admin/draft", json=body)
        assert saved.status_code == 200
        published = await client.post(
            "/api/enterprise/mcp/admin/publish", json={"expected_etag": saved.json()["etag"]}
        )
        assert published.status_code == 200
        identity["user"] = catalog.alice
        visible = await client.get("/api/enterprise/mcp/catalog")
        assert visible.status_code == 200
        assert visible.json()["entries"][0]["entry_id"] == "quality"
        denied = await client.post(
            "/api/enterprise/mcp/admin/publish", json={"expected_etag": published.json()["etag"]}
        )
        assert denied.status_code == 403


async def test_admin_member_picker_excludes_disabled_and_non_company_accounts(catalog):
    server = catalog.server
    local_id = server.services.user_repo.create(username="local-only", role=Role.USER)
    server.user_manager.register_cached_user(User(local_id, "local-only", Role.USER, "Local"))
    server.services.user_repo.set_disabled(catalog.bob.id, True)
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[current_user] = lambda: catalog.admin
    app.dependency_overrides[get_server] = lambda: server
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://center.example"
    ) as client:
        response = await client.get("/api/enterprise/mcp/admin/members")
    assert response.status_code == 200
    members = response.json()
    assert {item["display_name"] for item in members} == {catalog.admin.label, catalog.alice.label}
    assert all(set(item) == {"subject", "display_name"} for item in members)
    assert all(len(item["subject"]) == 64 for item in members)
    assert "synthetic-secret" not in response.text
    with pytest.raises(OctopError):
        catalog.service.members(catalog.alice)
