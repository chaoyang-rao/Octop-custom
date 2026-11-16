"""Company-controlled expert availability for independently installed companions."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from pydantic import Field

from octop.infra.auth.enterprise import client_for
from octop.infra.enterprise_resources.catalog import ResourceCatalog
from octop.infra.enterprise_resources.models import (
    ResourceEntry,
    StrictModel,
    canonical,
    conflict,
    digest,
    invalid,
)
from octop.infra.enterprise_resources.node import resources_for
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.users.identity import User

POLICY_KEY = "enterprise.companion.experts.v1"


class CompanionPolicy(StrictModel):
    expert_ids: list[str] = Field(default_factory=list, max_length=512)


class CompanionAdminState(CompanionPolicy):
    etag: str
    experts: list[ResourceEntry]


class CompanionAgent(StrictModel):
    agent_id: str
    name: str
    user_id: int


class CompanionCatalog:
    def __init__(self, server: Any) -> None:
        self.server = server
        self.catalog = ResourceCatalog(server)
        self.settings = server.services.settings_repo

    def _read(self) -> tuple[str | None, CompanionPolicy]:
        raw = self.settings.get(POLICY_KEY)
        try:
            return raw, CompanionPolicy.model_validate_json(raw) if raw else CompanionPolicy()
        except ValueError:
            raise invalid() from None

    def admin(self, user: User) -> dict[str, Any]:
        self.catalog._admin(user)
        raw, policy = self._read()
        published = self.catalog.admin(user).published
        return {
            "etag": digest(raw or ""),
            "expert_ids": policy.expert_ids,
            "experts": [e.model_dump(mode="json") for e in published.entries if e.kind == "expert"],
        }

    def save(self, user: User, policy: CompanionPolicy, expected_etag: str) -> dict[str, Any]:
        self.catalog._admin(user)
        raw, _ = self._read()
        if digest(raw or "") != expected_etag:
            raise conflict()
        published = self.catalog.admin(user).published
        eligible = {e.resource_id for e in published.entries if e.kind == "expert" and e.enabled}
        if set(policy.expert_ids) - eligible:
            raise invalid()
        value = canonical({"expert_ids": sorted(set(policy.expert_ids))})
        if not self.settings.compare_and_set(POLICY_KEY, raw, value):
            raise conflict()
        self.server.services.audit_repo.write(
            actor=user.username,
            action="enterprise.companion.experts",
            target=POLICY_KEY,
            payload=value,
        )
        return self.admin(user)

    def member(self, user: User) -> dict[str, Any]:
        _, policy = self._read()
        eligible = self.catalog.member(user)
        return {
            "expert_ids": [
                e.resource_id
                for e in eligible.entries
                if e.kind == "expert" and e.enabled and e.resource_id in policy.expert_ids
            ]
        }


def companion_mode() -> bool:
    return os.environ.get("OCTOP_COMPANION_MODE") == "1"


async def allowed_companion_agents(server: Any, user: User, *, sync: bool = False) -> set[str]:
    client = client_for(server)
    if client is None:
        raise OctopError.localized(ErrorCode.ENTERPRISE_NOT_CONFIGURED)
    await client.authorize(user)
    state = await asyncio.to_thread(client._state, user.id)
    # Always read current policy before admitting a new turn. No stale-policy
    # fallback when the authority is unavailable, and no local admin override.
    remote = await client._remote("GET", "/api/enterprise/companion/experts", token=state["token"])
    policy = CompanionPolicy.model_validate(remote)
    node = resources_for(server)
    local = await node.sync(user) if sync else await asyncio.to_thread(node.status, user)
    return {
        str(item["target_id"])
        for item in local["resources"]
        if item["kind"] == "expert"
        and item["enabled"]
        and item["resource_id"] in policy.expert_ids
        and item.get("target_id")
    }


async def assert_companion_agent(server: Any, user: User, agent_id: str) -> None:
    if companion_mode() and agent_id not in await allowed_companion_agents(server, user):
        raise OctopError.localized(ErrorCode.FORBIDDEN)


async def companion_agents(server: Any, user: User) -> list[CompanionAgent]:
    if companion_mode():
        from octop.infra.enterprise_resources.inference_node import builtin_models_for

        await builtin_models_for(server).try_ensure(user)
    allowed = await allowed_companion_agents(server, user, sync=True)
    if companion_mode():
        await builtin_models_for(server).try_ensure(user)
    rows = await asyncio.to_thread(server.services.agent_repo.list_all)
    return [
        CompanionAgent(agent_id=row.agent_id, name=row.name, user_id=user.id)
        for row in rows
        if row.agent_id in allowed and row.user_id == user.id
    ]
