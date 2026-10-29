"""Threads table — conversation metadata for history listing and /resume."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from octop.infra.db.pool import DatabasePool
from octop.infra.db.repos._base import DbRow, bool_int, map_rows, now_ts
from octop.infra.utils.thread_artifact import (
    MAX_THREAD_ARTIFACTS,
    ThreadArtifact,
    merge_thread_artifacts,
    parse_thread_artifacts,
    serialize_thread_artifacts,
)

__all__ = [
    "MAX_THREAD_ARTIFACTS",
    "ThreadArtifact",
    "ThreadRepo",
    "ThreadRow",
    "clip_thread_title",
    "merge_thread_artifacts",
    "parse_thread_artifacts",
    "serialize_thread_artifacts",
]


@dataclass(frozen=True)
class ThreadRow:
    id: int
    thread_id: str
    agent_id: str
    user_id: int
    channel_type: str
    session_key: str
    title: str | None
    last_active: int
    created_at: int
    pinned: bool = False
    model_ref: str | None = None
    reasoning_mode: str | None = None
    reasoning_effort: str | None = None
    artifacts: tuple[ThreadArtifact, ...] = field(default_factory=tuple)
    conversation_mode: str | None = None
    pending_plan_path: str | None = None
    hitl_policy: str | None = None
    project_path: str | None = None
    project_name: str | None = None

    @classmethod
    def from_row(cls, r: DbRow) -> ThreadRow:
        try:
            raw_artifacts = r["artifacts"]
        except (KeyError, IndexError):
            raw_artifacts = None
        try:
            conversation_mode = r["conversation_mode"]
        except (KeyError, IndexError):
            conversation_mode = None
        try:
            pending_plan_path = r["pending_plan_path"]
        except (KeyError, IndexError):
            pending_plan_path = None
        try:
            hitl_policy = r["hitl_policy"]
        except (KeyError, IndexError):
            hitl_policy = None
        project_path = r["project_path"] if "project_path" in r.keys() else None
        project_name = r["project_name"] if "project_name" in r.keys() else None
        return cls(
            id=r["id"],
            thread_id=r["thread_id"],
            agent_id=r["agent_id"],
            user_id=r["user_id"],
            channel_type=r["channel_type"],
            session_key=r["session_key"],
            title=r["title"],
            last_active=r["last_active"],
            created_at=r["created_at"],
            pinned=bool(r["pinned"]),
            model_ref=r["model_ref"],
            reasoning_mode=r["reasoning_mode"],
            reasoning_effort=r["reasoning_effort"],
            artifacts=tuple(parse_thread_artifacts(raw_artifacts)),
            conversation_mode=str(conversation_mode) if conversation_mode else None,
            pending_plan_path=str(pending_plan_path) if pending_plan_path else None,
            hitl_policy=str(hitl_policy) if hitl_policy else None,
            project_path=str(project_path) if project_path else None,
            project_name=str(project_name) if project_name else None,
        )


def clip_thread_title(title: str, *, max_len: int = 40) -> str:
    """Bound stored thread titles; longer names end with an ellipsis.

    Whitespace is collapsed so auto-titles from multi-line messages stay tidy.
    Exact-length titles (no longer source) are kept without forcing ``…``.
    """
    text = " ".join((title or "").split())
    if not text:
        return ""
    if max_len <= 1:
        return "…"
    if len(text) <= max_len:
        return text
    return f"{text[: max_len - 1].rstrip()}…"


def repair_legacy_thread_title(title: str | None, *, max_len: int = 40) -> str | None:
    """Rewrite hard-cut titles that hit the cap without an ellipsis.

    Pre-clipping storage truncated at ``max_len`` with no ``…``. New writes
    from :func:`clip_thread_title` always end with ``…`` when shortened.
    Title-repair migration and optional repo helpers use this.

    Legitimate full-length titles of exactly ``max_len`` without ellipsis are
    indistinguishable and get the same rewrite once during migration — rare.
    """
    if title is None:
        return None
    text = " ".join(title.split())
    if not text:
        return None
    if text.endswith("…") or text.endswith("..."):
        fixed = clip_thread_title(text, max_len=max_len)
        return fixed or None
    if len(text) == max_len:
        return f"{text[: max_len - 1].rstrip()}…"
    fixed = clip_thread_title(text, max_len=max_len)
    return fixed or None


def repair_all_legacy_thread_titles(db: DatabasePool) -> int:
    """Persist :func:`repair_legacy_thread_title` for every row. Returns update count."""
    updated = 0
    with db.transaction() as conn:
        rows = conn.execute(
            "SELECT thread_id, title FROM threads WHERE title IS NOT NULL"
        ).fetchall()
        for r in rows:
            thread_id = str(r["thread_id"])
            title = r["title"]
            fixed = repair_legacy_thread_title(title if isinstance(title, str) else str(title))
            if fixed is not None and fixed != title:
                conn.execute(
                    "UPDATE threads SET title = ? WHERE thread_id = ?",
                    (fixed, thread_id),
                )
                updated += 1
    return updated


class ThreadRepo:
    def __init__(self, db: DatabasePool) -> None:
        self._db = db

    def insert(
        self,
        *,
        thread_id: str,
        agent_id: str,
        user_id: int,
        channel_type: str,
        session_key: str,
        title: str | None = None,
        last_active: int | None = None,
        project_path: str | None = None,
        project_name: str | None = None,
    ) -> None:
        ts = now_ts()
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO threads(thread_id, agent_id, user_id, channel_type, "
                "session_key, title, last_active, created_at, project_path, project_name) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    thread_id,
                    agent_id,
                    user_id,
                    channel_type,
                    session_key,
                    clip_thread_title(title) if title else None,
                    ts if last_active is None else last_active,
                    ts,
                    project_path,
                    project_name,
                ),
            )
            if project_path:
                self._upsert_project(conn, agent_id, user_id, project_path, project_name)
            conn.execute(
                "INSERT INTO thread_history_projection(thread_id, status, updated_at, error) "
                "VALUES (?, 'ready', ?, NULL) ON CONFLICT(thread_id) DO NOTHING",
                (thread_id, ts),
            )

    @staticmethod
    def _upsert_project(
        conn: Any, agent_id: str, user_id: int, project_path: str, project_name: str | None
    ) -> str:
        existing = conn.execute(
            "SELECT project_name FROM thread_projects WHERE agent_id = ? AND user_id = ? "
            "AND project_path = ?",
            (agent_id, user_id, project_path),
        ).fetchone()
        name = (project_name or "").strip() or (
            str(existing["project_name"]) if existing else Path(project_path).name or project_path
        )
        conn.execute(
            "INSERT INTO thread_projects(agent_id, user_id, project_path, project_name, created_at) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(agent_id, user_id, project_path) "
            "DO UPDATE SET project_name = excluded.project_name",
            (agent_id, user_id, project_path, name, now_ts()),
        )
        conn.execute(
            "UPDATE threads SET project_name = ? WHERE agent_id = ? AND user_id = ? "
            "AND project_path = ?",
            (name, agent_id, user_id, project_path),
        )
        return name

    def upsert_project(
        self, *, agent_id: str, user_id: int, project_path: str, project_name: str | None = None
    ) -> dict[str, object]:
        with self._db.transaction() as conn:
            self._upsert_project(conn, agent_id, user_id, project_path, project_name)
            row = conn.execute(
                "SELECT project_path, project_name, created_at FROM thread_projects "
                "WHERE agent_id = ? AND user_id = ? AND project_path = ?",
                (agent_id, user_id, project_path),
            ).fetchone()
            count = conn.execute(
                "SELECT COUNT(*) FROM threads WHERE agent_id = ? AND user_id = ? AND project_path = ?",
                (agent_id, user_id, project_path),
            ).fetchone()[0]
            return {**dict(row), "thread_count": int(count)}

    def list_projects(self, *, agent_id: str, user_id: int) -> list[dict[str, object]]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT p.project_path, p.project_name, p.created_at, COUNT(t.thread_id) AS thread_count "
                "FROM thread_projects p LEFT JOIN threads t ON t.agent_id = p.agent_id "
                "AND t.user_id = p.user_id AND t.project_path = p.project_path "
                "WHERE p.agent_id = ? AND p.user_id = ? "
                "GROUP BY p.project_path, p.project_name, p.created_at "
                "ORDER BY p.created_at, p.project_path",
                (agent_id, user_id),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_project_threads(
        self, *, agent_id: str, user_id: int, project_path: str
    ) -> list[ThreadRow]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM threads WHERE agent_id = ? AND user_id = ? AND project_path = ?",
                (agent_id, user_id, project_path),
            ).fetchall()
        return map_rows(rows, ThreadRow)

    def set_project(
        self,
        thread_id: str,
        *,
        agent_id: str,
        user_id: int,
        project_path: str | None,
        project_name: str | None = None,
    ) -> None:
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT thread_id FROM threads WHERE thread_id = ? AND agent_id = ? AND user_id = ?",
                (thread_id, agent_id, user_id),
            ).fetchone()
            if row is None:
                raise ValueError("thread not owned by user and agent")
            name = (
                self._upsert_project(conn, agent_id, user_id, project_path, project_name)
                if project_path else None
            )
            conn.execute(
                "UPDATE threads SET project_path = ?, project_name = ? "
                "WHERE thread_id = ? AND agent_id = ? AND user_id = ?",
                (project_path, name, thread_id, agent_id, user_id),
            )

    def delete_project(self, *, agent_id: str, user_id: int, project_path: str) -> int:
        """Remove only grouping metadata. Never touch the referenced filesystem."""
        with self._db.transaction() as conn:
            cursor = conn.execute(
                "UPDATE threads SET project_path = NULL, project_name = NULL "
                "WHERE agent_id = ? AND user_id = ? AND project_path = ?",
                (agent_id, user_id, project_path),
            )
            count = cursor.rowcount
            conn.execute(
                "DELETE FROM thread_projects WHERE agent_id = ? AND user_id = ? AND project_path = ?",
                (agent_id, user_id, project_path),
            )
        return count

    def get(self, thread_id: str) -> ThreadRow | None:
        with self._db.connect() as conn:
            r = conn.execute("SELECT * FROM threads WHERE thread_id = ?", (thread_id,)).fetchone()
        return ThreadRow.from_row(r) if r else None

    def list_ids_for_agent(self, agent_id: str) -> set[str]:
        """Every thread id stored for ``agent_id``, with no row cap."""
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT thread_id FROM threads WHERE agent_id = ?",
                (agent_id,),
            ).fetchall()
        return {str(row["thread_id"]) for row in rows}

    def list_for_user(self, user_id: int) -> list[tuple[str, str]]:
        """``(agent_id, thread_id)`` pairs owned by ``user_id``."""
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT agent_id, thread_id FROM threads WHERE user_id = ?",
                (user_id,),
            ).fetchall()
        return [(str(row["agent_id"]), str(row["thread_id"])) for row in rows]

    def list_by_agent(self, *, agent_id: str, limit: int = 50) -> list[ThreadRow]:
        # last_active=0 is "no turns yet" (has_messages sentinel). Fall back to
        # created_at so brand-new empty threads sort to the top of the sidebar
        # instead of sinking below every previously active chat.
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM threads WHERE agent_id = ? "
                "ORDER BY pinned DESC, "
                "CASE WHEN last_active > 0 THEN last_active ELSE created_at END DESC, "
                "thread_id DESC LIMIT ?",
                (agent_id, limit),
            ).fetchall()
        return map_rows(rows, ThreadRow)

    def list_by_agent_user(
        self, *, agent_id: str, user_id: int, limit: int = 50
    ) -> list[ThreadRow]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM threads WHERE agent_id = ? AND user_id = ? "
                "ORDER BY pinned DESC, "
                "CASE WHEN last_active > 0 THEN last_active ELSE created_at END DESC, "
                "thread_id DESC LIMIT ?",
                (agent_id, user_id, limit),
            ).fetchall()
        return map_rows(rows, ThreadRow)

    def list_by_session(self, *, session_key: str, limit: int = 50) -> list[ThreadRow]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM threads WHERE session_key = ? "
                "ORDER BY "
                "CASE WHEN last_active > 0 THEN last_active ELSE created_at END DESC, "
                "thread_id DESC LIMIT ?",
                (session_key, limit),
            ).fetchall()
        return map_rows(rows, ThreadRow)

    def set_title_if_null(self, thread_id: str, title: str) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE threads SET title = ? WHERE thread_id = ? AND title IS NULL",
                (clip_thread_title(title), thread_id),
            )

    def update_title(self, thread_id: str, title: str) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE threads SET title = ? WHERE thread_id = ?",
                (clip_thread_title(title), thread_id),
            )

    def set_pinned(self, thread_id: str, pinned: bool) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE threads SET pinned = ? WHERE thread_id = ?",
                (bool_int(pinned), thread_id),
            )

    def update_composer(
        self,
        thread_id: str,
        *,
        model_ref: str | None | object = ...,
        reasoning_mode: str | None | object = ...,
        reasoning_effort: str | None | object = ...,
        conversation_mode: str | None | object = ...,
        pending_plan_path: str | None | object = ...,
        hitl_policy: str | None | object = ...,
    ) -> None:
        fields: list[str] = []
        params: list[object] = []
        for column, value in (
            ("model_ref", model_ref),
            ("reasoning_mode", reasoning_mode),
            ("reasoning_effort", reasoning_effort),
            ("conversation_mode", conversation_mode),
            ("pending_plan_path", pending_plan_path),
            ("hitl_policy", hitl_policy),
        ):
            if value is ...:
                continue
            fields.append(f"{column} = ?")
            params.append(value)
        if not fields:
            return
        params.append(thread_id)
        with self._db.transaction() as conn:
            conn.execute(
                f"UPDATE threads SET {', '.join(fields)} WHERE thread_id = ?",
                params,
            )

    def touch_last_active(self, thread_id: str) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE threads SET last_active = ? WHERE thread_id = ?",
                (now_ts(), thread_id),
            )

    def append_artifacts(
        self,
        thread_id: str,
        paths: Sequence[str],
        *,
        agent_id: str = "",
    ) -> None:
        aid = (agent_id or "").strip()
        incoming = [
            ThreadArtifact(path=p.strip(), agent_id=aid)
            for p in paths
            if isinstance(p, str) and p.strip()
        ]
        if not incoming:
            return
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT artifacts FROM threads WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
            if row is None:
                return
            current = parse_thread_artifacts(row["artifacts"])
            merged = merge_thread_artifacts(current, incoming)
            if merged == current:
                return
            conn.execute(
                "UPDATE threads SET artifacts = ? WHERE thread_id = ?",
                (
                    json.dumps(serialize_thread_artifacts(merged), ensure_ascii=False),
                    thread_id,
                ),
            )

    def delete(self, thread_id: str) -> None:
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM threads WHERE thread_id = ?", (thread_id,))
