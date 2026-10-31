"""Reviewable skill revisions and updates with preserved local changes."""

from __future__ import annotations

import asyncio
import difflib
import hashlib
import json
import time
from collections.abc import Mapping
from typing import Any

from octop.infra.errors import ErrorCode, OctopError
from octop.infra.skills.library_sources import read_selected
from octop.infra.skills.revisions import RevisionArchive, files_digest, library_lock, new_plan_id
from octop.infra.skills.skill_package_store import SkillPackageStore, normalize_copy_policy
from octop.infra.skills.skill_packages import (
    normalize_skill_files,
    read_skill_directory,
    validate_skill_slug,
)
from octop.infra.skills.skill_transfer import _stamp_locked_manifest, read_workspace_skill_files
from octop.infra.users.identity import User
from octop.infra.users.permissions import user_has_permission
from octop.infra.utils.frontmatter import parse_frontmatter


def _error(reason: str, status: int = 409) -> OctopError:
    return OctopError(
        ErrorCode.FORBIDDEN, "skill_library." + reason, status=status, details={"reason": reason}
    )


def compare_files(
    base: list[tuple[str, bytes]],
    local: list[tuple[str, bytes]],
    incoming: list[tuple[str, bytes]],
    *,
    tracked: bool,
) -> list[dict[str, Any]]:
    ancestor, current, proposed = dict(base), dict(local), dict(incoming)
    rows = []
    for path in sorted(ancestor.keys() | current.keys() | proposed.keys()):
        old, now, new = ancestor.get(path), current.get(path), proposed.get(path)
        if now == new:
            state, choice = "same", "local"
        elif tracked and now == old:
            state, choice = "incoming", "incoming"
        elif tracked and new == old:
            state, choice = "local", "local"
        elif not tracked and now is None:
            state, choice = "incoming", "incoming"
        else:
            state, choice = "conflict", None

        def preview(value: bytes | None) -> str | None:
            if value is None:
                return ""
            if len(value) > 128 * 1024 or b"\x00" in value:
                return None
            try:
                return value.decode("utf-8")
            except UnicodeDecodeError:
                return None

        before, after = preview(now), preview(new)
        diff = (
            None
            if before is None or after is None
            else "".join(
                difflib.unified_diff(
                    before.splitlines(True),
                    after.splitlines(True),
                    fromfile="local/" + path,
                    tofile="incoming/" + path,
                )
            )[:100_000]
        )
        rows.append(
            {
                "path": path,
                "state": state,
                "choice": choice,
                "local_size": len(now) if now is not None else None,
                "incoming_size": len(new) if new is not None else None,
                "diff": diff,
            }
        )
    return rows


class SkillLibrary:
    def __init__(self, server: Any) -> None:
        self.server = server
        self.store = SkillPackageStore(
            repo=server.services.skill_package_repo, root=server.paths.skill_packages_dir
        )
        self.archive = RevisionArchive(server.paths.skill_packages_dir)
        self._locks: dict[str, asyncio.Lock] = {}

    def package(
        self, package_id: str, user: User, *, write: bool = False, copy: bool = False
    ) -> Any:
        if not user_has_permission(user, "skill_packages"):
            raise _error("permission", 403)
        row = self.store.repo.get(package_id)
        if row is None:
            raise OctopError(ErrorCode.SKILL_PACKAGE_NOT_FOUND, "skill package not found")
        if write:
            self.store.assert_can_mutate(row, user)
        if copy:
            self.store.assert_can_copy(row, user)
        return row

    def current(self, package_id: str, slug: str) -> list[tuple[str, bytes]]:
        path = self.store.package_skills_dir(package_id) / validate_skill_slug(slug)
        return read_skill_directory(path) if (path / "SKILL.md").is_file() else []

    async def workspace(self, agent_id: str, user: User) -> tuple[Any, Any]:
        if not user_has_permission(user, "skills"):
            raise _error("permission", 403)
        row = await asyncio.to_thread(self.server.services.agent_repo.get, agent_id)
        if row is None or (row.user_id != user.id and not user.is_admin):
            raise _error("owner", 403)
        workspace = self.server.app_runtime.agent_registry.workspace_for_agent(agent_id)
        if workspace is None:
            raise _error("workspace_unavailable", 409)
        return workspace, row

    async def _workspace_current(self, workspace: Any, slug: str) -> list[tuple[str, bytes]]:
        text = await workspace.aread_text(f"skills/{slug}/SKILL.md")
        if text is None or parse_frontmatter(text)[0].get("removed"):
            return []
        return await read_workspace_skill_files(workspace, slug)

    async def guard_workspace(self, workspace: Any, agent: Any, slug: str, user: User) -> None:
        text = await workspace.aread_text(f"skills/{slug}/SKILL.md")
        if text and not parse_frontmatter(text)[0].get("removed"):
            metadata, _ = parse_frontmatter(text)
            if metadata.get("locked"):
                origin = str(metadata.get("origin") or "")
                row = await asyncio.to_thread(self.store.repo.get, origin) if origin else None
                if not user.is_admin and (row is None or not self.store.can_mutate(row, user)):
                    raise OctopError(ErrorCode.SKILL_PACKAGE_LOCKED, "locked skill package copy")
            return
        config = json.loads(agent.config_json or "{}")
        for package_id in (
            json.loads(agent.skill_package_ids or "[]")
            if isinstance(agent.skill_package_ids, str)
            else (agent.skill_package_ids or config.get("skill_package_ids", []))
        ):
            summaries = await asyncio.to_thread(self.store.list_skill_summaries, str(package_id))
            if any(row["slug"] == slug for row in summaries):
                raise _error("mounted_readonly", 403)

    def _read_setting(self, key: str, default: Any) -> Any:
        value = self.server.services.settings_repo.get(key)
        return json.loads(value) if value else default

    def _write_setting(self, key: str, value: Any) -> None:
        self.server.services.settings_repo.set(key, json.dumps(value))

    async def history(self, package_id: str, slug: str, user: User) -> dict[str, Any]:
        row = await asyncio.to_thread(self.package, package_id, user)
        self.store.assert_can_download(row, user)
        files = await asyncio.to_thread(self.current, package_id, slug)
        if files:
            await asyncio.to_thread(
                self.archive.put, "package:" + package_id, slug, files, source="current"
            )
        return {
            "current_revision": files_digest(files),
            "revisions": await asyncio.to_thread(
                self.archive.history, "package:" + package_id, slug
            ),
        }

    async def revision_diff(
        self, package_id: str, slug: str, revision: str, user: User
    ) -> dict[str, Any]:
        row = await asyncio.to_thread(self.package, package_id, user)
        self.store.assert_can_download(row, user)
        incoming = await asyncio.to_thread(
            self.archive.get, "package:" + package_id, slug, revision
        )
        current = await asyncio.to_thread(self.current, package_id, slug)
        return {
            "current_revision": files_digest(current),
            "incoming_revision": revision,
            "files": compare_files(current, current, incoming, tracked=True),
        }

    async def _plan(
        self,
        *,
        package_id: str,
        slug: str,
        incoming: list[tuple[str, bytes]],
        user: User,
        agent_id: str | None = None,
        source: str = "package",
        source_key: str | None = None,
    ) -> dict[str, Any]:
        slug = validate_skill_slug(slug)
        row = await asyncio.to_thread(
            self.package, package_id, user, write=agent_id is None, copy=agent_id is not None
        )
        namespace = "agent:" + agent_id if agent_id else "package:" + package_id
        if agent_id:
            workspace, agent = await self.workspace(agent_id, user)
            await self.guard_workspace(workspace, agent, slug, user)
            local = await self._workspace_current(workspace, slug)
            if normalize_copy_policy(row.copy_policy) == "lock":
                incoming = [
                    (path, _stamp_locked_manifest(data, package_id) if path == "SKILL.md" else data)
                    for path, data in incoming
                ]
        else:
            local = await asyncio.to_thread(self.current, package_id, slug)
        key = (
            "skill.library.baseline."
            + hashlib.sha256(
                (namespace + ":" + slug + ":" + (source_key or package_id)).encode()
            ).hexdigest()
        )
        baseline = await asyncio.to_thread(self._read_setting, key, None)
        base = (
            await asyncio.to_thread(self.archive.get, namespace, slug, baseline) if baseline else []
        )
        local_revision = await asyncio.to_thread(
            self.archive.put, namespace, slug, local, source="before-update", actor=user.username
        )
        incoming_revision = await asyncio.to_thread(
            self.archive.put, namespace, slug, incoming, source=source, actor=user.username
        )
        plan_id = new_plan_id()
        plan = {
            "plan_id": plan_id,
            "user_id": user.id,
            "package_id": package_id,
            "agent_id": agent_id,
            "slug": slug,
            "namespace": namespace,
            "baseline_key": key,
            "base_revision": baseline,
            "current_revision": local_revision,
            "incoming_revision": incoming_revision,
            "expires_at": int(time.time()) + 600,
        }
        await asyncio.to_thread(self._write_setting, "skill.library.plan." + plan_id, plan)
        return {
            **plan,
            "files": compare_files(base, local, incoming, tracked=baseline is not None),
            "local_changes": bool(local and (not baseline or local_revision != baseline)),
        }

    async def import_plan(
        self,
        *,
        package_id: str,
        slug: str,
        kind: str,
        root: str,
        user: User,
        explicit: bool,
        source_agent_id: str | None = None,
    ) -> dict[str, Any]:
        await asyncio.to_thread(self.package, package_id, user, write=True)
        workspace = (
            (await self.workspace(source_agent_id, user))[0]
            if kind == "workspace" and source_agent_id
            else None
        )
        if kind == "workspace" and workspace is None:
            raise _error("owner", 403)
        incoming = await read_selected(
            kind=kind, root=root, slug=slug, user=user, explicit=explicit, workspace=workspace
        )
        source_key = hashlib.sha256(
            (kind + ":" + str(source_agent_id) + ":" + root).encode()
        ).hexdigest()
        return await self._plan(
            package_id=package_id,
            slug=slug,
            incoming=incoming,
            user=user,
            source="provider:" + kind,
            source_key=source_key,
        )

    async def install_plan(
        self, package_id: str, slug: str, agent_id: str, user: User
    ) -> dict[str, Any]:
        incoming = await asyncio.to_thread(self.current, package_id, slug)
        if not incoming:
            raise _error("source_missing", 404)
        return await self._plan(
            package_id=package_id, slug=slug, incoming=incoming, user=user, agent_id=agent_id
        )

    async def rollback_plan(
        self, package_id: str, slug: str, revision: str, user: User, agent_id: str | None = None
    ) -> dict[str, Any]:
        await asyncio.to_thread(
            self.package, package_id, user, write=agent_id is None, copy=agent_id is not None
        )
        namespace = "agent:" + agent_id if agent_id else "package:" + package_id
        if agent_id:
            await self.workspace(agent_id, user)
        incoming = await asyncio.to_thread(self.archive.get, namespace, slug, revision)
        if not incoming:
            raise _error("source_missing", 404)
        # A rollback still uses the normal review; changed files require choices.
        return await self._plan(
            package_id=package_id,
            slug=slug,
            incoming=incoming,
            user=user,
            agent_id=agent_id,
            source="rollback",
        )

    async def installation(
        self, package_id: str, slug: str, agent_id: str, user: User
    ) -> dict[str, Any]:
        await asyncio.to_thread(self.package, package_id, user, copy=True)
        workspace, _ = await self.workspace(agent_id, user)
        namespace = "agent:" + agent_id
        key = (
            "skill.library.baseline."
            + hashlib.sha256((namespace + ":" + slug + ":" + package_id).encode()).hexdigest()
        )
        baseline = await asyncio.to_thread(self._read_setting, key, None)
        local = await self._workspace_current(workspace, slug)
        current = files_digest(local)
        return {
            "installed": bool(local),
            "baseline_revision": baseline,
            "current_revision": current,
            "local_changes": bool(local and (baseline is None or current != baseline)),
            "revisions": await asyncio.to_thread(self.archive.history, namespace, slug),
        }

    async def apply(self, plan_id: str, choices: Mapping[str, str], user: User) -> dict[str, str]:
        async with self._locks.setdefault(plan_id, asyncio.Lock()):
            key = "skill.library.plan." + plan_id
            plan = await asyncio.to_thread(self._read_setting, key, None)
            if (
                not plan
                or plan["user_id"] != user.id
                or plan["expires_at"] <= int(time.time())
                or plan.get("used")
            ):
                raise _error("stale")
            package_id, slug, agent_id = plan["package_id"], plan["slug"], plan["agent_id"]
            await asyncio.to_thread(
                self.package, package_id, user, write=agent_id is None, copy=agent_id is not None
            )
            namespace = plan["namespace"]
            if agent_id:
                workspace, agent = await self.workspace(agent_id, user)
                await self.guard_workspace(workspace, agent, slug, user)
                local = await self._workspace_current(workspace, slug)
            else:
                local = await asyncio.to_thread(self.current, package_id, slug)
            if files_digest(local) != plan["current_revision"]:
                raise _error("changed")
            incoming = await asyncio.to_thread(
                self.archive.get, namespace, slug, plan["incoming_revision"]
            )
            base = (
                await asyncio.to_thread(self.archive.get, namespace, slug, plan["base_revision"])
                if plan["base_revision"]
                else []
            )
            rows = compare_files(base, local, incoming, tracked=plan["base_revision"] is not None)
            if set(choices) - {row["path"] for row in rows}:
                raise _error("choices", 400)
            result: dict[str, bytes] = {}
            for row in rows:
                choice = choices.get(row["path"], row["choice"])
                if choice not in {"local", "incoming"}:
                    raise _error("conflict")
                content = (dict(local) if choice == "local" else dict(incoming)).get(row["path"])
                if content is not None:
                    result[row["path"]] = content
            files = list(normalize_skill_files(list(result.items())))
            plan["used"] = True
            await asyncio.to_thread(self._write_setting, key, plan)
            if agent_id:
                # Preserve current full snapshot before any backend mutation. Write
                # only changed files, preserving unrelated concurrently added paths.
                for path, content in files:
                    if dict(local).get(path) != content:
                        await workspace.aupload_many([(f"skills/{slug}/{path}", content)])
                for path, _ in local:
                    if path not in result:
                        await workspace.adelete(f"skills/{slug}/{path}")
            else:

                def commit() -> None:
                    with library_lock(self.store.root, package_id, slug):
                        if files_digest(self.current(package_id, slug)) != plan["current_revision"]:
                            raise _error("changed")
                        self.store.write_skill(package_id, slug, files)

                await asyncio.to_thread(commit)
                await self.server.app_runtime.agent_registry.refresh_agents_for_package(package_id)
            revision = await asyncio.to_thread(
                self.archive.put,
                namespace,
                slug,
                files,
                source="confirmed-update",
                actor=user.username,
            )
            # Base is the accepted upstream, not merged local edits, so later updates
            # keep detecting locally retained files and repeated upstream changes.
            await asyncio.to_thread(
                self._write_setting, plan["baseline_key"], plan["incoming_revision"]
            )
            return {"revision": revision}


def library_for(server: Any) -> SkillLibrary:
    value = getattr(server, "_skill_library", None)
    if not isinstance(value, SkillLibrary):
        value = SkillLibrary(server)
        server._skill_library = value
    return value
