import time
from unittest.mock import AsyncMock

import pytest
from tests.unit.connectors.test_enterprise_mcp_sync import definition, snapshot
from tests.unit.connectors.test_enterprise_mcp_sync import node as node

from octop.infra.connectors.enterprise_catalog import entry_fingerprint
from octop.infra.connectors.enterprise_mcp_protocol import gateway_url


@pytest.fixture
def gateway_node(node):
    entries = [
        definition(name, url=gateway_url(node.store.authority, name), auth_kind="none")
        for name in ["aftersales-quality", "quota-workbench", "negative-profit"]
    ]
    node.remote[node.alice.id] = snapshot(entries)
    node.client._state = lambda user_id: {"token": "company-identity-only"}

    async def grant(method, path, *, token, body):
        assert method == "POST" and "/mcp/grants/" in path
        assert token == "company-identity-only"
        mode = body["auth_mode"]
        return {
            "auth_mode": mode,
            "expires_at": str(int(time.time()) + 3600),
            **(
                {"username": "mcp_1", "password": "gateway-basic-private"}
                if mode == "basic"
                else {"token": "gateway-" + mode + "-private"}
            ),
        }

    node.client._remote = AsyncMock(side_effect=grant)
    node.gateway_entries = entries
    return node


async def test_company_sign_in_automatically_connects_all_three_without_extra_inputs(gateway_node):
    node = gateway_node
    state = await node.sync.sync(node.alice)
    assert len(state["entries"]) == 3
    assert all(
        e["authorized"] and e["auth_modes"] == ["none", "bearer", "basic"] for e in state["entries"]
    )
    assert node.client._remote.await_count == 3
    assert all(
        c["headers"]["Authorization"] == "Bearer gateway-none-private"
        for c in node.store.harness_configs(node.alice.id).values()
    )
    assert "gateway-none-private" not in str(state)
    assert all(e["selected_auth_mode"] == "none" for e in state["entries"])


@pytest.mark.parametrize("mode", ["none", "bearer", "basic"])
async def test_selected_mode_is_private_and_kept_after_sync(gateway_node, mode):
    node = gateway_node
    entry = node.gateway_entries[0]
    result = await node.sync.save_credentials(
        node.alice,
        entry["entry_id"],
        {},
        entry_fingerprint(entry),
        auth_mode=mode,
        use_company_identity=True,
    )
    item = next(e for e in result["entries"] if e["entry_id"] == entry["entry_id"])
    assert item["selected_auth_mode"] == mode and item["authorized"]
    before = node.client._remote.await_count
    await node.sync.sync(node.alice)
    assert node.client._remote.await_count == before
    assert "gateway-basic-private" not in str(node.store.state(node.alice.id))
    config = node.store.harness_configs(node.alice.id)[item["server_name"]]
    assert config["headers"]["Authorization"].startswith("Basic " if mode == "basic" else "Bearer ")


async def test_disconnected_gateway_is_not_silently_reconnected(gateway_node):
    node = gateway_node
    await node.sync.sync(node.alice)
    await node.sync.revoke_credentials(node.alice, "negative-profit")
    before = node.client._remote.await_count
    result = await node.sync.sync(node.alice)
    entry = next(e for e in result["entries"] if e["entry_id"] == "negative-profit")
    assert not entry["authorized"] and entry["local_disabled"]
    assert node.client._remote.await_count == before
