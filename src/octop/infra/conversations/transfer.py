"""Previewed user-owned history and expert portability, without identity stores."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import zipfile
from pathlib import PurePosixPath
from typing import Any

from pydantic import ValidationError

from octop.infra.conversations.archives import (
    MAX_ARCHIVE_BYTES,
    MAX_ARCHIVE_FILES,
    MAX_ENTRY_BYTES,
    MAX_MESSAGES,
    ConversationArchiveError,
    grok_history,
    json_document,
    portable_workspace_path,
    read_zip,
    redact_config_text,
)
from octop.infra.conversations.models import (
    ExportSelection,
    ImportSelection,
    PortableBundle,
    PortableConversation,
    PortableExpert,
    PortableMessage,
)
from octop.infra.conversations.service import ConversationService
from octop.infra.history.reader import export_messages
from octop.infra.skills.skill_packages import normalize_skill_files, validate_skill_slug
from octop.infra.skills.skill_transfer import read_workspace_skill_files
from octop.infra.tasks.models import WorkflowDefinition
from octop.infra.utils.frontmatter import parse_frontmatter
from octop.infra.utils.ulid import new_short_id, new_ulid


class ConversationTransfer:
    def __init__(self, service: ConversationService) -> None:
        self.service = service
        self.repo = service.repos.conversation_repo
        self._locks: dict[int, asyncio.Lock] = {}

    async def stage(self, user_id: int, data: bytes) -> dict[str, Any]:
        await asyncio.to_thread(self.service.identity, user_id)
        try:
            files = await asyncio.to_thread(read_zip, data)
            sha = hashlib.sha256(data).hexdigest()
            if "octop-transfer.json" in files:
                bundle = PortableBundle.model_validate(
                    await asyncio.to_thread(json_document, files["octop-transfer.json"])
                )
                kind = "transfer"
                payload: dict[str, Any] = {"bundle": bundle.model_dump()}
                relevant = self._bundle_files(bundle, files)
            elif "openbot-import.json" in files or "openbot-transfer.json" in files:
                # Public JSON contract only, never OpenBot implementation or bundled skill text.
                bundle, relevant = self._public_agent_bundle(files)
                kind = "transfer"
                payload = {"bundle": bundle.model_dump()}
            else:
                imported = await asyncio.to_thread(grok_history, files)
                kind = "grok-history"
                payload = {
                    "conversations": [item.model_dump() for item in imported.conversations],
                    "omitted_messages": imported.omitted_messages,
                    "ignored_files": imported.ignored_files,
                }
                relevant = {}
        except ConversationArchiveError as error:
            raise self.service.error(error.reason, user_id) from None
        except (ValidationError, ValueError, TypeError, KeyError):
            raise self.service.error("unsupported_format", user_id) from None
        payload["files"] = {
            name: base64.b64encode(value).decode() for name, value in relevant.items()
        }
        preview_id = new_ulid()
        await asyncio.to_thread(
            self.repo.stage,
            preview_id=preview_id,
            user_id=user_id,
            kind=kind,
            sha=sha,
            payload=json.dumps(payload, ensure_ascii=False),
        )
        return await self.preview(user_id, preview_id)

    @staticmethod
    def _bundle_files(bundle: PortableBundle, files: dict[str, bytes]) -> dict[str, bytes]:
        keys = {agent.key for agent in bundle.agents}
        if len(keys) != len(bundle.agents) or set(bundle.conversations) - keys:
            raise ConversationArchiveError("unsupported_format")
        if (
            sum(len(chats) for chats in bundle.conversations.values()) > 5000
            or sum(len(chat.messages) for chats in bundle.conversations.values() for chat in chats)
            > MAX_MESSAGES
        ):
            raise ConversationArchiveError("archive_limit")
        relevant: dict[str, bytes] = {}
        for agent in bundle.agents:
            if set(agent.members) - keys or agent.key in agent.members:
                raise ConversationArchiveError("unsupported_format")
            for name in agent.workspace_files:
                if not portable_workspace_path(name):
                    raise ConversationArchiveError("unsafe_archive")
                path = f"agents/{agent.key}/workspace/{name}"
                if path not in files:
                    raise ConversationArchiveError("invalid_archive")
                relevant[path] = files[path]
            for slug in agent.skills:
                validate_skill_slug(slug)
                prefix = f"agents/{agent.key}/skills/{slug}/"
                entries = [
                    (path[len(prefix) :], data)
                    for path, data in files.items()
                    if path.startswith(prefix)
                ]
                normalized = normalize_skill_files(entries)
                for name, data in normalized:
                    if not portable_workspace_path(name):
                        raise ConversationArchiveError("unsafe_archive")
                    relevant[prefix + name] = data
        return relevant

    @staticmethod
    def _public_agent_bundle(files: dict[str, bytes]) -> tuple[PortableBundle, dict[str, bytes]]:
        manifest_name = (
            "openbot-import.json" if "openbot-import.json" in files else "openbot-transfer.json"
        )
        raw = json_document(files[manifest_name])
        if (
            not isinstance(raw, dict)
            or raw.get("version") != 1
            or not isinstance(raw.get("agents"), list)
        ):
            raise ConversationArchiveError("unsupported_format")
        agents = []
        relevant: dict[str, bytes] = {}
        warnings = ["foreign_settings_omitted"]
        for item in raw["agents"]:
            if not isinstance(item, dict):
                raise ConversationArchiveError("unsupported_format")
            profile: dict[str, Any] = (
                item["profile"] if isinstance(item.get("profile"), dict) else item
            )
            key = str(item.get("key") or item.get("id") or "")
            name = profile.get("name") or profile.get("title")
            instructions = profile.get("instructions") or item.get("instructions") or ""
            if not isinstance(name, str) or not isinstance(instructions, str):
                raise ConversationArchiveError("unsupported_format")
            workspace = []
            skills: set[str] = set()
            source_prefix = f"agents/{key}/"
            for path, data in files.items():
                if not path.startswith(source_prefix):
                    continue
                relative = path[len(source_prefix) :]
                skill_path = next(
                    (
                        relative[len(prefix) :]
                        for prefix in ("skills/", ".agents/skills/", ".claude/skills/")
                        if relative.startswith(prefix)
                    ),
                    None,
                )
                if skill_path and "/" in skill_path:
                    slug, tail = skill_path.split("/", 1)
                    validate_skill_slug(slug)
                    if not portable_workspace_path(tail):
                        continue
                    target = f"agents/{key}/skills/{slug}/{tail}"
                    if target in relevant and relevant[target] != data:
                        raise ConversationArchiveError("conflicting_skills")
                    skills.add(slug)
                    relevant[target] = data
                elif relative.startswith("workspace/"):
                    target_path = relative[len("workspace/") :]
                    if portable_workspace_path(target_path) and not target_path.startswith(
                        "skills/"
                    ):
                        workspace.append(target_path)
                        relevant[f"agents/{key}/workspace/{target_path}"] = data
            agents.append(
                PortableExpert(
                    key=key,
                    name=name,
                    instructions=instructions,
                    description=str(profile.get("description") or "")[:5000],
                    workspace_files=workspace,
                    skills=sorted(skills),
                )
            )
        bundle = PortableBundle(agents=agents, warnings=warnings)
        # Validate each complete skill, and normalize foreign roots into our own format.
        return bundle, ConversationTransfer._bundle_files(bundle, relevant)

    async def preview(self, user_id: int, preview_id: str) -> dict[str, Any]:
        await asyncio.to_thread(self.service.identity, user_id)
        row = await asyncio.to_thread(self.repo.preview, preview_id, user_id)
        if row is None:
            raise self.service.error("preview_expired", user_id, 404)
        payload = json.loads(row["payload_json"])
        items = []
        if row["kind"] == "grok-history":
            known = await asyncio.to_thread(self.repo.imported_ids, user_id, "grok-history")
            items = [
                {
                    "key": item["external_id"],
                    "name": item["title"],
                    "messages": len(item["messages"]),
                    "duplicate": item["external_id"] in known,
                    "name_conflict": False,
                    "skills": 0,
                    "files": 0,
                }
                for item in payload.get("conversations", [])
            ]
        elif "bundle" in payload:
            names = {
                row.name
                for row in await asyncio.to_thread(
                    self.service.repos.agent_repo.list_by_user, user_id
                )
            }
            bundle = PortableBundle.model_validate(payload["bundle"])
            items = [
                {
                    "key": agent.key,
                    "name": agent.name,
                    "messages": len(bundle.conversations.get(agent.key, [])),
                    "duplicate": False,
                    "name_conflict": agent.name in names,
                    "skills": len(agent.skills),
                    "files": len(agent.workspace_files),
                }
                for agent in bundle.agents
            ]
        return {
            "id": preview_id,
            "kind": row["kind"],
            "state": row["state"],
            "sha256": row["source_sha256"],
            "expires_at": row["expires_at"],
            "items": items,
            "omitted_messages": payload.get("omitted_messages", 0),
            "ignored_files": payload.get("ignored_files", 0),
            "warnings": (payload.get("bundle") or {}).get("warnings", []),
            "bytes": sum(len(value) * 3 // 4 for value in payload.get("files", {}).values()),
        }

    async def discard(self, user_id: int, preview_id: str) -> None:
        await asyncio.to_thread(self.service.identity, user_id)
        await asyncio.to_thread(self.repo.discard, preview_id, user_id)

    async def confirm(
        self, user_id: int, preview_id: str, selection: ImportSelection
    ) -> dict[str, Any]:
        lock = self._locks.setdefault(user_id, asyncio.Lock())
        async with lock:
            await asyncio.to_thread(self.service.identity, user_id)
            row = await asyncio.to_thread(self.repo.preview, preview_id, user_id)
            if row is None or row["state"] != "preview":
                raise self.service.error("preview_expired", user_id, 409)
            payload = json.loads(row["payload_json"])
            keys = set(selection.keys)
            known_keys = {
                item["key"] for item in (await self.preview(user_id, preview_id))["items"]
            }
            if not keys <= known_keys:
                raise self.service.error("invalid_selection", user_id)
            if row["kind"] == "grok-history":
                if not selection.target_agent_id:
                    raise self.service.error("agent_required", user_id)
                await asyncio.to_thread(
                    self.service.owned_agent, user_id, selection.target_agent_id
                )
            else:
                await asyncio.to_thread(self.service.identity, user_id, "experts")
                if selection.include_skills:
                    await asyncio.to_thread(self.service.identity, user_id, "skills")
            if not await asyncio.to_thread(self.repo.claim_preview, preview_id, user_id):
                raise self.service.error("preview_expired", user_id, 409)
            created: list[str] = []
            try:
                if row["kind"] == "grok-history":
                    conversations = [
                        PortableConversation.model_validate(item)
                        for item in payload["conversations"]
                        if item["external_id"] in keys
                    ]
                    result = await self._history(
                        user_id,
                        preview_id,
                        selection.target_agent_id or "",
                        conversations,
                        row["kind"],
                        row["source_sha256"],
                        skip_duplicates=selection.skip_duplicates,
                    )
                else:
                    result = await self._apply_bundle(
                        user_id, preview_id, payload, row["source_sha256"], selection, created
                    )
                await asyncio.to_thread(self.repo.finish_preview, preview_id, user_id, success=True)
                return result
            except BaseException:
                # Roll back only IDs allocated by this import; never touch pre-existing resources.
                for agent_id in reversed(created):
                    current = await asyncio.to_thread(self.service.repos.agent_repo.get, agent_id)
                    if current is not None and current.user_id == user_id:
                        await asyncio.shield(self.service.agents.delete(agent_id))
                await asyncio.shield(
                    asyncio.to_thread(self.repo.finish_preview, preview_id, user_id, success=False)
                )
                raise

    async def _history(
        self,
        user_id: int,
        preview_id: str,
        agent_id: str,
        conversations: list[PortableConversation],
        source: str,
        sha: str,
        *,
        skip_duplicates: bool,
    ) -> dict[str, Any]:
        await asyncio.to_thread(self.service.owned_agent, user_id, agent_id)
        known = (
            await asyncio.to_thread(self.repo.imported_ids, user_id, source)
            if skip_duplicates
            else set()
        )
        rows = []
        for item in conversations:
            if item.external_id in known:
                continue
            thread_id = new_ulid()
            # Imported history is a read-only record, never seeded as a live model checkpoint.
            wires = [
                {
                    "type": "human" if message.role == "user" else "ai",
                    "data": {
                        "id": new_ulid(),
                        "content": message.content,
                        "additional_kwargs": {
                            "octop_imported": True,
                            "import_source": source,
                            "external_message_id": message.external_id,
                            "source_timestamp": message.created_at,
                        },
                    },
                }
                for message in item.messages
            ]
            rows.append(
                {
                    "thread_id": thread_id,
                    "origin_id": new_ulid(),
                    "external_id": item.external_id,
                    "agent_id": agent_id,
                    "title": item.title,
                    "messages": wires,
                    "archived": True,
                    "session_key": f"{agent_id}:dashboard:{user_id}:import-{thread_id}",
                }
            )
        await asyncio.to_thread(
            self.repo.import_history,
            preview_id=preview_id,
            user_id=user_id,
            source=source,
            sha=sha,
            rows=rows,
        )
        return {
            "threads": [
                {"thread_id": row["thread_id"], "agent_id": row["agent_id"], "title": row["title"]}
                for row in rows
            ],
            "agents": [],
            "skipped": len(conversations) - len(rows),
            "warnings": [],
        }

    async def _apply_bundle(
        self,
        user_id: int,
        preview_id: str,
        payload: dict[str, Any],
        sha: str,
        selection: ImportSelection,
        created: list[str],
    ) -> dict[str, Any]:
        from octop.infra.agents.manager import AgentCreateSpec

        bundle = PortableBundle.model_validate(payload["bundle"])
        keys = set(selection.keys)
        selected = [agent for agent in bundle.agents if agent.key in keys]
        names = {
            row.name
            for row in await asyncio.to_thread(self.service.repos.agent_repo.list_by_user, user_id)
        }
        model = selection.default_model
        if model and not self.service.agents.providers.is_model_ref_usable(model):
            raise self.service.error("model_unavailable", user_id)
        mapping = {agent.key: new_short_id() for agent in selected}
        output = []
        warnings = list(bundle.warnings)
        # Team members are available first. Host selection always follows local 小通 policy.
        for expert in sorted(selected, key=lambda item: item.kind == "team"):
            await asyncio.to_thread(self.service.identity, user_id, "experts")
            requested = (selection.names.get(expert.key) or expert.name).strip()
            if not requested or len(requested) > 100:
                raise self.service.error("invalid_name", user_id)
            name = requested
            counter = 2
            while name in names:
                name = f"{requested[:90]} ({counter})"
                counter += 1
            names.add(name)
            files: list[tuple[str, bytes]] = []
            if selection.include_files:
                for path in expert.workspace_files:
                    files.append(
                        (
                            path,
                            base64.b64decode(
                                payload["files"][f"agents/{expert.key}/workspace/{path}"],
                                validate=True,
                            ),
                        )
                    )
            if selection.include_skills:
                for slug in expert.skills:
                    prefix = f"agents/{expert.key}/skills/{slug}/"
                    sources = [
                        (path[len(prefix) :], base64.b64decode(data, validate=True))
                        for path, data in payload["files"].items()
                        if path.startswith(prefix)
                    ]
                    for path, data in normalize_skill_files(sources):
                        if path == "SKILL.md":
                            metadata, _ = parse_frontmatter(data.decode("utf-8"))
                            if metadata.get("locked"):
                                # Foreign origin IDs cannot collide with a local package ID and unlock it.
                                from octop.infra.skills.skill_transfer import _stamp_locked_manifest

                                data = _stamp_locked_manifest(
                                    data, f"import-{sha[:16]}-{expert.key}"
                                )
                                warnings.append("locked_skill_preserved")
                        files.append((f"skills/{slug}/{path}", data))

            async def initialize(
                _row: Any, workspace: Any, uploads: list[tuple[str, bytes]] = files
            ) -> None:
                if uploads:
                    await workspace.aupload_many(uploads)

            target = mapping[expert.key]
            created.append(target)  # before await: even a partially failed create is ours to clean.
            row = await self.service.agents.create(
                AgentCreateSpec(
                    agent_id=target,
                    name=name,
                    user_id=user_id,
                    description=expert.description,
                    system_prompt=expert.instructions,
                    welcome_message=expert.welcome_message,
                    default_model=model,
                    kind=expert.kind,
                    member_ids=[mapping[key] for key in expert.members if key in mapping],
                    config={},
                    mcp_servers=[],
                    skill_package_ids=[],
                    knowledge_base_ids=[],
                ),
                workspace_initializer=initialize,
            )
            output.append({"agent_id": row.agent_id, "name": row.name, "source_key": expert.key})
        threads = []
        for key, target in mapping.items():
            if bundle.conversations.get(key):
                result = await self._history(
                    user_id,
                    preview_id,
                    target,
                    bundle.conversations[key],
                    "octop-transfer",
                    sha,
                    skip_duplicates=False,
                )
                threads.extend(result["threads"])
        if selection.include_workflows and bundle.workflows:
            await asyncio.to_thread(self.service.identity, user_id, "tasks")
            if self.service.task_manager is None:
                raise self.service.error("workflow_unavailable", user_id, 409)
            for raw in bundle.workflows:
                definition = dict(raw.get("definition") or {})
                steps = []
                for step in definition.get("steps", []):
                    if step.get("agent_id") not in mapping:
                        break
                    # Credentials, model overrides, attachments and approval bypass never cross hosts.
                    steps.append(
                        {
                            "key": step["key"],
                            "agent_id": mapping[step["agent_id"]],
                            "title": step["title"],
                            "prompt": step["prompt"],
                            "depends_on": step.get("depends_on", []),
                        }
                    )
                else:
                    definition["steps"] = steps
                    name = str(raw.get("name") or "").strip()
                    if not name:
                        raise self.service.error("invalid_name", user_id)
                    await self.service.task_manager.create_workflow(
                        user_id,
                        name=name[:200],
                        definition=WorkflowDefinition.model_validate(definition),
                        enabled=False,
                    )
                    continue
                warnings.append("workflow_member_missing")
        return {
            "agents": output,
            "threads": threads,
            "skipped": 0,
            "warnings": sorted(set(warnings)),
        }

    async def export(self, user_id: int, selection: ExportSelection) -> bytes:
        try:
            return await self._export(user_id, selection)
        except ConversationArchiveError as error:
            raise self.service.error(error.reason, user_id) from None

    async def _export(self, user_id: int, selection: ExportSelection) -> bytes:
        user = await asyncio.to_thread(self.service.identity, user_id, "experts")
        files: dict[str, bytes] = {}
        agents = []
        conversations: dict[str, list[PortableConversation]] = {}
        warnings = ["identity_stores_excluded"]

        def put(path: str, data: bytes) -> None:
            if (
                path in files
                or len(data) > MAX_ENTRY_BYTES
                or len(files) >= MAX_ARCHIVE_FILES
                or sum(map(len, files.values())) + len(data) > MAX_ARCHIVE_BYTES
            ):
                raise ConversationArchiveError("archive_limit")
            files[path] = data

        for agent_id in dict.fromkeys(selection.agent_ids):
            row = await asyncio.to_thread(self.service.owned_agent, user_id, agent_id)
            key = row.agent_id
            workspace = await asyncio.to_thread(self.service.agents.workspace_for_agent, agent_id)
            workspace_paths = []
            skills = []
            if selection.include_files and workspace is not None:
                for path, data in await self._workspace_files(workspace):
                    put(f"agents/{key}/workspace/{path}", data)
                    workspace_paths.append(path)
            if selection.include_skills and workspace is not None:
                await asyncio.to_thread(self.service.identity, user_id, "skills")
                listing = await workspace.als("skills")
                for entry in getattr(listing, "entries", None) or []:
                    raw_path = (
                        entry.get("path", "")
                        if isinstance(entry, dict)
                        else getattr(entry, "path", "")
                    )
                    if (
                        entry.get("is_symlink")
                        if isinstance(entry, dict)
                        else getattr(entry, "is_symlink", False)
                    ):
                        continue
                    slug = PurePosixPath(str(raw_path)).name
                    if not slug or slug.startswith("."):
                        continue
                    manifest = await workspace.aread_text(f"skills/{slug}/SKILL.md")
                    if manifest is None:
                        continue
                    metadata, _ = parse_frontmatter(manifest)
                    origin = metadata.get("origin")
                    if origin:
                        source = await asyncio.to_thread(
                            self.service.repos.skill_package_repo.get, str(origin)
                        )
                        store = self.service.skill_store
                        if (
                            source is None
                            or store is None
                            or not store.can_copy(source, user)
                            or not store.can_download(source, user)
                        ):
                            warnings.append("skill_policy_omitted")
                            continue
                    for path, data in await read_workspace_skill_files(workspace, slug):
                        if not portable_workspace_path(path):
                            warnings.append("sensitive_file_omitted")
                            continue
                        put(f"agents/{key}/skills/{slug}/{path}", data)
                    skills.append(slug)
            members = []
            if row.kind == "team":
                team = getattr(self.service.agents, "teams", None)
                if team is not None:
                    source_members = await asyncio.to_thread(team.member_ids, agent_id)
                    members = [mid for mid in source_members if mid in selection.agent_ids]
            agents.append(
                PortableExpert(
                    key=key,
                    name=row.name,
                    description=redact_config_text(row.description or ""),
                    instructions=redact_config_text(row.system_prompt or ""),
                    welcome_message=redact_config_text(row.welcome_message or ""),
                    kind=row.kind,
                    workspace_files=workspace_paths,
                    skills=skills,
                    members=members,
                )
            )
            if selection.include_conversations:
                histories = []
                pairs = await asyncio.to_thread(
                    self.service.repos.thread_repo.list_for_user, user_id
                )
                for aid, thread_id in pairs:
                    if aid != agent_id:
                        continue
                    thread = await asyncio.to_thread(self.service.owned, user_id, thread_id)
                    if self.service.archive is not None:
                        wires = await export_messages(
                            self.service.archive, self.service.agents, aid, thread_id
                        )
                    else:
                        wires = []
                        cursor = None
                        for _ in range(100):
                            page = await self.service._read_page(
                                aid, thread_id, limit=100, cursor=cursor
                            )
                            wires = [*page["messages"], *wires]
                            if not page["has_more"]:
                                break
                            cursor = page["next_cursor"]
                    normalized = []
                    for wire in wires:
                        data = wire.get("data", wire)
                        role = {"human": "user", "ai": "assistant"}.get(
                            wire.get("type"), data.get("role")
                        )
                        content = data.get("content")
                        if role in {"user", "assistant"} and isinstance(content, str) and content:
                            normalized.append(
                                PortableMessage.model_validate(
                                    {
                                        "role": role,
                                        "content": content,
                                        "external_id": str(data.get("id") or "")[:300] or None,
                                    }
                                )
                            )
                    histories.append(
                        PortableConversation(
                            external_id=thread_id,
                            title=thread.title or thread_id,
                            messages=normalized,
                        )
                    )
                conversations[key] = histories
        workflows = []
        if selection.include_workflows:
            await asyncio.to_thread(self.service.identity, user_id, "tasks")
            for workflow in await asyncio.to_thread(
                self.service.repos.task_repo.workflows, user_id
            ):
                definition = WorkflowDefinition.model_validate_json(workflow.definition_json)
                if all(step.agent_id in selection.agent_ids for step in definition.steps):
                    safe = definition.model_dump()
                    for step in safe["steps"]:
                        step["options"] = {}
                        step["prompt"] = redact_config_text(step["prompt"])
                    workflows.append({"name": workflow.name, "definition": safe})
        bundle = PortableBundle(
            agents=agents,
            conversations=conversations,
            workflows=workflows,
            warnings=sorted(set(warnings)),
        )
        put("octop-transfer.json", bundle.model_dump_json().encode())
        if (
            len(files) > MAX_ARCHIVE_FILES
            or sum(len(data) for data in files.values()) > MAX_ARCHIVE_BYTES
        ):
            raise self.service.error("archive_limit", user_id)
        return await asyncio.to_thread(self._zip, files)

    @staticmethod
    def _zip(files: dict[str, bytes]) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
            for name, data in files.items():
                archive.writestr(name, data)
        return buffer.getvalue()

    @staticmethod
    async def _workspace_files(workspace: Any) -> list[tuple[str, bytes]]:
        pending = ["."]
        visited: set[str] = set()
        files: list[tuple[str, bytes]] = []
        total = 0
        while pending:
            current = pending.pop()
            if current in visited or len(visited) >= MAX_ARCHIVE_FILES:
                raise ConversationArchiveError("unsafe_archive")
            visited.add(current)
            listing = await workspace.als(current)
            for entry in getattr(listing, "entries", None) or []:

                def value(name: str, source: Any = entry) -> Any:
                    return (
                        source.get(name)
                        if isinstance(source, dict)
                        else getattr(source, name, None)
                    )

                name = PurePosixPath(str(value("path") or "")).name
                path = f"{current}/{name}" if current != "." else name
                if (
                    not name
                    or path.startswith("skills/")
                    or path == "skills"
                    or not portable_workspace_path(path)
                    or value("is_symlink")
                ):
                    continue
                if value("is_dir"):
                    pending.append(path)
                else:
                    if isinstance(value("size"), int) and value("size") > MAX_ENTRY_BYTES:
                        raise ConversationArchiveError("archive_limit")
                    data = await workspace.adownload_bytes(path)
                    if data is not None:
                        total += len(data)
                        if (
                            len(data) > MAX_ENTRY_BYTES
                            or total > MAX_ARCHIVE_BYTES
                            or len(files) >= MAX_ARCHIVE_FILES
                        ):
                            raise ConversationArchiveError("archive_limit")
                        files.append((path, data))
        return files
