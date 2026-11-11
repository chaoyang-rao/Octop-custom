"""Company identity isolation, revocation and local execution admission."""

import asyncio
import json
import secrets
import time
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from octop.config import OctopConfig
from octop.infra.agents.manager import AgentManager
from octop.infra.auth import enterprise
from octop.infra.auth.enterprise import (
    EnterpriseCenter,
    EnterpriseClient,
    client_for,
    record_company_identity,
)
from octop.infra.auth.sso.crypto import encrypt_secret
from octop.infra.connectors.accounts.actor import authenticated_vault_actor
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import build_shared_services
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.mobile_access.access import authorize_device_path
from octop.infra.users.identity import Role
from octop.infra.users.manager import UserManager
from octop.infra.utils.paths import PathLayout


@pytest.fixture
def servers(tmp_path, monkeypatch):
    monkeypatch.setenv("OCTOP_HOME", str(tmp_path))
    pools = []

    def make(name, config):
        paths = PathLayout(tmp_path / name)
        paths.ensure_root()
        pool = SqlitePool(paths.db)
        pools.append(pool)
        run_migrations(pool)
        services = build_shared_services(db=pool, paths=paths, config=config)
        services.secret_repo.get_or_create("jwt", lambda: secrets.token_bytes(32))
        return SimpleNamespace(
            services=services,
            user_manager=UserManager(services),
            paths=paths,
            config=config,
            database_bound=True,
            _started=True,
            app_runtime=None,
            _started_at=0,
        )

    yield make
    for pool in pools:
        pool.close()


async def employee(server, subject="employee", name="Colleague"):
    provider = server.services.sso_repo.upsert_by_kind(
        "feishu",
        enabled=True,
        display_name="Company",
        issuer="",
        client_id="company-app",
        client_secret_enc=encrypt_secret(server.services.secret_repo, "test-secret"),
        scopes="",
        dashboard_origin=None,
    )
    user = await server.user_manager.resolve_or_create_sso_user(
        provider_id=provider.id, subject=subject, claims={"name": name}
    )
    server.services.settings_repo.set_if_missing("enterprise.tenant_key", "company-tenant")
    record_company_identity(server.services, user.id, provider.client_id, subject, "company-tenant")
    await server.user_manager.set_permissions(user.username, ["experts", "terminal"])
    return user


async def approved(center, user):
    challenge = await center.begin("My computer", "office")
    assert (await center.exchange(challenge["pairing_secret"], "office"))["status"] == "pending"
    await center.approve(user, challenge["user_code"])
    result = await center.exchange(challenge["pairing_secret"], "office")
    return challenge, result


def connect_transport(monkeypatch, center):
    original = httpx.AsyncClient
    requests = []

    async def handler(request):
        requests.append(request)
        body = json.loads(request.content) if request.content else {}
        try:
            if request.url.path.endswith("/pairings/exchange"):
                result = await center.exchange(body["pairing_secret"], "office")
            elif request.url.path.endswith("/pairings"):
                result = await center.begin(body["name"], "office")
            elif request.url.path.endswith("/session/revoke"):
                await center.revoke(request.headers["Authorization"][7:])
                return httpx.Response(204)
            else:
                result = center.profile(request.headers["Authorization"][7:])
            return httpx.Response(200, json=result)
        except OctopError as exc:
            return httpx.Response(exc.status, json=exc.to_envelope())

    def factory(*args, **kwargs):
        kwargs.setdefault("transport", httpx.MockTransport(handler))
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    return requests


@pytest.fixture
def clock(monkeypatch):
    value = SimpleNamespace(now=time.time(), mono=time.monotonic())
    monkeypatch.setattr(
        enterprise, "time", SimpleNamespace(time=lambda: value.now, monotonic=lambda: value.mono)
    )

    def advance(seconds):
        value.now += seconds
        value.mono += seconds

    return advance


@pytest.mark.asyncio
async def test_enterprise_pairing_is_not_a_mobile_or_management_credential(servers):
    server = servers("center", OctopConfig(enterprise_center_enabled=True))
    user = await employee(server)
    center = EnterpriseCenter(server)
    challenge = await center.begin("Office laptop", "office")
    with pytest.raises(OctopError):
        await center.devices.approve_pairing(
            user_id=user.id, code=challenge["user_code"], scopes=["chat"]
        )
    with pytest.raises(OctopError):
        await center.devices.exchange_pairing(
            pairing_secret=challenge["pairing_secret"], network_key="office"
        )
    preview = await center.inspect(user, challenge["user_code"])
    assert preview["name"] == "Office laptop"
    await center.approve(user, challenge["user_code"])
    result = await center.exchange(challenge["pairing_secret"], "office")
    with pytest.raises(OctopError):
        await center.exchange(challenge["pairing_secret"], "office")
    session = center.devices.authenticate(result["access_token"])
    authorize_device_path(session, "/api/enterprise/session", "GET")
    for path in ["/api/auth/me", "/api/agents", "/api/terminal/ws", "/api/users"]:
        with pytest.raises(OctopError):
            authorize_device_path(session, path, "GET")
    stored = server.services.settings_repo.get(f"mobile_access.devices.{user.id}")
    assert result["access_token"] not in stored
    assert challenge["pairing_secret"] not in (
        server.services.settings_repo.get("mobile_access.pending") or ""
    )


@pytest.mark.asyncio
async def test_center_requires_feishu_even_for_a_password_admin(servers):
    server = servers("center", OctopConfig(enterprise_center_enabled=True))
    admin = await server.user_manager.create(
        username="admin", password="Safe-test-password!123", role=Role.ADMIN
    )
    center = EnterpriseCenter(server)
    request = await center.begin("Computer", "office")
    with pytest.raises(OctopError) as exc:
        await center.approve(admin, request["user_code"])
    assert exc.value.code is ErrorCode.ENTERPRISE_FEISHU_REQUIRED


@pytest.mark.asyncio
async def test_company_identity_survives_restart_without_exporting_center_credentials(
    servers, monkeypatch, clock
):
    server = servers("center", OctopConfig(enterprise_center_enabled=True))
    user = await employee(server)
    await server.user_manager.set_role(user.username, Role.ADMIN)
    center = EnterpriseCenter(server)
    requests = connect_transport(monkeypatch, center)
    node = servers("node", OctopConfig(enterprise_authority_url="https://company.example"))
    client = client_for(node)
    challenge = await client.begin("My local computer")
    assert "pairing_secret" not in challenge
    assert challenge["verification_uri"] == "https://company.example/enterprise/approve"
    await center.approve(user, challenge["user_code"])
    clock(4)
    result, local = await client.poll(challenge["login_id"])
    assert result == {"status": "approved"}
    assert not local.is_admin
    state = client._state(local.id)
    assert state["token"].encode() not in node.services.secret_repo.get(
        f"enterprise.identity.{local.id}"
    )
    assert state["subject"] != str(user.id)
    restarted = EnterpriseClient(node)
    assert not (await restarted.authorize(local)).is_admin
    assert (await restarted.authorize(local)).permissions
    assert {request.url.path for request in requests} <= {
        "/api/enterprise/pairings",
        "/api/enterprise/pairings/exchange",
        "/api/enterprise/session",
    }
    assert all(request.url.host == "company.example" for request in requests)


@pytest.mark.asyncio
async def test_approved_company_mode_survives_an_update_without_losing_local_configuration(
    servers, monkeypatch
):
    from octop.config import load_config

    center_server = servers("center", OctopConfig(enterprise_center_enabled=True))
    worker = await employee(center_server)
    center = EnterpriseCenter(center_server)
    connect_transport(monkeypatch, center)
    node = servers("node", OctopConfig(enterprise_authority_url="https://company.example"))
    previous = {"default_timezone": "Asia/Shanghai", "future_setting": {"keep": True}}
    node.paths.config.write_text(json.dumps(previous), encoding="utf-8")
    client = client_for(node)
    challenge = await client.begin("Computer")
    assert json.loads(node.paths.config.read_text()) == previous
    await center.approve(worker, challenge["user_code"])
    _, local = await client.poll(challenge["login_id"])
    assert json.loads(node.paths.config.read_text()) == {
        **previous,
        "enterprise_authority_url": "https://company.example",
    }
    monkeypatch.delenv("OCTOP_ENTERPRISE_AUTHORITY_URL", raising=False)
    upgraded = servers("node", load_config(node.paths.config))
    assert not (await client_for(upgraded).authorize(local)).is_admin
    await client.logout(local.id)
    assert load_config(node.paths.config).enterprise_authority_url == "https://company.example"


@pytest.mark.asyncio
async def test_revocation_and_permission_updates_reach_local_execution(servers, monkeypatch, clock):
    server = servers("center", OctopConfig(enterprise_center_enabled=True))
    user = await employee(server)
    center = EnterpriseCenter(server)
    connect_transport(monkeypatch, center)
    node = servers("node", OctopConfig(enterprise_authority_url="https://company.example"))
    client = client_for(node)
    challenge = await client.begin("Laptop")
    await center.approve(user, challenge["user_code"])
    _, local = await client.poll(challenge["login_id"])
    assert "terminal" in (await client.authorize(local)).permissions
    await server.user_manager.set_permissions(user.username, ["experts"])
    clock(31)
    assert (await client.authorize(local)).permissions == ["experts"]
    token = client._state(local.id)["token"]
    await center.revoke(token)
    # Task admission must revalidate even while the UI's positive cache is fresh.
    manager = AgentManager.__new__(AgentManager)
    manager._config = node.config
    manager.enterprise_authorizer = client.authorize_id
    manager.get_row = lambda _: SimpleNamespace(user_id=local.id)
    manager._harness_manager = SimpleNamespace(stream=Mock(), call=AsyncMock(), resume_hitl=Mock())
    for operation in [
        manager.call("expert", {}),
        anext(manager.stream("expert", {})),
        anext(manager.resume_hitl("expert", "thread", [])),
    ]:
        with pytest.raises(OctopError):
            await operation
    manager._harness_manager.call.assert_not_called()
    manager._harness_manager.stream.assert_not_called()
    manager._harness_manager.resume_hitl.assert_not_called()


@pytest.mark.asyncio
async def test_disabled_account_cannot_keep_a_device_grant(servers):
    server = servers("center", OctopConfig(enterprise_center_enabled=True))
    user = await employee(server)
    center = EnterpriseCenter(server)
    _, grant = await approved(center, user)
    server.services.user_repo.set_disabled(user.id, True)
    with pytest.raises(OctopError):
        center.profile(grant["access_token"])


@pytest.mark.asyncio
async def test_switching_authority_does_not_reuse_another_company_local_identity(
    servers, monkeypatch
):
    center_server = servers("center", OctopConfig(enterprise_center_enabled=True))
    user = await employee(center_server)
    center = EnterpriseCenter(center_server)
    connect_transport(monkeypatch, center)
    node = servers("node", OctopConfig(enterprise_authority_url="https://one.example"))
    first = client_for(node)
    challenge = await first.begin("Computer")
    await center.approve(user, challenge["user_code"])
    _, previous_user = await first.poll(challenge["login_id"])
    moved = servers("node", replace(node.config, enterprise_authority_url="https://two.example"))
    second = client_for(moved)
    with pytest.raises(OctopError) as exc:
        await second.authorize(previous_user)
    assert exc.value.code is ErrorCode.ENTERPRISE_LOGIN_REQUIRED
    challenge = await second.begin("Computer")
    await center.approve(user, challenge["user_code"])
    _, current_user = await second.poll(challenge["login_id"])
    assert current_user.id != previous_user.id
    assert moved.services.user_repo.get(previous_user.id) is not None


@pytest.mark.asyncio
async def test_real_http_pairing_and_first_node_login_do_not_expose_center_token(
    servers, monkeypatch
):
    from octop.api.app import build_app
    from octop.infra.auth.mfa.service import MfaService

    original_client = httpx.AsyncClient
    center_server = servers("center", OctopConfig(enterprise_center_enabled=True))
    user = await employee(center_server)
    web_token, _ = MfaService(center_server.services).mint_access_token(user)
    center = EnterpriseCenter(center_server)
    node = servers("node", OctopConfig(enterprise_authority_url="https://company.example"))
    connect_transport(monkeypatch, center)
    async with original_client(
        transport=httpx.ASGITransport(app=build_app(node)), base_url="http://127.0.0.1"
    ) as local:
        status = await local.get("/api/setup/status")
        assert not status.json()["setup_required"] and status.json()["enterprise_login"]
        begin = await local.post("/api/auth/enterprise/start", json={"name": "My computer"})
        assert begin.status_code == 200
        challenge = begin.json()
        assert "pairing_secret" not in challenge
        async with original_client(
            transport=httpx.ASGITransport(app=build_app(center_server)),
            base_url="https://company.example",
        ) as authority:
            response = await authority.post(
                "/api/enterprise/pairings/approve",
                json={"code": challenge["user_code"]},
                headers={"Authorization": "Bearer " + web_token},
            )
            assert response.status_code == 200
        response = await local.post(
            "/api/auth/enterprise/poll", json={"login_id": challenge["login_id"]}
        )
        assert response.status_code == 200
        result = response.json()
        assert result["status"] == "approved" and result["user"]["role"] != "admin"
        assert "octop_mobile_" not in json.dumps(result)
        assert (
            await local.get(
                "/api/auth/me", headers={"Authorization": "Bearer " + result["access_token"]}
            )
        ).status_code == 200


@pytest.mark.asyncio
async def test_network_failure_fails_closed_and_logout_clears_the_local_secret(
    servers, monkeypatch, clock
):
    server = servers("center", OctopConfig(enterprise_center_enabled=True))
    user = await employee(server)
    center = EnterpriseCenter(server)
    connect_transport(monkeypatch, center)
    node = servers("node", OctopConfig(enterprise_authority_url="https://company.example"))
    client = client_for(node)
    challenge = await client.begin("Computer")
    await center.approve(user, challenge["user_code"])
    _, local = await client.poll(challenge["login_id"])
    clock(31)
    original = httpx.AsyncClient

    async def unavailable(request):
        raise httpx.ConnectError("test network failure", request=request)

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(**(kwargs | {"transport": httpx.MockTransport(unavailable)})),
    )
    with pytest.raises(OctopError) as exc:
        await client.authorize(local)
    assert exc.value.code is ErrorCode.ENTERPRISE_UNAVAILABLE
    assert node.services.user_repo.get(local.id) is not None
    await client.logout(local.id)
    assert node.services.secret_repo.get(f"enterprise.identity.{local.id}") is None


def test_client_rejects_remote_plaintext_and_public_node_binding(servers):
    for config in [
        OctopConfig(enterprise_authority_url="http://company.example"),
        OctopConfig(enterprise_authority_url="https://company.example", bind_host="0.0.0.0"),
        OctopConfig(
            enterprise_authority_url="https://company.example", enterprise_center_enabled=True
        ),
    ]:
        with pytest.raises(ValueError):
            EnterpriseClient(
                servers(
                    "config-" + str(len(config.enterprise_authority_url)) + str(config.bind_host),
                    config,
                )
            )


@pytest.mark.asyncio
async def test_center_routes_do_not_expose_agent_file_or_terminal_execution(servers):
    from octop.api.app import build_app

    server = servers("center", OctopConfig(enterprise_center_enabled=True, enable_api_docs=True))
    app = build_app(server)
    paths = set(app.openapi()["paths"])
    assert "/api/enterprise/pairings" in paths
    assert "/api/auth/oauth/start" in paths
    assert "/api/users" in paths
    assert not any(
        path.startswith(
            (
                "/api/agents",
                "/api/terminal",
                "/api/browser",
                "/api/bridge",
                "/api/tasks",
                "/api/internal/mcp",
            )
        )
        for path in paths
    )


@pytest.mark.asyncio
async def test_center_rejects_expert_bootstrap_before_creating_a_user(servers):
    from octop.api.app import build_app
    from octop.infra.auth.mfa.service import MfaService

    server = servers("center", OctopConfig(enterprise_center_enabled=True))
    owner = await server.user_manager.create(
        username="owner", password="Safe-test-password!123", role=Role.ADMIN
    )
    token, _ = MfaService(server.services).mint_access_token(owner)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=build_app(server)), base_url="https://company.example"
    ) as http:
        response = await http.post(
            "/api/users",
            json={
                "username": "colleague",
                "password": "Safe-test-password!123",
                "create_default_expert": True,
            },
            headers={"Authorization": "Bearer " + token},
        )
    assert response.status_code == 403
    assert server.user_manager.count() == 1


@pytest.mark.asyncio
async def test_only_admin_can_pin_the_company_and_other_tenants_are_denied(servers):
    server = servers("center", OctopConfig(enterprise_center_enabled=True))
    with pytest.raises(OctopError):
        enterprise.verify_company_tenant(
            server.services, server.user_manager, {"tenant_key": "outside", "role": "admin"}, None
        )
    assert server.services.settings_repo.get("enterprise.tenant_key") is None
    admin = await server.user_manager.create(
        username="owner", password="Safe-test-password!123", role=Role.ADMIN
    )
    assert (
        enterprise.verify_company_tenant(
            server.services, server.user_manager, {"tenant_key": "company"}, admin.id
        )
        == "company"
    )
    with pytest.raises(OctopError) as exc:
        enterprise.verify_company_tenant(
            server.services, server.user_manager, {"tenant_key": "outside"}, admin.id
        )
    assert exc.value.code is ErrorCode.ENTERPRISE_ACCESS_DENIED
    assert server.services.settings_repo.get("enterprise.tenant_key") == "company"


@pytest.mark.asyncio
async def test_changing_the_feishu_app_requires_reverification(servers):
    server = servers("center", OctopConfig(enterprise_center_enabled=True))
    user = await employee(server)
    center = EnterpriseCenter(server)
    _, grant = await approved(center, user)
    provider = server.services.sso_repo.get_by_kind("feishu")
    server.services.sso_repo.upsert_by_kind(
        "feishu",
        enabled=True,
        display_name="Other",
        issuer="",
        client_id="another-app",
        client_secret_enc=provider.client_secret_enc,
        scopes="",
        dashboard_origin=None,
    )
    with pytest.raises(OctopError):
        center.profile(grant["access_token"])


@pytest.mark.asyncio
async def test_linking_keeps_personal_data_identity_without_inheriting_admin(servers, monkeypatch):
    from octop.api.app import build_app
    from octop.infra.auth.mfa.service import MfaService

    original_client = httpx.AsyncClient
    center_server = servers("center", OctopConfig(enterprise_center_enabled=True))
    worker = await employee(center_server)
    center = EnterpriseCenter(center_server)
    node = servers("node", OctopConfig(enterprise_authority_url="https://company.example"))
    personal = await node.user_manager.create(
        username="personal",
        password="Safe-test-password!123",
        role=Role.ADMIN,
        permissions=["browser"],
    )
    personal_token, _ = MfaService(node.services).mint_access_token(personal)
    original = node.services.user_repo.get(personal.id)
    connect_transport(monkeypatch, center)
    async with original_client(
        transport=httpx.ASGITransport(app=build_app(node)), base_url="http://127.0.0.1"
    ) as local:
        assert (
            await local.post(
                "/api/auth/enterprise/start", json={"name": "Computer", "bind_current": True}
            )
        ).status_code == 400
        challenge = (
            await local.post(
                "/api/auth/enterprise/start",
                json={"name": "Computer", "bind_current": True},
                headers={"Authorization": "Bearer " + personal_token},
            )
        ).json()
        await center.approve(worker, challenge["user_code"])
        response = await local.post(
            "/api/auth/enterprise/poll", json={"login_id": challenge["login_id"]}
        )
        assert response.status_code == 200
        assert response.json()["status"] == "confirm"
        assert not node.user_manager.list_sso_identities(personal.id)
        response = await local.post(
            "/api/auth/enterprise/poll", json={"login_id": challenge["login_id"], "confirmed": True}
        )
        result = response.json()
        assert result["user"]["id"] == personal.id
        assert result["user"]["role"] == "user"
        assert result["user"]["permissions"] == ["experts", "terminal"]
        stored = node.services.user_repo.get(personal.id)
        assert stored.role == original.role and stored.permissions == original.permissions
        assert (
            await local.post(
                "/api/setup/finish",
                json={},
                headers={"Authorization": "Bearer " + result["access_token"]},
            )
        ).status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["revoke", "permissions"])
@pytest.mark.parametrize("activity", ["receive", "send"])
async def test_first_frame_websocket_authorization_and_live_revocation(
    servers, monkeypatch, clock, change, activity
):
    from octop.api.deps import resolve_websocket_user
    from octop.api.middleware.enterprise import EnterpriseSocketMiddleware
    from octop.infra.auth.mfa.service import MfaService

    center_server = servers("center", OctopConfig(enterprise_center_enabled=True))
    worker = await employee(center_server)
    center = EnterpriseCenter(center_server)
    connect_transport(monkeypatch, center)
    node = servers("node", OctopConfig(enterprise_authority_url="https://company.example"))
    client = client_for(node)
    challenge = await client.begin("Computer")
    await center.approve(worker, challenge["user_code"])
    _, local = await client.poll(challenge["login_id"])
    await node.user_manager.set_role(local.username, Role.ADMIN)
    jwt, _ = MfaService(node.services).mint_access_token(local)
    incoming = asyncio.Queue()
    incoming.put_nowait({"type": "websocket.connect"})
    incoming.put_nowait({"type": "websocket.receive", "text": jwt})
    incoming.put_nowait({"type": "websocket.receive", "text": "next action"})
    outgoing = []

    async def handler(scope, receive, send):
        await receive()
        await send({"type": "websocket.accept"})
        frame = await receive()
        user = await resolve_websocket_user(node, frame["text"])
        assert not user.is_admin and user.permissions == ["experts", "terminal"]
        await send({"type": "websocket.send", "text": "authorized"})
        if change == "revoke":
            await center.revoke(client._state(user.id)["token"])
        else:
            await center_server.user_manager.set_permissions(worker.username, ["experts"])
        clock(31)
        if activity == "receive":
            assert (await receive())["type"] == "websocket.disconnect"
        else:
            await send({"type": "websocket.send", "text": "must not be sent"})

    async def send(message):
        outgoing.append(message)

    await EnterpriseSocketMiddleware(handler, server=node)(
        {"type": "websocket"}, incoming.get, send
    )
    assert outgoing[-1]["type"] == "websocket.close" and outgoing[-1]["code"] == 4403
    assert not any(item.get("text") == "must not be sent" for item in outgoing)


@pytest.mark.asyncio
async def test_logout_during_inflight_authorization_cannot_restore_cached_access(
    servers, monkeypatch
):
    center_server = servers("center", OctopConfig(enterprise_center_enabled=True))
    worker = await employee(center_server)
    center = EnterpriseCenter(center_server)
    connect_transport(monkeypatch, center)
    node = servers("node", OctopConfig(enterprise_authority_url="https://company.example"))
    client = client_for(node)
    challenge = await client.begin("Computer")
    await center.approve(worker, challenge["user_code"])
    _, local = await client.poll(challenge["login_id"])
    started, release = asyncio.Event(), asyncio.Event()
    original = client._remote

    async def remote(method, path, **kwargs):
        if method == "GET":
            started.set()
            await asyncio.wait_for(release.wait(), 2)
        return await original(method, path, **kwargs)

    monkeypatch.setattr(client, "_remote", remote)
    authorization = asyncio.create_task(client.authorize(local, force=True))
    await asyncio.wait_for(started.wait(), 2)
    logout = asyncio.create_task(client.logout(local.id))
    release.set()
    await asyncio.gather(authorization, logout)
    assert local.id not in client._cache
    with pytest.raises(OctopError) as exc:
        await client.authorize(local)
    assert exc.value.code is ErrorCode.ENTERPRISE_LOGIN_REQUIRED


@pytest.mark.asyncio
async def test_shared_expert_enterprise_admission_uses_trusted_actor():
    manager = object.__new__(AgentManager)
    manager._config = OctopConfig()
    manager.enterprise_authorizer = AsyncMock()
    manager.get_row = Mock(return_value=SimpleNamespace(user_id=None))

    with authenticated_vault_actor(42):
        await manager._authorize_enterprise_owner("shared")

    manager.enterprise_authorizer.assert_awaited_once_with(42)


@pytest.mark.asyncio
async def test_shared_expert_enterprise_admission_rejects_missing_or_denied_actor():
    manager = object.__new__(AgentManager)
    manager._config = OctopConfig()
    manager.enterprise_authorizer = AsyncMock()
    manager.get_row = Mock(return_value=SimpleNamespace(user_id=None))

    with pytest.raises(OctopError) as absent:
        await manager._authorize_enterprise_owner("shared")
    assert absent.value.code is ErrorCode.ENTERPRISE_ACCESS_DENIED
    with authenticated_vault_actor(None), pytest.raises(OctopError) as denied:
        await manager._authorize_enterprise_owner("shared")
    assert denied.value.code is ErrorCode.ENTERPRISE_ACCESS_DENIED
    manager.enterprise_authorizer.assert_not_awaited()


@pytest.mark.asyncio
async def test_private_expert_enterprise_admission_preserves_owner_validation():
    manager = object.__new__(AgentManager)
    manager._config = OctopConfig()
    manager.enterprise_authorizer = AsyncMock()
    manager.get_row = Mock(return_value=SimpleNamespace(user_id=7))

    with authenticated_vault_actor(42):
        await manager._authorize_enterprise_owner("private")

    manager.enterprise_authorizer.assert_awaited_once_with(7)
