"""Companion availability never widens company permissions or erases local state."""

from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from test_resources import definition, local, publish, workspace

from octop.infra.enterprise_resources import companion as module
from octop.infra.enterprise_resources.companion import CompanionCatalog, CompanionPolicy
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.users.identity import Role


def test_only_company_admin_can_open_published_experts_with_cas(company):
    publish(company, definition(), definition("skill", "manual"))
    policy = CompanionCatalog(company.center)
    before = policy.admin(company.admin)
    assert policy.member(company.alice) == {"expert_ids": []}
    with pytest.raises(OctopError):
        policy.save(company.alice, CompanionPolicy(expert_ids=["quality"]), before["etag"])
    for ids in [["manual"], ["unpublished"]]:
        with pytest.raises(OctopError):
            policy.save(company.admin, CompanionPolicy(expert_ids=ids), before["etag"])
    saved = policy.save(company.admin, CompanionPolicy(expert_ids=["quality"]), before["etag"])
    assert policy.member(company.alice) == {"expert_ids": ["quality"]}
    with pytest.raises(OctopError) as stale:
        policy.save(company.admin, CompanionPolicy(), before["etag"])
    assert stale.value.code == ErrorCode.ENTERPRISE_RESOURCE_CONFLICT
    policy.save(company.admin, CompanionPolicy(), saved["etag"])
    assert policy.member(company.alice) == {"expert_ids": []}


def test_open_policy_intersects_visibility_permissions_and_publication(company):
    publish(
        company,
        definition(allowed_subjects=[company.catalog.center.require_employee(company.alice)]),
    )
    policy = CompanionCatalog(company.center)
    policy.save(
        company.admin, CompanionPolicy(expert_ids=["quality"]), policy.admin(company.admin)["etag"]
    )
    assert policy.member(company.alice)["expert_ids"] == ["quality"]
    assert policy.member(company.bob)["expert_ids"] == []
    assert policy.member(replace(company.alice, role=Role.USER, permissions=[]))["expert_ids"] == []
    publish(company, definition("expert", "new-expert"))
    assert policy.member(company.alice)["expert_ids"] == ["quality"]
    publish(company, definition(enabled=False))
    assert policy.member(company.alice)["expert_ids"] == []


@pytest.mark.asyncio
async def test_revoke_checks_current_policy_and_preserves_personal_copy(company, monkeypatch):
    publish(company, definition())
    node = company.nodes[0]
    await node.sync.sync(node.user)
    agent = local(node)["target_id"]
    personal = dict(workspace(node).files)
    policy = {"expert_ids": ["quality"]}
    client = company.clients[id(node.server)]
    client._state = lambda _uid: {"token": "fixture-purpose-limited"}
    client._remote = AsyncMock(side_effect=lambda *_args, **_kwargs: policy)
    monkeypatch.setattr(module, "client_for", lambda _server: client)
    monkeypatch.setenv("OCTOP_COMPANION_MODE", "1")
    await module.assert_companion_agent(node.server, node.user, agent)
    with pytest.raises(OctopError):
        await module.assert_companion_agent(node.server, node.user, "unpublished-local-clone")
    policy = {"expert_ids": []}
    with pytest.raises(OctopError):
        await module.assert_companion_agent(node.server, node.user, agent)
    assert workspace(node).files == personal
    assert local(node)["target_id"] == agent
    client._remote = AsyncMock(side_effect=OctopError.localized(ErrorCode.ENTERPRISE_UNAVAILABLE))
    with pytest.raises(OctopError):
        await module.assert_companion_agent(node.server, node.user, agent)


@pytest.mark.asyncio
async def test_normal_octop_turns_do_not_require_companion_policy(monkeypatch):
    monkeypatch.delenv("OCTOP_COMPANION_MODE", raising=False)
    monkeypatch.setattr(module, "allowed_companion_agents", AsyncMock(side_effect=AssertionError))
    await module.assert_companion_agent(None, None, "existing-octop-expert")
