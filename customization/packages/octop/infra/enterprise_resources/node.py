"""Member-local resource copies and conservative idle-boundary updates."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any, Literal

from octop.infra.auth.enterprise import client_for
from octop.infra.connectors.enterprise_mcp_store import EnterpriseMcpStore
from octop.infra.enterprise_resources.merge import content_hash, merge_files
from octop.infra.enterprise_resources.models import (
    NAMESPACE,
    PROMPT_FILES,
    ResourceDefinition,
    ResourceEntry,
    canonical,
    conflict,
    digest,
    invalid,
    safe_path,
    snapshot,
    validate_snapshot,
)
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.skills.skill_package_store import SkillPackageStore
from octop.infra.users.identity import User

logger = logging.getLogger(__name__)
BACKUP_NAMESPACE = "enterprise_resource_backup"


def encode_files(files: dict[str, bytes]) -> dict[str, str]:
    return {key: base64.b64encode(value).decode() for key, value in files.items()}


def decode_files(files: dict[str, str]) -> dict[str, bytes]:
    return {key: base64.b64decode(value, validate=True) for key, value in files.items()}


class ResourceSync:
    def __init__(self, server: Any) -> None:
        self.server = server
        self.services = server.services
        self.authority = str(self.services.config.enterprise_authority_url or "").rstrip("/")
        self.source_id = digest(self.authority)[:12]
        self.settings = self.services.settings_repo
        self.blobs = self.services.control_file_repo
        self.packages = SkillPackageStore(
            repo=self.services.skill_package_repo,
            root=server.paths.skill_packages_dir,
            database=self.services.config.database,
        )
        self._locks: dict[int, asyncio.Lock] = {}
        self._workspace_locks: dict[str, asyncio.Lock] = {}
        self._task: asyncio.Task[None] | None = None
        self._attempts: dict[int, float] = {}

    def workspace_lock(self, agent_id: str) -> asyncio.Lock:
        return self._workspace_locks.setdefault(agent_id, asyncio.Lock())

    def _lock(self, user_id: int) -> asyncio.Lock:
        return self._locks.setdefault(user_id, asyncio.Lock())

    def _key(self, user_id: int) -> str:
        return f"enterprise.resources.node.{self.source_id}.{user_id}"

    def _state(self, user_id: int) -> dict[str, Any]:
        raw = self.settings.get(self._key(user_id))
        return (
            json.loads(raw)
            if raw
            else {
                "subject": "",
                "snapshot": snapshot(0, 0, []).model_dump(mode="json"),
                "resources": {},
                "last_synced_at": None,
                "error": None,
            }
        )

    def _save(self, user_id: int, state: dict[str, Any]) -> None:
        self.settings.set(self._key(user_id), canonical(state))

    def _scope(self, user_id: int, state: dict[str, Any], resource_id: str) -> str:
        return digest([self.authority, user_id, state["subject"], resource_id])[:20]

    def _bundle(self, content_digest: str) -> ResourceDefinition:
        data = self.blobs.get(NAMESPACE, content_digest, "bundle.json")
        try:
            parsed = ResourceDefinition.model_validate_json(data or b"")
            if parsed.content_digest() != content_digest:
                raise ValueError
            return parsed
        except (ValueError, TypeError):
            raise invalid() from None

    def _registry(self) -> Any:
        return self.server.app_runtime.agent_registry if self.server.app_runtime else None

    async def _fetch(self, user: User) -> None:
        client = client_for(self.server)
        if client is None:
            raise OctopError.localized(ErrorCode.ENTERPRISE_NOT_CONFIGURED)
        subject, raw = await client.fetch_resource_catalog(user)
        remote = validate_snapshot(raw)
        state = await asyncio.to_thread(self._state, user.id)
        if state["subject"] != subject:
            for record in state["resources"].values():
                if record.get("journal") and not await self._settle_interrupted(
                    user, state, record
                ):
                    raise OctopError.localized(ErrorCode.AGENT_BUSY)
            # Existing local copies remain owned by the member; a different identity
            # gets different deterministic ids and cannot adopt their management state.
            state = {
                **state,
                "subject": subject,
                "resources": {},
                "snapshot": snapshot(0, 0, []).model_dump(mode="json"),
            }
        if remote.revision < state["snapshot"]["revision"]:
            raise invalid()
        for entry in remote.entries:
            if not entry.enabled:
                continue
            cached = await asyncio.to_thread(self.blobs.has_owner, NAMESPACE, entry.digest)
            if not cached:
                data = await client.fetch_resource_bundle(user, entry.digest)
                try:
                    definition = ResourceDefinition.model_validate(data)
                except ValueError:
                    raise invalid() from None
                if (
                    definition.content_digest() != entry.digest
                    or definition.resource_id != entry.resource_id
                    or definition.kind != entry.kind
                ):
                    raise invalid()
                value = canonical(
                    definition.model_dump(mode="json", exclude={"allowed_subjects", "enabled"})
                ).encode()
                await asyncio.to_thread(
                    self.blobs.replace_tree, NAMESPACE, entry.digest, [("bundle.json", value)]
                )
        state["snapshot"] = remote.model_dump(mode="json")
        state["last_synced_at"] = int(time.time())
        state["error"] = None
        await asyncio.to_thread(self._save, user.id, state)

    def _record(self, state: dict[str, Any], entry: ResourceEntry) -> dict[str, Any]:
        record: dict[str, Any] = state["resources"].setdefault(
            entry.resource_id,
            {
                "kind": entry.kind,
                "target_id": None,
                "base_digest": None,
                "base_profile": {},
                "status": "pending",
                "conflicts": [],
                "paused": False,
                "journal": None,
            },
        )

        return record

    def _profile(self, user_id: int, record: dict[str, Any]) -> dict[str, Any]:
        if record["kind"] == "expert":
            row = self.services.agent_repo.get(record["target_id"])
            if row is None or row.user_id != user_id:
                raise conflict()
            cfg = json.loads(row.config_json or "{}")
            return {
                "name": row.name,
                "description": row.description or "",
                "avatar": cfg.get("avatar"),
                "skill_package_ids": json.loads(row.skill_package_ids or "[]"),
                "mcp_servers": json.loads(row.mcp_servers or "[]"),
            }
        package = self.services.skill_package_repo.get(record["target_id"])
        if package is None or package.created_by != str(user_id):
            raise conflict()
        return {"name": package.name, "description": package.description}

    async def _local_files(self, user_id: int, record: dict[str, Any]) -> dict[str, bytes]:
        await asyncio.to_thread(self._profile, user_id, record)  # ownership before content I/O
        if record["kind"] == "skill":
            files = dict(
                await asyncio.to_thread(
                    self.packages.read_skill_files, record["target_id"], record["slug"]
                )
            )
            if any(not safe_path(path) for path in files):
                # Never archive/copy a member's private .env or credential files.
                raise conflict()
            return files
        registry = self._registry()
        workspace = await asyncio.to_thread(registry.workspace_for_agent, record["target_id"])
        if workspace is None:
            raise conflict()
        result = {}
        for path in sorted(PROMPT_FILES):
            value = await workspace.adownload_bytes(path)
            if value is not None:
                result[path] = value
        return result

    def _desired_profile(
        self, user_id: int, state: dict[str, Any], definition: ResourceDefinition
    ) -> dict[str, Any]:
        scope = self._scope(user_id, state, definition.resource_id)
        result: dict[str, Any] = {
            "name": definition.display_name + " · " + scope[:8],
            "description": definition.description,
        }
        if definition.kind == "skill":
            return result
        if definition.avatar is not None:
            result["avatar"] = definition.avatar.model_dump(mode="json")
        packages = []
        for ref in definition.skill_refs:
            record = state["resources"].get(ref)
            if not record or not record.get("target_id") or record["status"] != "current":
                raise conflict()
            packages.append(record["target_id"])
        result["skill_package_ids"] = packages
        mcp = EnterpriseMcpStore(
            self.services.settings_repo, self.services.secret_repo, self.authority
        )
        configs = mcp.harness_configs(user_id)
        result["mcp_servers"] = [
            name
            for ref in definition.mcp_refs
            if (name := mcp.server_name(ref, user_id=user_id)) in configs
        ]
        return result

    async def _ensure_target(
        self,
        user: User,
        state: dict[str, Any],
        entry: ResourceEntry,
        definition: ResourceDefinition,
        record: dict[str, Any],
    ) -> None:
        if record["target_id"]:
            return
        scope = self._scope(user.id, state, entry.resource_id)
        profile = await asyncio.to_thread(self._desired_profile, user.id, state, definition)
        target = "cer_" + scope
        if entry.kind == "expert":
            from octop.infra.agents.manager import AgentCreateSpec

            registry = self._registry()
            row = await asyncio.to_thread(self.services.agent_repo.get, target)
            marker = {
                "source": self.source_id,
                "subject": state["subject"],
                "resource_id": entry.resource_id,
            }
            if row is not None:
                if (
                    row.user_id != user.id
                    or json.loads(row.config_json or "{}").get("enterprise_resource") != marker
                ):
                    raise conflict()
            else:

                async def initialize(_row: Any, workspace: Any) -> None:
                    for path, content in definition.content_files().items():
                        await workspace.aupload_bytes(path, content)

                config: dict[str, Any] = {"enterprise_resource": marker}
                if definition.avatar:
                    config["avatar"] = definition.avatar.model_dump(mode="json")
                await registry.create(
                    AgentCreateSpec(
                        agent_id=target,
                        user_id=user.id,
                        name=profile["name"],
                        description=profile["description"],
                        config=config,
                        skill_package_ids=profile["skill_package_ids"],
                        mcp_servers=profile["mcp_servers"],
                    ),
                    workspace_initializer=initialize,
                )
        else:
            row = await asyncio.to_thread(self.services.skill_package_repo.get, target)
            if row is not None and row.created_by != str(user.id):
                raise conflict()
            if row is not None and record.get("provision_id") != target:
                raise conflict()
            record["slug"] = "corp-" + self.source_id[:8] + "-" + entry.resource_id
            if row is None:
                record["provision_id"] = target
                await asyncio.to_thread(self._save, user.id, state)
                await asyncio.to_thread(
                    self.services.skill_package_repo.create,
                    id=target,
                    name=profile["name"],
                    description=profile["description"],
                    created_by=str(user.id),
                    shared=False,
                )
                await asyncio.to_thread(
                    self.packages.write_skill,
                    target,
                    record["slug"],
                    list(definition.content_files().items()),
                )
            elif not await asyncio.to_thread(self.packages.has_skill, target, record["slug"]):
                if not await asyncio.to_thread(
                    self.packages.seed_empty_skill,
                    target,
                    record["slug"],
                    definition.content_files(),
                ):
                    raise conflict()
        record["target_id"] = target
        # Newly created copies were seeded from this exact bundle. Adopting a
        # crash-recovered id still runs the normal three-way checks below.
        if row is None:
            record["base_digest"] = entry.digest
            actual = await asyncio.to_thread(self._profile, user.id, record)
            record["base_profile"] = {k: actual[k] for k in profile}
        await asyncio.to_thread(self._save, user.id, state)

    async def _read_plan(
        self,
        user: User,
        state: dict[str, Any],
        entry: ResourceEntry,
        decisions: dict[str, Literal["local", "remote"]] | None = None,
    ) -> dict[str, Any]:
        record = self._record(state, entry)
        definition = await asyncio.to_thread(self._bundle, entry.digest)
        current_profile = await asyncio.to_thread(self._profile, user.id, record)
        desired = await asyncio.to_thread(self._desired_profile, user.id, state, definition)
        local = await self._local_files(user.id, record)
        base = (
            (await asyncio.to_thread(self._bundle, record["base_digest"])).content_files()
            if record["base_digest"]
            else {}
        )
        remote = definition.content_files()
        base_profile = record["base_profile"]

        # Only fields managed by the incoming template participate; e.g. an
        # omitted avatar leaves the member's random/personal portrait alone.
        def encoded_profile(values: dict[str, Any]) -> dict[str, bytes]:
            # Colons are forbidden in portable paths, so fields cannot shadow files.
            return {":" + key: canonical(values[key]).encode() for key in desired if key in values}

        combined_base = {**base, **encoded_profile(base_profile)}
        combined_local = {**local, **encoded_profile(current_profile)}
        combined_remote = {**remote, **encoded_profile(desired)}
        merged, conflicts = merge_files(combined_base, combined_local, combined_remote, decisions)
        ticket = digest(
            {
                "subject": state["subject"],
                "remote": entry.digest,
                "base": record["base_digest"],
                "local": {p: content_hash(v) for p, v in combined_local.items()},
            }
        )
        return {
            "ticket": ticket,
            "local_files": local,
            "local_profile": current_profile,
            "remote_profile": desired,
            "merged_files": {p: v for p, v in merged.items() if not p.startswith(":")},
            "merged_profile": {
                p[1:]: json.loads(v) for p, v in merged.items() if p.startswith(":")
            },
            "conflicts": conflicts,
            "definition": definition,
        }

    def _write_profile(
        self,
        user_id: int,
        record: dict[str, Any],
        profile: dict[str, Any],
        expected: dict[str, Any],
    ) -> None:
        if record["kind"] == "skill":
            if not self.services.skill_package_repo.compare_and_update(
                record["target_id"],
                str(user_id),
                expected["name"],
                expected["description"],
                profile["name"],
                profile["description"],
            ):
                raise conflict()
            return
        row = self.services.agent_repo.get(record["target_id"])
        if row is None or self._profile(user_id, record) != expected:
            raise conflict()
        cfg = json.loads(row.config_json or "{}")
        changes: dict[str, Any] = {
            "name": profile["name"],
            "description": profile["description"],
            "skill_package_ids": canonical(profile["skill_package_ids"]),
            "mcp_servers": canonical(profile["mcp_servers"]),
        }
        if profile.get("avatar") != expected.get("avatar"):
            cfg["avatar"] = profile["avatar"]
            changes["config_json"] = canonical(cfg)
        conditions = {
            "user_id": user_id,
            "name": row.name,
            "description": row.description,
            "skill_package_ids": row.skill_package_ids,
            "mcp_servers": row.mcp_servers,
            "config_json": row.config_json,
        }
        if not self.services.agent_repo.compare_and_update(row.agent_id, conditions, changes):
            raise conflict()

    async def _write_files(
        self, record: dict[str, Any], before: dict[str, bytes], after: dict[str, bytes]
    ) -> None:
        if before == after:
            return
        if record["kind"] == "skill":
            if not await asyncio.to_thread(
                self.packages.compare_and_write_skill,
                record["target_id"],
                record["slug"],
                before,
                after,
            ):
                raise conflict()
            return
        workspace = await asyncio.to_thread(
            self._registry().workspace_for_agent, record["target_id"]
        )
        for path in sorted(set(before) | set(after)):
            current = await workspace.adownload_bytes(path)
            if current != before.get(path):
                raise conflict()
            value = after.get(path)
            if current == value:
                continue
            if value is None:
                await workspace.adelete(path)
            else:
                await workspace.aupload_bytes(path, value)

    async def _recover(self, user: User, state: dict[str, Any], record: dict[str, Any]) -> None:
        journal = record.get("journal")
        if not journal:
            return
        current = await self._local_files(user.id, record)
        # Undo only our bytes; edits made after an interrupted update win.
        restored, _ = merge_files(
            decode_files(journal["after_files"]), current, decode_files(journal["before_files"])
        )
        await self._write_files(record, current, restored)
        actual = await asyncio.to_thread(self._profile, user.id, record)
        profile = dict(actual)
        for key, value in journal["before_profile"].items():
            if actual.get(key) == journal["after_profile"].get(key):
                profile[key] = value
        await asyncio.to_thread(self._write_profile, user.id, record, profile, actual)
        record["journal"] = None
        record["status"] = "pending"
        await asyncio.to_thread(self._save, user.id, state)

    def _affected(self, record: dict[str, Any]) -> list[str]:
        if record["kind"] == "expert":
            return [record["target_id"]]
        rows = self.services.agent_repo.list_all(include_disabled=False)
        return sorted(
            row.agent_id
            for row in rows
            if record["target_id"] in json.loads(row.skill_package_ids or "[]")
        )

    async def _apply_entry(
        self,
        user: User,
        state: dict[str, Any],
        entry: ResourceEntry,
        decisions: dict[str, Literal["local", "remote"]] | None = None,
        expected_ticket: str | None = None,
    ) -> None:
        record = self._record(state, entry)
        if record["paused"] or not entry.enabled:
            return
        registry = self._registry()
        if registry is None:
            return
        definition = await asyncio.to_thread(self._bundle, entry.digest)
        await self._ensure_target(user, state, entry, definition, record)
        held: list[str] = []
        for agent_id in await asyncio.to_thread(self._affected, record):
            if not registry.try_begin_runtime_update(agent_id):
                for item in held:
                    registry.end_runtime_update(item)
                record["status"] = "pending"
                if expected_ticket is not None:
                    raise OctopError.localized(ErrorCode.AGENT_BUSY)
                return
            held.append(agent_id)
        lock = self.workspace_lock(record["target_id"])
        try:
            async with lock:
                if record["journal"]:
                    await self._recover(user, state, record)
                plan = await self._read_plan(user, state, entry, decisions)
                if expected_ticket is not None and plan["ticket"] != expected_ticket:
                    raise conflict()
                if plan["conflicts"]:
                    record["status"] = "conflict"
                    record["conflicts"] = [c.path for c in plan["conflicts"]]
                    return
                # Recheck the entire observed state before the first modification.
                current = await self._read_plan(user, state, entry, decisions)
                if current["ticket"] != plan["ticket"]:
                    raise conflict()
                target_profile = {**plan["local_profile"], **plan["merged_profile"]}
                journal = {
                    "before_files": encode_files(plan["local_files"]),
                    "after_files": encode_files(plan["merged_files"]),
                    "before_profile": plan["local_profile"],
                    "after_profile": target_profile,
                }
                changed = (
                    plan["local_files"] != plan["merged_files"]
                    or plan["local_profile"] != target_profile
                )
                if changed:
                    backup_id = (
                        self._scope(user.id, state, entry.resource_id) + "-" + uuid.uuid4().hex
                    )
                    await asyncio.to_thread(
                        self.blobs.replace_tree,
                        BACKUP_NAMESPACE,
                        backup_id,
                        [("backup.json", canonical(journal).encode())],
                    )
                    record["journal"] = journal
                    record["last_backup"] = backup_id
                    await asyncio.to_thread(self._save, user.id, state)
                    try:
                        await asyncio.to_thread(
                            self._write_profile,
                            user.id,
                            record,
                            target_profile,
                            plan["local_profile"],
                        )
                        await self._write_files(record, plan["local_files"], plan["merged_files"])
                        for agent_id in held:
                            await registry.reload_resource_content(agent_id)
                    except Exception:
                        await self._recover(user, state, record)
                        for agent_id in held:
                            with contextlib.suppress(Exception):
                                await registry.reload_resource_content(agent_id)
                        raise
                record.update(
                    base_digest=entry.digest,
                    base_profile=plan["remote_profile"],
                    status="current",
                    local_modified=(
                        plan["merged_files"] != definition.content_files()
                        or plan["merged_profile"] != plan["remote_profile"]
                    ),
                    conflicts=[],
                    journal=None,
                    error=None,
                )
        finally:
            for agent_id in held:
                registry.end_runtime_update(agent_id)

    async def _apply(self, user: User) -> None:
        state = await asyncio.to_thread(self._state, user.id)
        entries = validate_snapshot(state["snapshot"]).entries
        blocked: set[str] = set()
        for resource_id, record in state["resources"].items():
            if not record.get("journal"):
                continue
            try:
                if not await self._settle_interrupted(user, state, record):
                    blocked.add(resource_id)
            except Exception:
                record.update(status="error", error=ErrorCode.ENTERPRISE_RESOURCE_SYNC_FAILED.value)
                blocked.add(resource_id)
            await asyncio.to_thread(self._save, user.id, state)
        for entry in sorted(entries, key=lambda e: (e.kind != "skill", e.resource_id)):
            if entry.resource_id in blocked:
                continue
            record = self._record(state, entry)
            try:
                await self._apply_entry(user, state, entry)
            except OctopError as exc:
                record.update(status="error", error=exc.code.value)
            except Exception as exc:
                logger.warning(
                    "Company resource update failed user=%s resource=%s (%s)",
                    user.id,
                    entry.resource_id,
                    type(exc).__name__,
                )
                record.update(status="error", error=ErrorCode.ENTERPRISE_RESOURCE_SYNC_FAILED.value)
            await asyncio.to_thread(self._save, user.id, state)

    async def _settle_interrupted(
        self, user: User, state: dict[str, Any], record: dict[str, Any]
    ) -> bool:
        """Restore interrupted writes even if distribution was removed or paused."""
        registry = self._registry()
        if registry is None:
            return False
        held: list[str] = []
        try:
            for agent_id in await asyncio.to_thread(self._affected, record):
                if not registry.try_begin_runtime_update(agent_id):
                    record["status"] = "pending"
                    return False
                held.append(agent_id)
            async with self.workspace_lock(record["target_id"]):
                await self._recover(user, state, record)
                for agent_id in held:
                    await registry.reload_resource_content(agent_id)
            return True
        finally:
            for agent_id in held:
                registry.end_runtime_update(agent_id)

    async def sync(self, user: User) -> dict[str, Any]:
        async with self._lock(user.id):
            try:
                await self._fetch(user)
                await self._apply(user)
            except OctopError as exc:
                state = await asyncio.to_thread(self._state, user.id)
                state["error"] = exc.code.value
                await asyncio.to_thread(self._save, user.id, state)
                raise
        return await asyncio.to_thread(self.status, user)

    def status(self, user: User) -> dict[str, Any]:
        state = self._state(user.id)
        visible = {e.resource_id: e for e in validate_snapshot(state["snapshot"]).entries}
        items = []
        for resource_id in sorted(set(visible) | set(state["resources"])):
            entry = visible.get(resource_id)
            record = state["resources"].get(resource_id, {})
            items.append(
                {
                    "resource_id": resource_id,
                    "kind": entry.kind if entry else record["kind"],
                    "display_name": entry.display_name if entry else resource_id,
                    "enabled": bool(entry and entry.enabled),
                    "digest": entry.digest if entry else None,
                    "target_id": record.get("target_id"),
                    "applied_digest": record.get("base_digest"),
                    "status": record.get("status", "pending"),
                    "paused": record.get("paused", False),
                    "local_modified": record.get("local_modified", False),
                    "conflicts": record.get("conflicts", []),
                    "error": record.get("error"),
                }
            )
        return {
            "enabled": bool(self.authority),
            "revision": state["snapshot"]["revision"],
            "last_synced_at": state["last_synced_at"],
            "error": state["error"],
            "resources": items,
        }

    async def detail(self, user: User, resource_id: str) -> dict[str, Any]:
        async with self._lock(user.id):
            state = await asyncio.to_thread(self._state, user.id)
            entry = next(
                (
                    e
                    for e in validate_snapshot(state["snapshot"]).entries
                    if e.resource_id == resource_id and e.enabled
                ),
                None,
            )
            record = state["resources"].get(resource_id)
            if entry is None or not record or not record.get("target_id"):
                raise OctopError.localized(ErrorCode.NOT_FOUND)
            plan = await self._read_plan(user, state, entry)

            def part(value: bytes | None) -> str | None:
                return base64.b64encode(value).decode() if value is not None else None

            return {
                "resource_id": resource_id,
                "ticket": plan["ticket"],
                "local_files": encode_files(plan["local_files"]),
                "conflicts": [
                    {
                        "path": c.path,
                        "base": part(c.base),
                        "local": part(c.local),
                        "remote": part(c.remote),
                    }
                    for c in plan["conflicts"]
                ],
            }

    async def resolve(
        self,
        user: User,
        resource_id: str,
        ticket: str,
        decisions: dict[str, Literal["local", "remote"]],
    ) -> dict[str, Any]:
        async with self._lock(user.id):
            await self._fetch(user)  # fresh visibility and publication before any write
            state = await asyncio.to_thread(self._state, user.id)
            entry = next(
                (
                    e
                    for e in validate_snapshot(state["snapshot"]).entries
                    if e.resource_id == resource_id and e.enabled
                ),
                None,
            )
            if entry is None:
                raise conflict()
            plan = await self._read_plan(user, state, entry)
            if ticket != plan["ticket"] or set(decisions) != {c.path for c in plan["conflicts"]}:
                raise conflict()
            await self._apply_entry(user, state, entry, decisions, ticket)
            await asyncio.to_thread(self._save, user.id, state)
        return await asyncio.to_thread(self.status, user)

    async def pause(self, user: User, resource_id: str, paused: bool) -> dict[str, Any]:
        async with self._lock(user.id):
            state = await asyncio.to_thread(self._state, user.id)
            if resource_id not in state["resources"]:
                raise OctopError.localized(ErrorCode.NOT_FOUND)
            state["resources"][resource_id]["paused"] = paused
            if not paused:
                state["resources"][resource_id]["status"] = "pending"
            await asyncio.to_thread(self._save, user.id, state)
        return await asyncio.to_thread(self.status, user)

    def start(self) -> None:
        if self.authority and (self._task is None or self._task.done()):
            self._task = asyncio.create_task(self._run(), name="enterprise-resources-sync")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while True:
            try:
                rows = await asyncio.to_thread(self.services.user_repo.list)
                for row in rows:
                    try:
                        if not await asyncio.to_thread(
                            self.services.secret_repo.get, f"enterprise.identity.{row.id}"
                        ):
                            continue
                        user = await asyncio.to_thread(self.server.user_manager.get_by_id, row.id)
                        if user is None:
                            continue
                        if time.monotonic() - self._attempts.get(row.id, 0) >= 30:
                            self._attempts[row.id] = time.monotonic()
                            await self.sync(user)
                        elif await asyncio.to_thread(self._has_pending, row.id):
                            async with self._lock(row.id):
                                await self._fetch(user)
                                await self._apply(user)
                    except Exception as exc:
                        logger.warning(
                            "Company resource sync retry user=%s (%s)", row.id, type(exc).__name__
                        )
            except Exception as exc:
                logger.warning("Company resource scan retry (%s)", type(exc).__name__)
            await asyncio.sleep(3)

    def _has_pending(self, user_id: int) -> bool:
        state = self._state(user_id)
        visible = {e.resource_id for e in validate_snapshot(state["snapshot"]).entries if e.enabled}
        return any(
            not r.get("paused")
            and ((key in visible and r.get("status") == "pending") or r.get("journal"))
            for key, r in state["resources"].items()
        )


def resources_for(server: Any) -> ResourceSync:
    value = getattr(server, "_enterprise_resources", None)
    if value is None or value.services is not server.services:
        value = ResourceSync(server)
        server._enterprise_resources = value
    return value


@contextlib.asynccontextmanager
async def workspace_edit(server: Any, agent_id: str) -> AsyncIterator[None]:
    """Serialize dashboard writes with an active resource synchronizer."""
    sync = getattr(server, "_enterprise_resources", None)
    if isinstance(sync, ResourceSync):
        async with sync.workspace_lock(agent_id):
            yield
    else:
        yield
