from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from octop.infra.connectors.enterprise_account_auth import BusinessAccountAuth
from octop.infra.connectors.enterprise_catalog import (
    CatalogEntry,
    EnterpriseMcpCatalog,
    entry_fingerprint,
)
from octop.infra.errors import OctopError


def broker(company, monkeypatch):
    origin = "https://company.example"
    monkeypatch.setenv("OCTOP_MCP_ACCOUNT_ORIGIN", origin)
    catalog = EnterpriseMcpCatalog(company.center)
    entry = CatalogEntry(
        entry_id="quota-workbench",
        display_name="Workbench",
        url=origin + "/team-mcp/workbench",
        auth_kind="basic",
    )
    state = catalog.save_draft(
        company.admin, [entry.model_dump()], catalog.get_admin(company.admin).etag
    )
    catalog.publish(company.admin, state.etag)
    value = BusinessAccountAuth(company.center)
    value._helper = AsyncMock(
        side_effect=lambda user, entry, action, account_id="": (
            {
                "accounts": [
                    {"account_id": str(user.id), "label": user.label, "password": "do-not-expose"}
                ]
            }
            if action == "list"
            else {"username": "__octop_mcp_" + account_id, "password": "fixture-personal-grant"}
        )
    )
    return value, entry


@pytest.mark.asyncio
async def test_account_picker_contains_only_current_identity_choices_and_never_credentials(
    company, monkeypatch
):
    service, entry = broker(company, monkeypatch)
    result = await service.choices(company.alice, entry.entry_id)
    assert result == {
        "identity_name": company.alice.label,
        "accounts": [{"account_id": str(company.alice.id), "label": company.alice.label}],
    }
    with pytest.raises(OctopError):
        await service.issue(
            company.alice, entry.entry_id, str(company.bob.id), entry_fingerprint(entry)
        )
    assert not any(call.args[2] == "issue" for call in service._helper.call_args_list)
    grant = await service.issue(
        company.alice, entry.entry_id, str(company.alice.id), entry_fingerprint(entry)
    )
    assert grant["username"] == "__octop_mcp_" + str(company.alice.id)


@pytest.mark.asyncio
async def test_account_grant_refuses_stale_target_and_untrusted_destination(company, monkeypatch):
    service, entry = broker(company, monkeypatch)
    with pytest.raises(OctopError):
        await service.issue(company.alice, entry.entry_id, str(company.alice.id), "0" * 64)
    service._helper.assert_not_called()
    monkeypatch.setenv("OCTOP_MCP_ACCOUNT_ORIGIN", "https://another.example")
    with pytest.raises(OctopError):
        await service.choices(company.alice, entry.entry_id)


@pytest.mark.asyncio
async def test_member_grant_uses_existing_probe_and_private_storage_in_correct_order(
    company, monkeypatch
):
    from octop.infra.connectors import enterprise_account_auth as module

    node = company.nodes[0]
    credentials = {"username": "__octop_mcp_13", "password": "fixture-personal-grant"}
    remote = AsyncMock(return_value=credentials)
    client = SimpleNamespace(_state=lambda uid: {"token": "fixture-company-grant"}, _remote=remote)
    save = AsyncMock(return_value={"entries": [], "pending_apply": False})
    monkeypatch.setattr(module, "client_for", lambda server: client)
    monkeypatch.setattr(module, "sync_for", lambda server: SimpleNamespace(save_credentials=save))
    selection = {"account_id": "13", "expected_fingerprint": "a" * 64}
    result = await module.member_account_request(
        node.server, node.user, "quota-workbench", selection
    )
    save.assert_awaited_once_with(node.user, "quota-workbench", credentials, "a" * 64)
    assert "password" not in result
