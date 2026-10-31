"""Account isolation, encrypted storage and single-use exact-action approvals."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from octop.infra.connectors.accounts import AccountConnectionError, AccountConnectionService
from octop.infra.connectors.accounts import service as module
from octop.infra.connectors.accounts.tools import build_account_tools
from octop.infra.connectors.accounts.vault_cli import item_metadata
from octop.infra.utils.paths import PathLayout
from octop.infra.utils.ssrf_guard import UnsafeOutboundUrl


class Settings:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.values[key] = value

    def delete(self, key):
        self.values.pop(key, None)


class Secrets:
    def __init__(self):
        self.values = {}

    def get_or_create(self, key, factory):
        if key not in self.values:
            self.values[key] = factory()
        return self.values[key]


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv("OCTOP_HOME", str(tmp_path))
    monkeypatch.setattr(
        module, "validate_https_url_resolved", AsyncMock(side_effect=lambda url: url)
    )
    return AccountConnectionService(
        settings_repo=Settings(), secret_repo=Secrets(), paths=PathLayout(tmp_path)
    )


async def seeded(service):
    connection = await service.save_connection(
        1,
        provider="onepassword",
        name="Owned",
        allowed_hosts=["api.example.com"],
        service_account_token="fake-service-account-token",
    )
    reference = await service.create_reference(
        1, connection_id=connection["id"], item_id="item1", vault_id="vault1"
    )
    return connection, reference


@pytest.mark.asyncio
async def test_credentials_encrypted_and_accounts_isolated(service):
    connection, reference = await seeded(service)
    encoded = json.dumps(service.settings.values)
    assert "fake-service-account-token" not in encoded
    assert "vault1" not in encoded
    assert "service_account_token" not in connection
    assert "fake-service-account-token" not in json.dumps(await service.list_connections(1))
    assert await service.list_connections(2) == []
    with pytest.raises(AccountConnectionError) as error:
        await service.create_reference(
            2, connection_id=connection["id"], item_id="item1", vault_id="vault1"
        )
    assert error.value.status == 404
    with pytest.raises(AccountConnectionError):
        await service.request_use(
            2, reference=reference["reference"], url="https://api.example.com", purpose="test"
        )


@pytest.mark.asyncio
async def test_bitwarden_session_memory_only_and_profile_independent(service):
    connection = await service.save_connection(1, provider="bitwarden", name="BW", allowed_hosts=[])
    assert not connection["ready"]
    await service.unlock_bitwarden(1, connection["id"], "fake-unlock-session")
    assert (await service.list_connections(1))[0]["ready"]
    assert "fake-unlock-session" not in json.dumps(service.settings.values)
    clone = Settings()
    clone.values = service.settings.values.copy()
    restarted = AccountConnectionService(
        settings_repo=clone, secret_repo=service.secrets, paths=service.paths
    )
    assert not (await restarted.list_connections(1))[0]["ready"]
    other = await service.save_connection(2, provider="bitwarden", name="Other", allowed_hosts=[])
    assert connection["profile_path"] != other["profile_path"]
    assert not (await service.list_connections(2))[0]["ready"]
    await service.lock_connection(1, connection["id"])
    assert not (await service.list_connections(1))[0]["ready"]


@pytest.mark.asyncio
async def test_exact_action_approval_single_consume_and_no_secret_outputs(service, monkeypatch):
    _, reference = await seeded(service)
    read = AsyncMock(return_value="fake-vault-value")
    deliver = AsyncMock(return_value=204)
    monkeypatch.setattr(service, "_read_secret", read)
    monkeypatch.setattr(module, "send_secret_header", deliver)
    pending = await service.request_use(
        1,
        reference=reference["reference"],
        url="https://api.example.com/v1/action?scope=one",
        purpose="Own request",
        method="POST",
        body={"message": "reviewed"},
    )
    assert "approval_token" not in pending
    read.assert_not_awaited()
    deliver.assert_not_awaited()
    with pytest.raises(AccountConnectionError):
        await service.approve_use(2, pending["request_id"], "guessed")
    with pytest.raises(AccountConnectionError):
        await service.approve_use(1, pending["request_id"], "guessed")
    row = (await service.list_requests(1))[0]
    # Race two approvals. Exactly one may read/deliver the secret.
    results = await asyncio.gather(
        *[service.approve_use(1, row["request_id"], row["approval_token"]) for _ in range(2)],
        return_exceptions=True,
    )
    assert sum(isinstance(result, AccountConnectionError) for result in results) == 1
    read.assert_awaited_once()
    deliver.assert_awaited_once()
    assert deliver.call_args.args == ("POST", "https://api.example.com/v1/action?scope=one")
    assert deliver.call_args.kwargs["headers"] == {"Authorization": "Bearer fake-vault-value"}
    assert deliver.call_args.kwargs["body"] == {"message": "reviewed"}
    assert "fake-vault-value" not in json.dumps(
        [r for r in results if not isinstance(r, Exception)]
    )
    final = (await service.list_requests(1))[0]
    assert final["state"] == "completed" and final["status_code"] == 204
    assert "approval_token" not in final and "fake-vault-value" not in json.dumps(
        service.settings.values
    )


@pytest.mark.asyncio
async def test_failed_delivery_consumes_request_without_echoing_secret(service, monkeypatch):
    _, reference = await seeded(service)
    monkeypatch.setattr(service, "_read_secret", AsyncMock(return_value="secret-for-test"))
    deliver = AsyncMock(side_effect=RuntimeError("Authorization: Bearer secret-for-test"))
    monkeypatch.setattr(module, "send_secret_header", deliver)
    pending = await service.request_use(
        1, reference=reference["reference"], url="https://api.example.com", purpose="test"
    )
    row = (await service.list_requests(1))[0]
    with pytest.raises(AccountConnectionError) as error:
        await service.approve_use(1, pending["request_id"], row["approval_token"])
    assert error.value.code == "delivery_failed" and "secret-for-test" not in str(error.value)
    with pytest.raises(AccountConnectionError):
        await service.approve_use(1, pending["request_id"], row["approval_token"])
    assert deliver.await_count == 1
    assert (await service.list_requests(1))[0]["state"] == "failed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "target",
    [
        "http://api.example.com",
        "https://evil.example",
        "https://api.example.com.evil.example",
        "https://user:password@api.example.com",
        "https://api.example.com:8443",
        "https://api.example.com/path#fragment",
    ],
)
async def test_targets_must_match_allowlist_exactly(service, target):
    _, reference = await seeded(service)
    with pytest.raises(AccountConnectionError) as error:
        await service.request_use(1, reference=reference["reference"], url=target, purpose="test")
    assert error.value.code == "invalid_target"


@pytest.mark.asyncio
async def test_dns_private_target_rejected_before_vault_access(service, monkeypatch):
    _, reference = await seeded(service)
    monkeypatch.setattr(
        module,
        "validate_https_url_resolved",
        AsyncMock(side_effect=UnsafeOutboundUrl("private address")),
    )
    with pytest.raises(AccountConnectionError):
        await service.request_use(
            1, reference=reference["reference"], url="https://api.example.com", purpose="test"
        )


@pytest.mark.asyncio
async def test_connection_revoke_and_expiry_invalidate_pending_requests(service):
    connection, reference = await seeded(service)
    pending = await service.request_use(
        1, reference=reference["reference"], url="https://api.example.com", purpose="test"
    )
    document = await service._load(1)
    token = document["requests"][pending["request_id"]]["approval_token"]
    document["requests"][pending["request_id"]]["expires_at"] = 0
    await service._save(1, document)
    with pytest.raises(AccountConnectionError) as error:
        await service.approve_use(1, pending["request_id"], token)
    assert error.value.code == "expired_request"
    await service.delete_connection(1, connection["id"])
    assert await service.list_references(1) == []
    assert await service.list_requests(1) == []


def test_cli_item_projection_drops_all_secret_fields():
    payload = [
        {
            "id": "item",
            "name": "Title",
            "login": {"password": "fake-secret", "username": "private-user"},
            "notes": "private-note",
            "fields": [{"value": "private-field"}],
        }
    ]
    result = item_metadata("bitwarden", json.dumps(payload).encode())
    assert result == [{"item_id": "item", "title": "Title", "vault_id": ""}]
    assert "fake-secret" not in json.dumps(result)


@pytest.mark.asyncio
async def test_tools_cannot_approve_or_retrieve_approval_tokens(service, monkeypatch):
    _, reference = await seeded(service)
    tools = {
        tool.name: tool
        for tool in build_account_tools(
            service,
            user_id=1,
            user_repo=SimpleNamespace(
                get=lambda uid: SimpleNamespace(role="user", disabled=0, permissions=["connectors"])
            ),
        )
    }
    assert "vault_approve" not in tools
    pending = json.loads(
        await tools["vault_request_use"].ainvoke(
            {
                "reference": reference["reference"],
                "url": "https://api.example.com",
                "purpose": "test",
            },
            config={"configurable": {"octop_authenticated_user_id": 1}},
        )
    )
    assert "approval_token" not in pending
    status = await tools["vault_use_status"].ainvoke(
        {"request_id": pending["request_id"]},
        config={"configurable": {"octop_authenticated_user_id": 1}},
    )
    assert "approval_token" not in status
    assert json.loads(status)["state"] == "pending"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "actor,permissions,disabled",
    [
        (None, ["connectors"], 0),
        (2, ["connectors"], 0),
        (True, ["connectors"], 0),
        (1, [], 0),
        (1, ["connectors"], 1),
    ],
)
async def test_tools_fail_closed_for_other_missing_or_disabled_actor(
    service, actor, permissions, disabled
):
    await seeded(service)
    repo = SimpleNamespace(
        get=lambda uid: SimpleNamespace(role="user", disabled=disabled, permissions=permissions)
    )
    tool = build_account_tools(service, user_id=1, user_repo=repo)[0]
    config = {"configurable": {"octop_authenticated_user_id": actor}} if actor is not None else {}
    result = json.loads(await tool.ainvoke({}, config=config))
    assert result["error"] == "access_denied"


@pytest.mark.asyncio
async def test_ingress_scope_overrides_stale_checkpoint_actor_and_restores(service):
    from octop.infra.connectors.accounts.actor import authenticated_vault_actor

    await seeded(service)
    repo = SimpleNamespace(
        get=lambda uid: SimpleNamespace(role="user", disabled=0, permissions=["connectors"])
    )
    tool = build_account_tools(service, user_id=1, user_repo=repo)[0]
    old_config = {"configurable": {"octop_authenticated_user_id": 1}}
    with authenticated_vault_actor(2):
        denied = json.loads(await tool.ainvoke({}, config=old_config))
        assert denied["error"] == "access_denied"
        with authenticated_vault_actor(1):
            own = json.loads(
                await tool.ainvoke({}, config={"configurable": {"octop_authenticated_user_id": 2}})
            )
            assert len(own) == 1
        denied_again = json.loads(await tool.ainvoke({}, config=old_config))
        assert denied_again["error"] == "access_denied"
    restored = json.loads(await tool.ainvoke({}, config=old_config))
    assert len(restored) == 1
    with authenticated_vault_actor(None):
        denied = json.loads(await tool.ainvoke({}, config=old_config))
        assert denied["error"] == "access_denied"
