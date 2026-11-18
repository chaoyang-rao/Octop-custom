"""Local update consent, identity isolation, revocation and download integrity."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from octop.infra.client_updates.models import verify_release
from octop.infra.client_updates.node import ClientUpdateNode
from octop.infra.errors import ErrorCode, OctopError
from tests.unit.client_updates.test_protocol import ORIGIN, publish
from tests.unit.client_updates.test_protocol import company as company


@pytest.fixture
def node(company, monkeypatch, tmp_path):
    catalog, user, trust = company
    envelope, release = publish(company)
    server = catalog.server
    server.paths = SimpleNamespace(root=tmp_path)
    server.services.db = SimpleNamespace(dialect="sqlite")
    server.services.config = SimpleNamespace(
        database=SimpleNamespace(
            driver="sqlite", resolve_sqlite_path=lambda root: Path(root) / "octop.db"
        )
    )
    server.services.agent_repo = SimpleNamespace(list_all=lambda: [])
    registry = SimpleNamespace(
        try_begin_application_update=lambda: True,
        end_application_update=lambda: None,
        is_agent_active=lambda agent: False,
    )
    server.app_runtime = SimpleNamespace(agent_registry=registry)
    credentials = {"subject": "a" * 64, "token": "local-test-grant"}
    client = SimpleNamespace(
        authority=ORIGIN,
        authorize=AsyncMock(),
        _state=lambda _: credentials,
        _remote=AsyncMock(
            return_value={"revision": release.revision, "envelope": envelope.model_dump()}
        ),
    )
    monkeypatch.setattr("octop.infra.client_updates.node.client_for", lambda _: client)
    monkeypatch.setattr(
        "octop.infra.client_updates.node.verify_release",
        lambda value, authority: verify_release(value, authority, trust),
    )
    monkeypatch.setenv("OCTOP_DESKTOP_CLIENT_VERSION", "1.0.3b3.post2026111703")
    monkeypatch.setenv("OCTOP_DESKTOP_UPDATER_PROTOCOL", "1")
    monkeypatch.setenv("OCTOP_DESKTOP_PROGRAM_ROOT", str(tmp_path / "program"))
    manager = ClientUpdateNode(server, native_platform="darwin-arm64")
    return SimpleNamespace(
        manager=manager,
        user=user,
        client=client,
        credentials=credentials,
        envelope=envelope,
        release=release,
        server=server,
    )


async def saved_download(node):
    state, _ = await node.manager._fetch(node.user)
    identifier = "a" * 32
    value = {
        "schema_version": 1,
        "id": identifier,
        "owner_user_id": node.user.id,
        "subject": state["subject"],
        "platform": "darwin-arm64",
        "current_version": node.manager.native_version,
        "target_version": node.release.version,
        "revision": node.release.revision,
        "phase": "downloaded",
        "downloaded_bytes": 4,
        "total_bytes": 4,
        "envelope": node.envelope.model_dump(),
        "error_code": None,
    }
    node.manager._write_job(value)
    node.manager._change(node.user.id, {"job_id": identifier})
    return value


async def test_idle_consent_owns_only_its_job(node):
    value = await saved_download(node)
    with pytest.raises(OctopError):
        await node.manager.prepare_install(replace(node.user, id=2), value["id"])
    node.server._client_update_mutations = 1
    with pytest.raises(OctopError) as error:
        await node.manager.prepare_install(node.user, value["id"])
    assert error.value.code == ErrorCode.CLIENT_UPDATE_BUSY
    assert node.manager._job(value["id"])["phase"] == "waiting_idle"
    node.server._client_update_mutations = 0
    result = await node.manager.prepare_install(node.user, value["id"])
    assert result == {"job_id": value["id"]}
    assert node.manager.applying
    assert node.manager._job(value["id"])["expires_at"] > 0
    await node.manager.abort_install(node.user, value["id"])
    assert not node.manager.applying


async def test_identity_switch_cannot_reuse_previous_consent(node):
    value = await saved_download(node)
    node.credentials["subject"] = "b" * 64
    with pytest.raises(OctopError) as error:
        await node.manager.prepare_install(node.user, value["id"])
    assert error.value.code == ErrorCode.CLIENT_UPDATE_CONFLICT
    assert not node.manager.applying
    assert node.manager._state(node.user.id)["job_id"] is None


async def test_withdrawn_publication_cannot_install_downloaded_bytes(node):
    value = await saved_download(node)
    node.client._remote.return_value = {"revision": node.release.revision + 1, "envelope": None}
    with pytest.raises(OctopError) as error:
        await node.manager.prepare_install(node.user, value["id"])
    assert error.value.code == ErrorCode.CLIENT_UPDATE_CONFLICT
    assert not node.manager.applying


@pytest.mark.parametrize("mode", ["valid", "wrong-hash", "oversized", "unsafe-redirect", "revoked"])
async def test_download_integrity_and_revocation(node, monkeypatch, mode):
    value = await saved_download(node)
    value["phase"] = "downloading"
    node.manager._write_job(value)
    content = b"payload" if mode == "oversized" else b"data"
    original_client = httpx.AsyncClient

    async def request(_):
        if mode == "unsafe-redirect":
            return httpx.Response(302, headers={"location": "https://outside.example/payload"})
        return httpx.Response(200, content=content)

    monkeypatch.setattr(
        "octop.infra.client_updates.node.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(request), **kwargs),
    )
    node.manager.report = AsyncMock()
    if mode == "revoked":
        node.client._remote.return_value = {"revision": node.release.revision + 1, "envelope": None}
    expected = hashlib.sha256(b"data" if mode != "wrong-hash" else b"nope").hexdigest()
    url = next(p.url for p in node.release.packages if p.platform == "darwin-arm64")
    await node.manager._download(node.user, value, url, expected)
    directory = node.manager._directory(value["id"])
    assert not (directory / "payload.part").exists()
    assert (directory / "payload.zip").exists() == (mode == "valid")
    assert node.manager._job(value["id"])["phase"] == (
        "downloaded" if mode == "valid" else "failed"
    )


async def test_poll_cannot_replace_current_download_job(node):
    value = await saved_download(node)
    await asyncio.gather(*(node.manager._fetch(node.user) for _ in range(4)))
    assert node.manager._state(node.user.id)["job_id"] == value["id"]


def test_external_database_disables_automatic_replacement(node):
    node.server.services.config.database.driver = "postgresql"
    assert not ClientUpdateNode(node.server, native_platform="darwin-arm64").supported
