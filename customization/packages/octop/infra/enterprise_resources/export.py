"""Portable exports of owned content; personal runtime configuration stays local."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
from typing import Any

from octop.infra.enterprise_resources.models import (
    PROMPT_FILES,
    ResourceAvatar,
    ResourceDefinition,
    ResourceFile,
    digest,
    invalid,
)
from octop.infra.enterprise_resources.node import resources_for
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.users.identity import User


def _not_found() -> OctopError:
    return OctopError.localized(ErrorCode.NOT_FOUND)


def export_options(server: Any, user: User) -> list[dict[str, str]]:
    sync = resources_for(server)
    result = []
    for agent in server.services.agent_repo.list_all():
        if agent.user_id == user.id and agent.kind == "expert":
            result.append({"kind": "expert", "id": agent.agent_id, "name": agent.name, "slug": ""})
    for package in server.services.skill_package_repo.list_all():
        if package.created_by == str(user.id):
            for slug in sync.packages.list_skill_slugs(package.id):
                result.append(
                    {
                        "kind": "skill",
                        "id": package.id,
                        "name": package.name + " / " + slug,
                        "slug": slug,
                    }
                )
    return result


async def export_resource(
    server: Any, user: User, kind: str, target_id: str, slug: str = ""
) -> ResourceDefinition:
    sync = resources_for(server)
    avatar = None
    if kind == "expert":
        row = await asyncio.to_thread(server.services.agent_repo.get, target_id)
        if row is None or row.user_id != user.id:
            raise _not_found()
        workspace = await asyncio.to_thread(sync._registry().workspace_for_agent, target_id)
        files = {}
        for path in sorted(PROMPT_FILES):
            data = await workspace.adownload_bytes(path)
            if data is not None:
                files[path] = data
        with contextlib.suppress(ValueError):
            avatar = ResourceAvatar.model_validate(
                json.loads(row.config_json or "{}").get("avatar")
            )
        name, description = row.name, row.description or ""
    elif kind == "skill":
        package = await asyncio.to_thread(server.services.skill_package_repo.get, target_id)
        if package is None or package.created_by != str(user.id):
            raise _not_found()
        files = dict(await asyncio.to_thread(sync.packages.read_skill_files, target_id, slug))
        name, description = slug, package.description
    else:
        raise _not_found()
    # Only portable content goes through the same validator as publication.
    # Dependencies are selected explicitly at the authority after import.
    try:
        return ResourceDefinition(
            resource_id=kind + "-" + digest([target_id, slug])[:12],
            kind="expert" if kind == "expert" else "skill",
            display_name=name[:80],
            description=description[:2000],
            avatar=avatar,
            files=[
                ResourceFile(path=path, content_base64=base64.b64encode(value).decode())
                for path, value in files.items()
            ],
        )
    except ValueError:
        raise invalid() from None
