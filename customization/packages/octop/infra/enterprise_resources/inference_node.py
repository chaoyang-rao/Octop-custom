"""Provision per-member model connections using personal company device grants."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from octop.infra.auth.enterprise import client_for
from octop.infra.enterprise_resources.companion import companion_mode
from octop.infra.enterprise_resources.models import canonical
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.users.groups import RESOURCE_MODEL, GroupAccess, model_resource_key
from octop.infra.users.identity import User

BUILTIN_KIND = "enterprise"
PROFILE_PATH = "/api/enterprise/companion/inference/profile"


class BuiltinModels:
    def __init__(self, server: Any) -> None:
        self.server = server
        self.services = server.services
        self._locks: dict[int, asyncio.Lock] = {}

    async def try_ensure(self, user: User) -> bool:
        try:
            await self.ensure(user)
        except OctopError as error:
            await asyncio.to_thread(
                self.services.settings_repo.set,
                f"companion.models.error.{user.id}",
                error.code.value,
            )
            return False
        await asyncio.to_thread(
            self.services.settings_repo.delete, f"companion.models.error.{user.id}"
        )
        return True

    async def ensure(self, user: User) -> None:
        async with self._locks.setdefault(user.id, asyncio.Lock()):
            client = client_for(self.server)
            if client is None:
                return
            identity = await asyncio.to_thread(client._state, user.id)
            profile = await client._remote("GET", PROFILE_PATH, token=identity["token"])
            changed, name = await asyncio.to_thread(
                self._apply, user, identity, profile, client.authority
            )
            registry = getattr(getattr(self.server, "app_runtime", None), "agent_registry", None)
            refresh = getattr(registry, "on_provider_changed", None)
            if changed and callable(refresh):
                await refresh(provider_name=name)

    def _apply(
        self, user: User, identity: dict[str, Any], profile: dict[str, Any], authority: str
    ) -> tuple[bool, str]:
        default = profile.get("default_model")
        models = profile.get("models")
        if (
            not isinstance(default, str)
            or not isinstance(models, list)
            or default not in {m.get("id") for m in models if isinstance(m, dict)}
        ):
            raise OctopError.localized(ErrorCode.DORA_MODEL_UNAVAILABLE)
        models = sorted(models, key=lambda m: str(m.get("id")) != default)
        name = f"哆啦内置-{user.id}" if companion_mode() else f"词元内置-{user.id}"
        ref = name + "/" + default
        repo = self.services.provider_repo
        row = repo.get_by_name(name)
        if row is not None and row.kind != BUILTIN_KIND:
            raise OctopError.localized(ErrorCode.DORA_MODEL_MANAGED)
        base = authority.rstrip("/") + "/api/enterprise/companion/inference/v1"
        model_json = canonical(models)
        extra_json = canonical(
            {"stream_usage": bool(profile.get("stream_usage")), "managed_owner": user.id}
        )
        changed = (
            row is None
            or row.api_key != identity["token"]
            or row.models_json != model_json
            or row.base_url != base
            or not row.enabled
        )
        if row is None:
            repo.create(
                name=name,
                kind=BUILTIN_KIND,
                base_url=base,
                api_key=identity["token"],
                models_json=model_json,
                extra_json=extra_json,
                note="企业内置模型，随当前飞书身份自动配置；上游模型密钥不进入本机。",
            )
        elif changed:
            repo.update(
                row.id,
                base_url=base,
                api_key=identity["token"],
                models_json=model_json,
                extra_json=extra_json,
                enabled=True,
            )
        settings = self.services.settings_repo
        state_key = f"companion.models.{user.id}"
        previous = json.loads(settings.get(state_key) or "{}")
        previous_ref = previous.get("default_ref")
        if changed or previous.get("revision") != profile.get("revision"):
            groups = self.services.repos.user_group_repo
            group_id = previous.get("group_id")
            group = groups.get(group_id) if isinstance(group_id, str) else None
            if group is None:
                group = groups.create(
                    name=f"哆啦模型账户-{user.id}",
                    description="内置模型的成员身份隔离，由哆啦自动管理。",
                )
            self.services.repos.user_group_member_repo.replace(group.user_group_id, [user.id])
            access = GroupAccess(self.services.repos)
            for model in models:
                access.set_visibility(
                    RESOURCE_MODEL,
                    model_resource_key(name, str(model["id"])),
                    "groups",
                    [group.user_group_id],
                )
            settings.set(
                state_key,
                canonical(
                    {
                        "revision": profile.get("revision"),
                        "group_id": group.user_group_id,
                        "default_ref": ref,
                    }
                ),
            )
        for agent in self.services.agent_repo.list_all():
            if (
                agent.user_id == user.id
                and (not agent.default_model or agent.default_model == previous_ref)
                and agent.default_model != ref
            ):
                self.services.agent_repo.update_config(agent.agent_id, default_model=ref)
                changed = True
        return changed, name


def builtin_models_for(server: Any) -> BuiltinModels:
    value = getattr(server, "_companion_builtin_models", None)
    if value is None:
        value = BuiltinModels(server)
        server._companion_builtin_models = value
    return value


async def company_model_usage(server: Any, user: User, days: int) -> dict[str, Any]:
    if server.services.config.enterprise_center_enabled:
        from octop.infra.enterprise_resources.inference import inference_for

        return await asyncio.to_thread(inference_for(server).usage, user, days)
    client = client_for(server)
    if client is None:
        raise OctopError.localized(ErrorCode.ENTERPRISE_NOT_CONFIGURED)
    state = await asyncio.to_thread(client._state, user.id)
    return await client._remote(
        "GET", f"/api/enterprise/companion/inference/usage?days={days}", token=state["token"]
    )
