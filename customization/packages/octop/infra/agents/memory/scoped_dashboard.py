"""Scope-authorized dashboard operations over octop-memory's public API."""

from __future__ import annotations

import json
from typing import Any, cast

from octop.infra.errors import ErrorCode, OctopError


class ScopedMemoryDashboard:
    def __init__(self, registry: Any, repos: Any, teams: Any) -> None:
        self._registry, self._repos, self._teams = registry, repos, teams

    @staticmethod
    def _rpc(memory: Any, method: str, **params: Any) -> dict[str, Any]:
        from octop_memory.adapters.bridge.handlers import Bridge

        result = Bridge(memory).handle(
            {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        )
        if "error" in result:
            raise OctopError.localized(ErrorCode.NOT_FOUND)
        return cast(dict[str, Any], result["result"])

    def _sources(self, memory: Any, atom_id: str, uid: int) -> list[dict[str, Any]]:
        atom = memory.get_atom(atom_id)
        if atom is None:
            return []
        sources = []
        for entry in memory.list_journal(target_atom_id=atom_id, limit=10):
            if entry.action != "user_edit":
                continue
            try:
                source = json.loads(entry.note).get("source", {})
            except ValueError:
                continue
            row = self._repos.thread_repo.get(source.get("thread_id", ""))
            if row is not None and row.user_id == uid:
                sources.append(
                    {
                        "thread_id": row.thread_id,
                        "agent_id": row.agent_id,
                        "title": row.title or row.thread_id,
                        "message_id": source.get("message_id"),
                        "created_at": entry.timestamp.isoformat(),
                        "origin": source.get("origin", "user"),
                    }
                )
        for raw in memory.get_raw_events_by_ids(atom.raw_event_ids[:5]):
            metadata = raw.payload.get("metadata", {})
            source = dict(metadata.get("source", {}))
            tid = str(source.get("thread_id") or raw.thread_id or "")
            row = self._repos.thread_repo.get(tid)
            if row is None or row.user_id != uid:
                continue
            sources.append(
                {
                    "thread_id": tid,
                    "agent_id": row.agent_id,
                    "title": row.title or tid,
                    "message_id": source.get("message_id"),
                    "created_at": raw.timestamp.isoformat(),
                    "origin": source.get("origin")
                    or ("user_message" if raw.event_type == "user_message" else "conversation"),
                }
            )
        return sources

    def execute(
        self, agent_id: str, thread_id: str, user_id: int, operation: str, **params: Any
    ) -> dict[str, Any]:
        thread = self._repos.thread_repo.get(thread_id)
        row = self._repos.agent_repo.get(agent_id)
        if (
            thread is None
            or thread.user_id != user_id
            or thread.agent_id != agent_id
            or row is None
        ):
            raise OctopError.localized(ErrorCode.FORBIDDEN)
        actor_id = self._teams.require_primary(user_id).agent_id if row.kind == "team" else agent_id
        harness = self._registry.get_agent(actor_id)
        try:
            view = harness.memory_for_context({"thread_id": thread_id, "user": str(user_id)})
        except PermissionError:
            raise OctopError.localized(ErrorCode.FORBIDDEN) from None
        except (AttributeError, ValueError):
            raise OctopError.localized(ErrorCode.MEMORY_SCOPE_UNAVAILABLE) from None
        scope = params.pop("scope", "auto")
        scope = view.context["default_scope"] if scope == "auto" else scope
        if scope not in view.context["scopes"]:
            raise OctopError.localized(ErrorCode.FORBIDDEN)
        expected = params.pop("expected_scope_token", None)
        scope_token = view.context["scopes"][scope]["namespace"]
        if expected is not None and expected != scope_token:
            raise OctopError.localized(ErrorCode.MEMORY_REVISION_CONFLICT)
        service = view.owner.open(scope, view.context)
        memory = service.memory
        if operation == "list":
            result = self._rpc(memory, "list_atoms", limit=20, **params)
            for atom in result["items"]:
                atom["sources"] = self._sources(memory, atom["id"], user_id)
            return {
                **result,
                "scope": scope,
                "scope_token": scope_token,
                "default_scope": view.context["default_scope"],
                "available_scopes": list(view.context["scopes"]),
                "project_name": view.source.get("project_name"),
            }
        if operation == "save":
            try:
                return cast(dict[str, Any], view.save(scope=scope, user_action=True, **params))
            except ValueError:
                raise OctopError.localized(ErrorCode.MEMORY_REVISION_CONFLICT) from None
        if operation == "deprecate":
            return self._rpc(memory, "deprecate_atom", actor="user", **params)
        if operation == "revisions":
            atom_id = params["atom_id"]
            atom = memory.get_atom(atom_id)
            if atom is None:
                raise OctopError.localized(ErrorCode.NOT_FOUND)
            # Successor links are provided by octop-memory; retain the original
            # source and show the journal for this atom, including corrections.
            result = self._rpc(memory, "list_journal", target_entity_id=atom.entity_id, limit=500)
            related = {atom_id}
            while True:
                previous_size = len(related)
                for item in result["items"]:
                    ids = {
                        item.get("target_atom_id"),
                        (item.get("before") or {}).get("atom_id"),
                        (item.get("after") or {}).get("atom_id"),
                    } - {None}
                    if ids & related:
                        related.update(ids)
                if len(related) == previous_size:
                    break
            result["items"] = [
                item for item in result["items"] if item.get("target_atom_id") in related
            ]
            result["total"] = len(result["items"])
            for item in result["items"]:
                # Notes may carry our source JSON; no raw storage configuration.
                note = item.get("note") or ""
                try:
                    item["source"] = json.loads(note).get("source")
                except (ValueError, AttributeError):
                    item["source"] = None
            return result
        raise ValueError("unknown scoped memory operation")
