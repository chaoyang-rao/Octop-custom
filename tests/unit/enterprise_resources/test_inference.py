"""Metered inference, private company credentials, and per-member provisioning."""

import json
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest
from test_resources import definition, publish

from octop.api.routers.providers import _row_to_dict
from octop.infra.enterprise_resources.companion import CompanionPolicy
from octop.infra.enterprise_resources.inference import CONFIG_KEY, InferenceConfig, InferenceService
from octop.infra.enterprise_resources.inference_node import BuiltinModels
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.mobile_access.access import authorize_device_path
from octop.infra.users.groups import RESOURCE_MODEL, GroupAccess, model_resource_key
from octop.infra.users.identity import Role, User

SECRET = "fixture-upstream-key-not-real"


def configured(company, **options):
    publish(company, definition())
    service = InferenceService(company.center)
    policy = service.catalog.admin(company.admin)
    service.catalog.save(company.admin, CompanionPolicy(expert_ids=["quality"]), policy["etag"])
    config = InferenceConfig(
        enabled=True,
        base_url="https://models.example/v1",
        api_key=SECRET,
        default_model="test-model",
        models=[{"id": "test-model", "context_window": 128000}],
        **options,
    )
    service.configure(company.admin, config, service.admin(company.admin)["etag"])
    return service


def request(**changes):
    return {
        "model": "test-model",
        "messages": [{"role": "user", "content": "fixture only"}],
        **changes,
    }


def test_center_keeps_upstream_credential_encrypted_and_out_of_metadata(company):
    service = configured(company)
    assert SECRET not in company.center.services.settings_repo.get(CONFIG_KEY)
    assert SECRET not in json.dumps(service.admin(company.admin))
    assert SECRET not in json.dumps(service.profile(company.alice))
    assert service.profile(company.alice)["models"][0]["max_output_tokens"] == 8192
    with pytest.raises(OctopError):
        service.admin(company.alice)
    with pytest.raises(OctopError):
        service.profile(replace(company.alice, permissions=[]))


@pytest.mark.asyncio
async def test_proxy_applies_output_limit_redacts_provider_echo_and_records_usage(company):
    service = configured(company, max_output_tokens=512)

    async def upstream(req):
        assert req.headers["authorization"] == "Bearer " + SECRET
        body = json.loads(req.content)
        assert body["max_tokens"] == body["max_completion_tokens"] == 512
        assert body["messages"][0]["content"] == "fixture only"
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": SECRET}}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 4},
            },
        )

    service.transport = httpx.MockTransport(upstream)
    reply = await service.open(
        company.alice, "chat/completions", request(max_tokens=99999, max_completion_tokens=99999)
    )
    result = await reply.json()
    assert SECRET not in json.dumps(result)
    assert company.center.services.usage_repo.total_tokens_for_user(company.alice.id) == 11
    assert service._active[company.alice.id] == 0


class SplitSSE(httpx.AsyncByteStream):
    async def __aiter__(self):
        data = (
            "data: "
            + json.dumps({"choices": [{"delta": {"content": SECRET}}]})
            + "\n\ndata: "
            + json.dumps({"usage": {"prompt_tokens": 10, "completion_tokens": 2}})
            + "\n\ndata: [DONE]\n\n"
        ).encode()
        for offset in range(0, len(data), 11):
            yield data[offset : offset + 11]


@pytest.mark.asyncio
async def test_stream_redaction_survives_chunk_boundaries_and_releases_lease(company):
    service = configured(company)
    service.transport = httpx.MockTransport(
        lambda req: httpx.Response(
            200, headers={"Content-Type": "text/event-stream"}, stream=SplitSSE()
        )
    )
    reply = await service.open(company.alice, "chat/completions", request(stream=True))
    output = b"".join([part async for part in reply.events()])
    assert SECRET.encode() not in output
    assert b"[DONE]" in output
    assert company.center.services.usage_repo.total_tokens_for_user(company.alice.id) == 12
    assert service._active[company.alice.id] == 0


@pytest.mark.asyncio
async def test_revocation_quota_rate_and_unsupported_model_reject_before_forwarding(company):
    service = configured(company, requests_per_minute=1)
    calls = []

    def upstream(req):
        calls.append(req)
        return httpx.Response(200, json={"choices": []})

    service.transport = httpx.MockTransport(upstream)
    for changes in [
        {"model": "not-open"},
        {"base_url": "https://evil.example"},
        {"n": 50},
        {"max_tokens": -1},
    ]:
        with pytest.raises(OctopError):
            await service.open(company.alice, "chat/completions", request(**changes))
    assert not calls
    company.center.services.user_policy_repo.set(company.alice.id, "token_quota", "0")
    with pytest.raises(OctopError) as quota:
        await service.open(company.alice, "chat/completions", request())
    assert quota.value.code == ErrorCode.TOKEN_QUOTA_EXCEEDED
    company.center.services.user_policy_repo.set(company.alice.id, "token_quota", None)
    reply = await service.open(company.alice, "chat/completions", request())
    await reply.json()
    with pytest.raises(OctopError) as rate:
        await service.open(company.alice, "chat/completions", request())
    assert rate.value.code == ErrorCode.DORA_MODEL_RATE_LIMITED
    state = service.catalog.admin(company.admin)
    service.catalog.save(company.admin, CompanionPolicy(), state["etag"])
    # Companion expert controls do not revoke the full Octop model service.
    assert service.profile(company.bob)["default_model"] == "test-model"
    with pytest.raises(OctopError):
        await service.open(replace(company.bob, permissions=[]), "chat/completions", request())
    assert len(calls) == 1


def test_enterprise_device_grants_can_infer_but_cannot_configure_the_service():
    session = SimpleNamespace(scopes=("enterprise",))
    for path, method in [
        ("/api/enterprise/companion/inference/profile", "GET"),
        ("/api/enterprise/companion/inference/usage", "GET"),
        ("/api/enterprise/companion/inference/v1/models", "GET"),
        ("/api/enterprise/companion/inference/v1/chat/completions", "POST"),
        ("/api/enterprise/companion/inference/v1/responses", "POST"),
    ]:
        authorize_device_path(session, path, method)
    for path, method in [
        ("/api/enterprise/companion/admin/inference", "GET"),
        ("/api/enterprise/companion/admin/inference", "PUT"),
        ("/api/enterprise/companion/inference/v1/files", "POST"),
    ]:
        with pytest.raises(OctopError):
            authorize_device_path(session, path, method)


def test_member_connections_use_personal_device_grants_not_the_shared_upstream_key(company):
    service = configured(company)
    node = company.nodes[0]
    local = BuiltinModels(node.server)
    profile = service.profile(company.alice)
    changed, name = local._apply(
        node.user, {"token": "fixture-alice-device-grant"}, profile, "https://company.example"
    )
    assert changed
    row = node.server.services.provider_repo.get_by_name(name)
    assert row.kind == "enterprise" and row.api_key == "fixture-alice-device-grant"
    assert SECRET not in row.api_key
    assert row.api_key not in json.dumps(_row_to_dict(row))
    access = GroupAccess(node.server.services.repos)
    key = model_resource_key(name, "test-model")
    assert access.allows(
        user_id=node.user.id,
        is_admin=False,
        resource_type=RESOURCE_MODEL,
        resource_key=key,
        is_owner=False,
    )
    other_id = node.server.services.user_repo.create(
        username="other-local", role=Role.USER, permissions=["experts"]
    )
    other = User(other_id, "other-local", Role.USER, "Other", permissions=["experts"])
    local._apply(other, {"token": "fixture-other-device-grant"}, profile, "https://company.example")
    assert not access.allows(
        user_id=other_id,
        is_admin=False,
        resource_type=RESOURCE_MODEL,
        resource_key=key,
        is_owner=False,
    )
    changed, _ = local._apply(
        node.user, {"token": "fixture-refreshed-device-grant"}, profile, "https://company.example"
    )
    assert (
        changed
        and node.server.services.provider_repo.get_by_name(name).api_key
        == "fixture-refreshed-device-grant"
    )
    updated_profile = {**profile, "stream_usage": True, "revision": "changed-stream-usage"}
    changed, _ = local._apply(
        node.user,
        {"token": "fixture-refreshed-device-grant"},
        updated_profile,
        "https://company.example",
    )
    assert changed
    assert (
        json.loads(node.server.services.provider_repo.get_by_name(name).extra_json)["stream_usage"]
        is True
    )


@pytest.mark.asyncio
async def test_regular_octop_provisions_company_models_and_preserves_personal_defaults(
    company, monkeypatch
):
    from unittest.mock import AsyncMock

    from octop.infra.enterprise_resources import inference_node

    monkeypatch.delenv("OCTOP_COMPANION_MODE", raising=False)
    service = configured(company)
    node = company.nodes[0]
    agents = node.server.services.agent_repo
    agents.create(
        agent_id="personal", user_id=node.user.id, name="Personal", default_model="mine/model"
    )
    agents.create(agent_id="automatic", user_id=node.user.id, name="Automatic")
    client = SimpleNamespace(
        authority="https://company.example",
        _state=lambda uid: {"token": "fixture-personal-company-grant"},
        _remote=AsyncMock(return_value=service.profile(company.alice)),
    )
    monkeypatch.setattr(inference_node, "client_for", lambda server: client)
    await BuiltinModels(node.server).ensure(node.user)
    assert agents.get("personal").default_model == "mine/model"
    assert agents.get("automatic").default_model == f"词元内置-{node.user.id}/test-model"
    row = node.server.services.provider_repo.get_by_name(f"词元内置-{node.user.id}")
    assert row.api_key == "fixture-personal-company-grant"
    client._remote.assert_awaited_once()


async def test_resource_sync_recovers_models_after_failed_first_login(company, monkeypatch):
    from unittest.mock import AsyncMock

    from octop.infra.enterprise_resources import inference_node

    monkeypatch.delenv("OCTOP_COMPANION_MODE", raising=False)
    service = configured(company)
    node = company.nodes[0]
    agents = node.server.services.agent_repo
    agents.create(agent_id="stranded", user_id=node.user.id, name="Primary")
    agents.set_state("stranded", "failed", error="NO_MODELS_CONFIGURED")
    client = SimpleNamespace(
        authority="https://company.example",
        _state=lambda uid: {"token": "fixture-personal-company-grant"},
        _remote=AsyncMock(
            side_effect=[
                OctopError.localized(ErrorCode.ENTERPRISE_UNAVAILABLE),
                service.profile(company.alice),
            ]
        ),
    )
    monkeypatch.setattr(inference_node, "client_for", lambda server: client)
    local = inference_node.builtin_models_for(node.server)
    assert not await local.try_ensure(node.user)
    assert not node.server.services.provider_repo.list_all()

    async def refresh(*, provider_name):
        assert agents.get("stranded").default_model == provider_name + "/test-model"
        agents.set_state("stranded", "running", error=None)

    node.registry.on_provider_changed = AsyncMock(side_effect=refresh)
    await node.sync.sync(node.user)
    name = f"词元内置-{node.user.id}"
    assert node.server.services.provider_repo.get_by_name(name).enabled
    assert agents.get("stranded").last_state == "running"
    assert node.server.services.settings_repo.get(f"companion.models.error.{node.user.id}") is None
    node.registry.on_provider_changed.assert_awaited_once_with(provider_name=name)
    assert GroupAccess(node.server.services.repos).allows(
        user_id=node.user.id,
        is_admin=False,
        resource_type=RESOURCE_MODEL,
        resource_key=model_resource_key(name, "test-model"),
        is_owner=False,
    )


async def test_directory_failure_does_not_prevent_model_recovery(company, monkeypatch):
    from unittest.mock import AsyncMock

    from octop.infra.enterprise_resources import inference_node

    service = configured(company)
    node = company.nodes[0]
    client = SimpleNamespace(
        authority="https://company.example",
        _state=lambda uid: {"token": "fixture-personal-company-grant"},
        _remote=AsyncMock(return_value=service.profile(company.alice)),
    )
    monkeypatch.setattr(inference_node, "client_for", lambda server: client)
    company.clients[id(node.server)].fetch_resource_catalog.side_effect = OctopError.localized(
        ErrorCode.ENTERPRISE_UNAVAILABLE
    )
    with pytest.raises(OctopError):
        await node.sync.sync(node.user)
    assert len(node.server.services.provider_repo.list_all()) == 1


async def test_model_failure_does_not_block_other_enterprise_resources(company, monkeypatch):
    from unittest.mock import AsyncMock

    from octop.infra.enterprise_resources import inference_node

    configured(company)
    node = company.nodes[0]
    client = SimpleNamespace(
        authority="https://company.example",
        _state=lambda uid: {"token": "fixture-personal-company-grant"},
        _remote=AsyncMock(side_effect=OctopError.localized(ErrorCode.DORA_MODEL_UNAVAILABLE)),
    )
    monkeypatch.setattr(inference_node, "client_for", lambda server: client)
    result = await node.sync.sync(node.user)
    assert result["resources"] and not result["error"]


def test_company_usage_resolves_current_owner_and_never_grants_team_data_to_local_admin(company):
    service = configured(company)
    repo = company.center.services.repos.company_model_usage_repo
    for who, amount in [(company.alice, 10), (company.bob, 20)]:
        repo.record(
            user_id=who.id,
            model="test-model",
            request_id=f"usage-{who.id}",
            input_tokens=amount,
            output_tokens=2,
            source="dora_model",
        )
    own = service.usage(replace(company.alice, role=Role.ADMIN), 30)
    assert own["scope"] == "self" and own["totals"]["total_tokens"] == 12
    assert {r["user_id"] for r in own["rows"]} == {company.alice.id}
    admin = service.usage(replace(company.admin, role=Role.USER), 30)
    assert admin["scope"] == "company" and admin["totals"]["total_tokens"] == 34
    assert {r["user_id"] for r in admin["rows"]} == {company.alice.id, company.bob.id}
    assert all("member_name" in row for row in admin["rows"])
