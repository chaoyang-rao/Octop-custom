import base64
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.requests import Request

from octop.api.deps import current_user, get_server, is_jwt_exempt_request
from octop.api.routers.enterprise_mcp_admin import router
from octop.infra.connectors import enterprise_mcp_gateway as module
from octop.infra.connectors.enterprise_catalog import (
    CatalogEntry,
    EnterpriseMcpCatalog,
    entry_fingerprint,
    validate_snapshot,
)
from octop.infra.connectors.enterprise_mcp_protocol import gateway_url
from octop.infra.errors import OctopError
from octop.infra.mobile_access.access import MobileUser, authorize_device_path
from octop.infra.mobile_access.service import DeviceSession


@pytest.fixture
def gateway(company, monkeypatch):
    origin = "https://company.example"
    monkeypatch.setenv("OCTOP_MCP_ACCOUNT_ORIGIN", origin)
    targets = [
        CatalogEntry(entry_id=entry_id, display_name=entry_id, url=url, auth_kind=auth)
        for entry_id, url, auth in [
            ("aftersales-quality", origin + "/team-mcp/aftersales", "bearer"),
            ("quota-workbench", origin + "/team-mcp/workbench", "basic"),
            ("negative-profit", "http://negative.example/mcp", "none"),
        ]
    ]
    service = module.gateway_for(company.center)
    service.configure(company.admin, targets)
    catalog = EnterpriseMcpCatalog(company.center)
    entries = [
        e.model_copy(update={"url": gateway_url(origin, e.entry_id), "auth_kind": "none"})
        for e in targets
    ]
    draft = catalog.save_draft(company.admin, entries, catalog.get_admin(company.admin).etag)
    catalog.publish(company.admin, draft.etag)

    async def helper(user, entry_id, action, account_id=""):
        if action == "list":
            return {"accounts": [{"account_id": str(user.id), "label": user.label}]}
        assert account_id == str(user.id)
        return (
            {"token": "quality-private-" + str(user.id)}
            if entry_id == "aftersales-quality"
            else {"username": "work-" + str(user.id), "password": "work-private-" + str(user.id)}
        )

    mocked_helper = AsyncMock(side_effect=helper)
    monkeypatch.setattr(
        module.BusinessAccountAuth, "_helper", lambda self, *args: mocked_helper(*args)
    )
    calls = []

    def upstream(request):
        calls.append(request)
        if request.url.path.endswith("aftersales"):
            assert request.headers["authorization"].startswith("Bearer quality-private-")
        elif request.url.path.endswith("workbench"):
            assert request.headers["authorization"].startswith("Basic ")
        else:
            assert "authorization" not in request.headers
        data = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"tools": [{"name": "read_only_info", "inputSchema": {"type": "object"}}]},
        }
        return httpx.Response(200, json=data, headers={"Mcp-Session-Id": "same-upstream-id"})

    monkeypatch.setattr(
        module,
        "public_http_transport",
        AsyncMock(side_effect=lambda url: httpx.MockTransport(upstream)),
    )
    return SimpleNamespace(
        service=service,
        catalog=catalog,
        entries=entries,
        targets=targets,
        calls=calls,
        helper=mocked_helper,
        company=company,
    )


def auth(credentials):
    if credentials["auth_mode"] == "basic":
        value = credentials["username"] + ":" + credentials["password"]
        return "Basic " + base64.b64encode(value.encode()).decode()
    return "Bearer " + credentials["token"]


async def consume(reply):
    return b"".join([chunk async for chunk in reply.body])


@pytest.mark.parametrize("entry_id", ["aftersales-quality", "quota-workbench", "negative-profit"])
@pytest.mark.parametrize("mode", ["none", "bearer", "basic"])
async def test_all_nine_member_authorization_combinations_forward_with_scoped_upstream_identity(
    gateway, entry_id, mode
):
    member = gateway.company.alice
    grant = await gateway.service.issue(member, entry_id, mode)
    reply = await gateway.service.forward(
        entry_id,
        "POST",
        {"authorization": auth(grant), "accept": "application/json"},
        b'{"method":"tools/list"}',
    )
    assert reply.status == 200
    assert json.loads(await consume(reply))["result"]["tools"][0]["name"] == "read_only_info"
    assert reply.headers["Mcp-Session-Id"] != "same-upstream-id"
    assert grant.get("token", grant.get("password")) not in str(
        gateway.catalog.snapshot_for(member).model_dump()
    )
    assert all(b"tools/call" not in request.content for request in gateway.calls)


async def test_anonymous_bad_credentials_wrong_service_expired_and_disabled_grants_are_denied(
    gateway, monkeypatch
):
    service = gateway.service
    for invalid in [
        "",
        "Bearer invalid",
        "Basic invalid",
        "Basic " + base64.b64encode(b"no-separator").decode(),
    ]:
        with pytest.raises(OctopError):
            service.authenticate("negative-profit", invalid)
    grant = await service.issue(gateway.company.alice, "negative-profit", "bearer")
    with pytest.raises(OctopError):
        service.authenticate("quota-workbench", auth(grant))
    basic = await service.issue(gateway.company.alice, "negative-profit", "basic")
    with pytest.raises(OctopError):
        service.authenticate("negative-profit", "Bearer " + basic["password"])
    with pytest.raises(OctopError):
        service.authenticate(
            "negative-profit",
            "Basic " + base64.b64encode(("someone-else:" + basic["password"]).encode()).decode(),
        )
    clock = module.time.time()
    with monkeypatch.context() as expired:
        expired.setattr(module.time, "time", lambda: clock + 31 * 86400)
        with pytest.raises(OctopError):
            service.authenticate("negative-profit", auth(grant))
    gateway.company.center.services.user_repo.set_disabled(gateway.company.alice.id, True)
    with pytest.raises(OctopError):
        service.authenticate("negative-profit", auth(grant))


async def test_mcp_sessions_are_bound_to_the_grant_and_service(gateway):
    alice = await gateway.service.issue(gateway.company.alice, "negative-profit", "none")
    bob = await gateway.service.issue(gateway.company.bob, "negative-profit", "none")
    reply = await gateway.service.forward(
        "negative-profit", "POST", {"authorization": auth(alice)}, b"{}"
    )
    await consume(reply)
    sid = reply.headers["Mcp-Session-Id"]
    before = len(gateway.calls)
    with pytest.raises(OctopError):
        await gateway.service.forward(
            "negative-profit", "POST", {"authorization": auth(bob), "mcp-session-id": sid}, b"{}"
        )
    assert len(gateway.calls) == before
    again = await gateway.service.forward(
        "negative-profit", "POST", {"authorization": auth(alice), "mcp-session-id": sid}, b"{}"
    )
    await consume(again)
    assert gateway.calls[-1].headers["mcp-session-id"] == "same-upstream-id"


async def test_disabled_catalog_and_source_change_invalidate_existing_grants(gateway):
    service = gateway.service
    grant = await service.issue(gateway.company.alice, "negative-profit", "none")
    changed = [
        e.model_copy(update={"url": "https://changed.example/mcp"})
        if e.entry_id == "negative-profit"
        else e
        for e in gateway.targets
    ]
    service.configure(gateway.company.admin, changed)
    with pytest.raises(OctopError):
        service.authenticate("negative-profit", auth(grant))
    state = gateway.catalog.get_admin(gateway.company.admin)
    draft = gateway.catalog.save_draft(
        gateway.company.admin,
        [e.model_copy(update={"enabled": False}) for e in gateway.entries],
        state.etag,
    )
    gateway.catalog.publish(gateway.company.admin, draft.etag)
    with pytest.raises(OctopError):
        await service.issue(gateway.company.alice, "negative-profit", "none")


async def test_employee_without_a_bound_business_account_cannot_borrow_another_account(gateway):
    gateway.helper.side_effect = None
    gateway.helper.return_value = {
        "accounts": [{"account_id": "different-member", "label": "Someone else"}]
    }
    with pytest.raises(OctopError):
        await gateway.service.issue(
            gateway.company.alice,
            "aftersales-quality",
            "none",
            account_id=str(gateway.company.alice.id),
        )
    assert not any(call.args[2] == "issue" for call in gateway.helper.call_args_list)


def test_legacy_catalog_keeps_original_authentication_and_checksum(gateway):
    legacy = gateway.catalog.snapshot_for(
        gateway.company.alice, include_gateway=False, include_http=False
    )
    assert {e.entry_id: e.auth_kind for e in legacy.entries} == {
        "aftersales-quality": "bearer",
        "quota-workbench": "basic",
    }
    assert all("/gateway/" not in e.url for e in legacy.entries)
    assert validate_snapshot(legacy.model_dump()).checksum == legacy.checksum


@pytest.mark.parametrize("entry_id", ["aftersales-quality", "quota-workbench", "negative-profit"])
async def test_enterprise_identity_device_can_exchange_only_its_owners_mcp_permissions(
    gateway, entry_id
):
    owner = gateway.company.alice
    user = MobileUser(
        **{**owner.__dict__, "role": "user", "permissions": ["experts", "token_usage"]},
        device_id="member-node",
        device_scopes=("enterprise",),
        device_kind="enterprise",
    )
    session = DeviceSession(owner.id, "member-node", ("enterprise",), 9999999999, "enterprise")
    authorize_device_path(session, "/api/enterprise/mcp/grants/" + entry_id, "POST")
    grant = await gateway.service.issue(user, entry_id, "none")
    assert gateway.service.authenticate(entry_id, auth(grant))[0].id == owner.id
    for method, path in [
        ("GET", "/api/enterprise/mcp/grants/" + entry_id),
        ("POST", "/api/enterprise/mcp/grants/other-service"),
        ("PUT", "/api/enterprise/mcp/admin/gateway"),
        ("POST", "/api/enterprise/mcp/admin/publish"),
    ]:
        with pytest.raises(OctopError):
            authorize_device_path(session, path, method)


async def test_gateway_http_auth_is_separate_from_grant_issuance_and_does_not_echo_secrets(gateway):
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_server] = lambda: gateway.company.center
    app.dependency_overrides[current_user] = lambda: gateway.company.alice

    @app.exception_handler(OctopError)
    async def failure(request, exc):
        return JSONResponse(exc.to_envelope(), status_code=exc.status)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://company.example"
    ) as client:
        denied = await client.post(
            "/api/enterprise/mcp/gateway/negative-profit",
            headers={"Authorization": "Bearer private-invalid"},
            json={},
        )
        assert denied.status_code == 401
        assert "private-invalid" not in denied.text
        granted = await client.post(
            "/api/enterprise/mcp/grants/negative-profit",
            json={
                "auth_mode": "none",
                "expected_fingerprint": entry_fingerprint(gateway.entries[-1]),
            },
        )
        assert granted.status_code == 200
        assert granted.headers["cache-control"] == "no-store"
        result = await client.post(
            "/api/enterprise/mcp/gateway/negative-profit",
            headers={"Authorization": auth(granted.json())},
            json={"method": "tools/list"},
        )
        assert result.status_code == 200
        assert granted.json()["token"] not in result.text
    for path, exempt in [
        ("/api/enterprise/mcp/gateway/negative-profit", True),
        ("/api/enterprise/mcp/grants/negative-profit", False),
        ("/api/enterprise/mcp/gateway/negative-profit/extra", False),
    ]:
        request = Request({"type": "http", "method": "POST", "path": path, "headers": []})
        assert is_jwt_exempt_request(request) is exempt
