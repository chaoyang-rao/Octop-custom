import json
import time
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from tests.unit.enterprise_resources.test_mcp_gateway import auth, consume
from tests.unit.enterprise_resources.test_mcp_gateway import gateway as gateway

from octop.api.deps import current_user, get_server
from octop.api.routers.member_access import router
from octop.infra.auth.enterprise import EnterpriseCenter
from octop.infra.connectors.enterprise_catalog import validate_snapshot
from octop.infra.enterprise_resources import member_access as module
from octop.infra.enterprise_resources.member_access import MemberSelection, access_for
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.mobile_access.access import MobileUser
from octop.infra.mobile_access.service import DeviceSession


async def initialize(gateway):
    return await access_for(gateway.company.center).initialize_owner(
        gateway.company.admin,
        {
            "aftersales-quality": str(gateway.company.admin.id),
            "quota-workbench": str(gateway.company.admin.id),
        },
    )


def test_fresh_authority_defaults_closed_and_admin_lists_only_account_flags(company):
    access = access_for(company.center)
    access.ensure_default()
    assert access.status(company.alice) == {
        "configured": True,
        "revision": 0,
        "mcp_ids": [],
        "companion": False,
    }
    state = access.admin(company.admin)
    assert len(state["members"]) == 3
    assert all(not row["mcp_ids"] and not row["companion"] for row in state["members"])
    assert "identity" not in json.dumps(state)


async def test_one_member_grid_controls_all_three_mcps_and_companion_without_member_business_binding(
    gateway,
):
    state = await initialize(gateway)
    access = access_for(gateway.company.center)
    member = gateway.company.bob
    assert not access.status(member)["mcp_ids"]
    selected = MemberSelection(
        user_id=member.id,
        mcp_ids=["aftersales-quality", "quota-workbench", "negative-profit"],
        companion=True,
    )
    state = access.save(gateway.company.admin, [selected], state["etag"])
    assert access.status(member)["mcp_ids"] == list(module.MCP_IDS)
    assert access.allows_companion(member)
    assert len(gateway.catalog.snapshot_for(member).entries) == 3
    validate_snapshot(gateway.catalog.snapshot_for(member).model_dump())
    gateway.helper.reset_mock()
    grant = await gateway.service.issue(member, "aftersales-quality", "none")
    assert not gateway.helper.await_count
    reply = await gateway.service.forward(
        "aftersales-quality", "POST", {"authorization": auth(grant)}, b"{}"
    )
    await consume(reply)
    assert gateway.calls[-1].headers["authorization"] == "Bearer quality-private-" + str(
        gateway.company.admin.id
    )
    assert all(
        call.args[0].id == gateway.company.admin.id for call in gateway.helper.await_args_list
    )
    raw = gateway.company.center.services.secret_repo.get(
        "enterprise.mcp.service.aftersales-quality"
    )
    assert b"quality-private" not in raw
    assert "quality-private" not in json.dumps(access.admin(gateway.company.admin))


async def test_revocation_denies_existing_gateway_grants_without_deleting_local_resources(gateway):
    state = await initialize(gateway)
    access = access_for(gateway.company.center)
    member = gateway.company.alice
    state = access.save(
        gateway.company.admin,
        [MemberSelection(user_id=member.id, mcp_ids=["negative-profit"], companion=True)],
        state["etag"],
    )
    grant = await gateway.service.issue(member, "negative-profit", "basic")
    assert gateway.service.authenticate("negative-profit", auth(grant))[0].id == member.id
    access.save(gateway.company.admin, [], state["etag"])
    with pytest.raises(OctopError):
        gateway.service.authenticate("negative-profit", auth(grant))
    assert not access.allows_companion(member)
    assert gateway.catalog.snapshot_for(member).entries == []
    assert gateway.company.center.services.user_repo.get(member.id) is not None


async def test_new_member_identity_cannot_inherit_old_identity_entitlements(gateway, monkeypatch):
    state = await initialize(gateway)
    access = access_for(gateway.company.center)
    member = gateway.company.alice
    access.save(
        gateway.company.admin,
        [MemberSelection(user_id=member.id, mcp_ids=["negative-profit"], companion=True)],
        state["etag"],
    )
    original = module.center_for
    monkeypatch.setattr(
        module,
        "center_for",
        lambda server: SimpleNamespace(
            require_employee=lambda user: (
                "f" * 64 if user.id == member.id else original(server).require_employee(user)
            )
        ),
    )
    assert not access.allows_companion(member)
    assert access.status(member)["mcp_ids"] == []


async def test_only_super_administrators_manage_policy_and_stale_edits_do_not_overwrite(gateway):
    state = await initialize(gateway)
    access = access_for(gateway.company.center)
    for user in [
        gateway.company.alice,
        MobileUser(
            **gateway.company.admin.__dict__, device_id="identity", device_scopes=("enterprise",)
        ),
    ]:
        with pytest.raises(OctopError):
            access.admin(user)
        with pytest.raises(OctopError):
            access.save(user, [], state["etag"])
    access.save(gateway.company.admin, [], state["etag"])
    with pytest.raises(OctopError) as error:
        access.save(
            gateway.company.admin,
            [MemberSelection(user_id=gateway.company.alice.id, companion=True)],
            state["etag"],
        )
    assert error.value.code == ErrorCode.ENTERPRISE_ACCESS_POLICY_CONFLICT


async def test_policy_uses_verified_logged_in_members_not_client_supplied_identity(gateway):
    state = await initialize(gateway)
    access = access_for(gateway.company.center)
    with pytest.raises(OctopError):
        access.save(
            gateway.company.admin, [MemberSelection(user_id=999, companion=True)], state["etag"]
        )
    duplicate = MemberSelection(user_id=gateway.company.alice.id, companion=True)
    with pytest.raises(OctopError):
        access.save(gateway.company.admin, [duplicate, duplicate], state["etag"])


async def test_policy_takes_priority_over_old_directory_audiences(gateway):
    state = await initialize(gateway)
    access = access_for(gateway.company.center)
    member = gateway.company.alice
    access.save(
        gateway.company.admin,
        [MemberSelection(user_id=member.id, mcp_ids=["negative-profit"])],
        state["etag"],
    )
    catalog = gateway.catalog
    current = catalog.get_admin(gateway.company.admin)
    entries = [
        entry.model_copy(update={"allowed_subjects": ["not-this-member"]})
        for entry in gateway.entries
    ]
    draft = catalog.save_draft(gateway.company.admin, entries, current.etag)
    catalog.publish(gateway.company.admin, draft.etag)
    assert [entry.entry_id for entry in catalog.snapshot_for(member).entries] == ["negative-profit"]


async def test_admin_http_request_rejects_extra_secret_fields_without_echoing(gateway):
    state = await initialize(gateway)
    app = FastAPI()
    app.include_router(router, prefix="/api")
    actor = {"user": gateway.company.admin}
    app.dependency_overrides[current_user] = lambda: actor["user"]
    app.dependency_overrides[get_server] = lambda: gateway.company.center

    @app.exception_handler(OctopError)
    async def failure(request, error):
        return JSONResponse(error.to_envelope(), status_code=error.status)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://company.example"
    ) as client:
        bad = await client.put(
            "/api/enterprise/access/admin",
            json={"expected_etag": state["etag"], "members": [], "password": "do-not-echo"},
        )
        assert bad.status_code == 400 and "do-not-echo" not in bad.text
        actor["user"] = gateway.company.bob
        denied = await client.get("/api/enterprise/access/admin")
        assert denied.status_code == 403


async def test_company_profile_keeps_member_entitlements_through_the_http_schema(
    company, monkeypatch
):
    from octop.api.routers.enterprise import router as enterprise_router

    access = access_for(company.center)
    access.ensure_default()
    state = access.admin(company.admin)
    access.save(
        company.admin,
        [MemberSelection(user_id=company.alice.id, mcp_ids=["negative-profit"], companion=True)],
        state["etag"],
    )
    company.center.user_manager._users[company.alice.username] = replace(
        company.alice, permissions=[]
    )
    center = EnterpriseCenter(company.center)
    monkeypatch.setattr(
        center.devices,
        "authenticate",
        lambda token: DeviceSession(
            company.alice.id, "node", ("enterprise",), int(time.time()) + 3600, "device"
        ),
    )
    app = FastAPI()
    app.include_router(enterprise_router, prefix="/api")
    app.dependency_overrides[get_server] = lambda: company.center
    app.dependency_overrides[current_user] = lambda: company.alice
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://company.example"
    ) as client:
        result = await client.get(
            "/api/enterprise/session", headers={"Authorization": "Bearer isolated-test-device"}
        )
        assert result.status_code == 200
        assert result.json()["member_access"]["companion"] is True
        assert result.json()["member_access"]["mcp_ids"] == ["negative-profit"]
        assert {"experts", "connector_enabled"} <= set(result.json()["permissions"])
