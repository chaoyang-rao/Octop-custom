"""Authorize memory scopes from persisted conversation bindings.

Octop owns identity and project membership. Storage, extraction, search and
revision history remain octop-memory services assembled by octop-harness.
"""

from __future__ import annotations

import hashlib
from typing import Any

from octop.infra.agents.teams.primary import current_primary_room, request_user_id
from octop.infra.users.groups import expert_visible_to
from octop.infra.utils.paths import PathLayout


class MemoryScopePolicy:
    def __init__(self, repos: Any, teams: Any, config: Any) -> None:
        self._repos = repos
        self._teams = teams
        self._config = config

    def resolve(self, actor_id: str, cfg: dict[str, Any]) -> dict[str, Any]:
        """Fail closed; neither model arguments nor project cwd grant access."""
        uid = request_user_id({"configurable": cfg})
        room = current_primary_room()
        thread_id = str(cfg.get("thread_id") or "")
        room_id = str(cfg.get("octop_team_thread_id") or "")
        if room is not None and actor_id == room.primary_id and thread_id == room.thread_id:
            room_id = room.thread_id
            uid = uid or room.user_id
        thread = self._repos.thread_repo.get(room_id or thread_id)
        actor = self._repos.agent_repo.get(actor_id)
        user = self._repos.user_repo.get(uid) if uid is not None else None
        if (
            uid is None
            or user is None
            or user.disabled
            or thread is None
            or thread.user_id != uid
            or actor is None
            or (actor.user_id != uid and not actor.is_shared)
        ):
            raise PermissionError("memory scope unavailable")
        if actor.user_id != uid and not expert_visible_to(
            self._repos, actor, user_id=uid, is_admin=False
        ):
            raise PermissionError("memory expert unavailable")
        if thread.agent_id != actor_id:
            owner = self._repos.agent_repo.get(thread.agent_id)
            if (
                owner is None
                or owner.kind != "team"
                or owner.user_id != uid
                or actor_id not in self._teams.visible_member_ids(owner.agent_id)
            ):
                raise PermissionError("memory room unavailable")

        # project_path was canonicalized on binding. Do not substitute a task
        # worktree (execution cwd) or resolve it again after a folder is removed.
        project = str(thread.project_path or "")
        identities = {
            "user": f"user:{uid}",
            "expert": f"user:{uid}:expert:{actor_id}",
            "session": f"user:{uid}:thread:{thread.thread_id}",
        }
        if project:
            identities["project"] = f"user:{uid}:project:{project}"
        specs = {}
        for name, identity in identities.items():
            token = hashlib.sha256(identity.encode()).hexdigest()[:32]
            namespace = f"scope_{name}_{token}"
            if self._config.database.is_postgresql:
                backend = {"type": "postgres", "dsn": self._config.database.postgresql_conninfo()}
            else:
                backend = {
                    "type": "sqlite",
                    "db_path": str(
                        PathLayout.from_env().root / "shared-memory" / f"{namespace}.sqlite"
                    ),
                }
            specs[name] = {"namespace": namespace, "backend": backend}
        active = "project" if project else "expert"
        legacy_readable = actor.user_id == uid and not actor.is_shared
        recall_scopes = ["session", "user", active]
        if not project and legacy_readable:
            # Preserve the private expert's historical unbound behavior while
            # keeping unclassified memories out of project conversations.
            recall_scopes.append("legacy")
        return {
            "scopes": specs,
            "default_scope": active,
            # Unclassified/legacy expert memories never auto-enter a project.
            "recall_scopes": recall_scopes,
            "scope_id": specs[active]["namespace"],
            "legacy_readable": legacy_readable,
            "source": {
                "user_id": uid,
                "agent_id": actor_id,
                "thread_id": thread.thread_id,
                "room_agent_id": thread.agent_id,
                "project_path": project or None,
                "project_name": thread.project_name,
            },
        }
