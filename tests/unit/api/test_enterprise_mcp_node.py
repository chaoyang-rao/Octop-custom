"""Company MCP member HTTP operations do not expose credentials or log users out."""

import base64
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from tests.unit.connectors.test_enterprise_mcp_sync import definition, snapshot
from tests.unit.connectors.test_enterprise_mcp_sync import node as node

from octop.api.deps import current_user, get_server
from octop.api.routers.enterprise_mcp import router
from octop.infra.connectors.enterprise_catalog import entry_fingerprint
from octop.infra.errors import ErrorCode, OctopError


@pytest.fixture
async def api(node):
    app = FastAPI()
    app.include_router(router, prefix="/api")
    actor = {"user": node.alice}
    app.dependency_overrides[current_user] = lambda: actor["user"]
    app.dependency_overrides[get_server] = lambda: node.server

    @app.exception_handler(OctopError)
    async def error_handler(request, error):
        return JSONResponse(status_code=error.status, content=error.to_envelope())

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://node.example"
    ) as client:
        yield SimpleNamespace(client=client, actor=actor, node=node)


async def authorize(api, **credentials):
    return await api.client.put(
        "/api/connectors/enterprise-mcp/entries/quality/credentials",
        json={
            "expected_fingerprint": entry_fingerprint(definition()),
            "token": "private-member-token",
            **credentials,
        },
    )


async def test_member_status_sync_and_authorization_never_return_secret_values(api):
    result = await api.client.post("/api/connectors/enterprise-mcp/sync")
    assert result.status_code == 200
    assert result.headers["Cache-Control"] == "no-store"
    assert result.json()["entries"][0]["needs_reauthorization"] is True
    authorized = await authorize(api)
    assert authorized.status_code == 200
    assert authorized.json()["entries"][0]["authorized"] is True
    assert "private-member-token" not in authorized.text
    assert authorized.headers["Cache-Control"] == "no-store"
    status = await api.client.get("/api/connectors/enterprise-mcp")
    assert status.status_code == 200
    assert "private-member-token" not in status.text
    assert set(status.json()["entries"][0]) >= {
        "fingerprint",
        "authorized",
        "needs_reauthorization",
    }


async def test_upstream_auth_failure_is_not_an_octop_session_401(api):
    api.node.probe.return_value = {
        "ok": False,
        "error_type": "auth",
        "error": "private-member-token",
    }
    response = await authorize(api)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == ErrorCode.CONNECTOR_INVALID_CREDENTIALS.value
    assert "private-member-token" not in response.text
    status = await api.client.get("/api/connectors/enterprise-mcp")
    assert status.status_code == 200
    assert status.json()["entries"][0]["authorized"] is False
    assert api.node.store.state(api.node.alice.id)["desired_auth"] == {}


@pytest.mark.parametrize(
    "extra",
    [
        {"headers": {"Authorization": "secret-not-for-errors"}},
        {"token": {"nested": "secret-not-for-errors"}},
        {"password": {"nested": "secret-not-for-errors"}},
    ],
)
async def test_validation_errors_do_not_echo_rejected_credentials(api, extra):
    response = await authorize(api, **extra)
    assert response.status_code == 400
    assert "secret-not-for-errors" not in response.text
    api.node.probe.assert_not_awaited()
    assert api.node.store.state(api.node.alice.id)["desired_auth"] == {}


async def test_expected_fingerprint_is_required_and_a_stale_form_never_probes(api):
    missing = await api.client.put(
        "/api/connectors/enterprise-mcp/entries/quality/credentials",
        json={"token": "private-member-token"},
    )
    assert missing.status_code == 400
    assert "private-member-token" not in missing.text
    stale = await authorize(api, expected_fingerprint="0" * 64)
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == ErrorCode.ENTERPRISE_MCP_CATALOG_CONFLICT.value
    api.node.probe.assert_not_awaited()


async def test_one_members_disconnect_does_not_delete_another_members_authorization(api):
    assert (await authorize(api)).status_code == 200
    alice_name = api.node.store.server_name("quality", user_id=api.node.alice.id)
    alice_reference = api.node.store.state(api.node.alice.id)["applied_auth"]["quality"]["key"]
    api.actor["user"] = api.node.bob
    other = await api.client.post("/api/connectors/enterprise-mcp/sync")
    assert other.json()["entries"][0]["authorized"] is False
    assert other.json()["entries"][0]["server_name"] != alice_name
    revoked = await api.client.delete("/api/connectors/enterprise-mcp/entries/quality/credentials")
    assert revoked.status_code == 200
    assert api.node.services.secret_repo.get(alice_reference) is not None
    assert alice_name in api.node.store.harness_configs(api.node.alice.id)


async def test_basic_authorization_is_validated_locally_and_not_exposed_in_response(api):
    basic = definition(auth_kind="basic", url="https://words.example/mcp")
    api.node.remote[api.node.alice.id] = snapshot([basic])
    response = await api.client.put(
        "/api/connectors/enterprise-mcp/entries/quality/credentials",
        json={
            "expected_fingerprint": entry_fingerprint(basic),
            "username": "member",
            "password": "private-basic-password",
        },
    )
    assert response.status_code == 200
    assert response.json()["entries"][0]["authorized"] is True
    assert "private-basic-password" not in response.text
    attempted = api.node.probe.call_args.args[0]
    expected = base64.b64encode(b"member:private-basic-password").decode()
    assert attempted["headers"] == {"Authorization": "Basic " + expected}


async def test_member_without_connector_permission_cannot_manage_local_company_grants(api):
    api.actor["user"] = replace(api.node.alice, permissions=[])
    response = await authorize(api)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == ErrorCode.FORBIDDEN.value
    assert "private-member-token" not in response.text
    api.node.client.fetch_mcp_catalog.assert_not_awaited()
    api.node.probe.assert_not_awaited()
    assert api.node.store.state(api.node.alice.id)["desired_auth"] == {}
