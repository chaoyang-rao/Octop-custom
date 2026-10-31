"""Conversation annotations and insert-only import staging (SQL only)."""

from __future__ import annotations

import json
from typing import Any

from octop.infra.db.pool import DatabasePool
from octop.infra.db.repos._base import now_ts
from octop.infra.db.repos.threads import ThreadRow, clip_thread_title


class ConversationRepo:
    def __init__(self, db: DatabasePool) -> None:
        self._db = db

    def browse(
        self, user_id: int, *, archived: bool, agent_id: str, query: str, limit: int, offset: int
    ) -> list[ThreadRow]:
        sql = "SELECT t.* FROM threads t WHERE t.user_id=? AND t.archived=?"
        args: list[object] = [user_id, int(archived)]
        if agent_id:
            sql += " AND t.agent_id=?"
            args.append(agent_id)
        if query:
            sql += " AND LOWER(COALESCE(t.title,'')) LIKE ? ESCAPE '!'"
            escaped = query.casefold().replace("!", "!!").replace("%", "!%").replace("_", "!_")
            args.append(f"%{escaped}%")
        sql += " ORDER BY t.last_active DESC,t.created_at DESC,t.thread_id DESC LIMIT ? OFFSET ?"
        args.extend((limit, offset))
        with self._db.connect() as conn:
            return [ThreadRow.from_row(row) for row in conn.execute(sql, args).fetchall()]

    def reactions(self, user_id: int, thread_id: str) -> list[dict[str, Any]]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT message_key,message_digest,message_role,emoji,created_at FROM conversation_reactions "
                "WHERE thread_id=? AND user_id=? ORDER BY id",
                (thread_id, user_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def react(
        self,
        *,
        reaction_id: str,
        user_id: int,
        thread_id: str,
        message_key: str,
        digest: str,
        role: str,
        emoji: str,
        active: bool,
    ) -> None:
        with self._db.transaction() as conn:
            if active:
                conn.execute(
                    "INSERT INTO conversation_reactions "
                    "(reaction_id,thread_id,message_key,message_digest,message_role,user_id,emoji,created_at) "
                    "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(thread_id,message_key,user_id,emoji) DO NOTHING",
                    (reaction_id, thread_id, message_key, digest, role, user_id, emoji, now_ts()),
                )
            else:
                conn.execute(
                    "DELETE FROM conversation_reactions WHERE thread_id=? AND user_id=? AND message_key=? AND emoji=?",
                    (thread_id, user_id, message_key, emoji),
                )

    def origin(self, thread_id: str) -> dict[str, Any] | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT source,external_id,source_archive_sha256,source_title,source_thread_id,imported_at "
                "FROM conversation_origins WHERE thread_id=?",
                (thread_id,),
            ).fetchone()
        return dict(row) if row else None

    def set_origin(
        self,
        *,
        origin_id: str,
        user_id: int,
        thread_id: str,
        source: str,
        external_id: str,
        archive_sha: str | None = None,
        source_title: str | None = None,
        source_thread: str | None = None,
    ) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO conversation_origins "
                "(origin_id,thread_id,user_id,source,external_id,source_archive_sha256,source_title,source_thread_id,imported_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    origin_id,
                    thread_id,
                    user_id,
                    source,
                    external_id,
                    archive_sha,
                    source_title,
                    source_thread,
                    now_ts(),
                ),
            )

    def imported_ids(self, user_id: int, source: str) -> set[str]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT external_id FROM conversation_origins WHERE user_id=? AND source=?",
                (user_id, source),
            ).fetchall()
        return {str(row["external_id"]) for row in rows}

    def stage(self, *, preview_id: str, user_id: int, kind: str, sha: str, payload: str) -> None:
        with self._db.transaction() as conn:
            # Preview payloads are private user data and expire independently of imports.
            conn.execute(
                "DELETE FROM conversation_import_previews WHERE expires_at<? AND state!='importing'",
                (now_ts(),),
            )
            conn.execute(
                "INSERT INTO conversation_import_previews "
                "(preview_id,user_id,kind,source_sha256,payload_json,state,created_at,expires_at) "
                "VALUES (?,?,?,?,?,'preview',?,?)",
                (preview_id, user_id, kind, sha, payload, now_ts(), now_ts() + 1800),
            )

    def preview(self, preview_id: str, user_id: int) -> dict[str, Any] | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM conversation_import_previews WHERE preview_id=? AND user_id=? AND expires_at>=?",
                (preview_id, user_id, now_ts()),
            ).fetchone()
        return dict(row) if row else None

    def discard(self, preview_id: str, user_id: int) -> bool:
        with self._db.transaction() as conn:
            cur = conn.execute(
                "DELETE FROM conversation_import_previews WHERE preview_id=? AND user_id=? AND state!='importing'",
                (preview_id, user_id),
            )
        return bool(cur.rowcount)

    def claim_preview(self, preview_id: str, user_id: int) -> bool:
        with self._db.transaction() as conn:
            cur = conn.execute(
                "UPDATE conversation_import_previews SET state='importing' "
                "WHERE preview_id=? AND user_id=? AND state='preview' AND expires_at>=?",
                (preview_id, user_id, now_ts()),
            )
        return bool(cur.rowcount)

    def finish_preview(self, preview_id: str, user_id: int, *, success: bool) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE conversation_import_previews SET state=?,payload_json='{}' WHERE preview_id=? AND user_id=? AND state='importing'",
                ("imported" if success else "failed", preview_id, user_id),
            )

    def import_history(
        self,
        *,
        preview_id: str,
        user_id: int,
        source: str,
        sha: str,
        rows: list[dict[str, Any]],
    ) -> None:
        """A selected history batch is inserted atomically, never merged into existing chats."""
        ts = now_ts()
        with self._db.transaction() as conn:
            preview = conn.execute(
                "SELECT 1 FROM conversation_import_previews WHERE preview_id=? AND user_id=? AND state='importing'",
                (preview_id, user_id),
            ).fetchone()
            if not preview:
                raise ValueError("stale import preview")
            for row in rows:
                conn.execute(
                    "INSERT INTO threads(thread_id,agent_id,user_id,channel_type,session_key,title,last_active,created_at,archived) "
                    "VALUES (?,?,?,'dashboard',?,?,?,?,?)",
                    (
                        row["thread_id"],
                        row["agent_id"],
                        user_id,
                        row["session_key"],
                        clip_thread_title(row["title"]),
                        ts,
                        ts,
                        int(row.get("archived", False)),
                    ),
                )
                conn.execute(
                    "INSERT INTO thread_history_projection(thread_id,status,updated_at,error) VALUES (?,'ready',?,NULL)",
                    (row["thread_id"], ts),
                )
                for seq, wire in enumerate(row["messages"], 1):
                    conn.execute(
                        "INSERT INTO thread_messages(thread_id,seq,message_id,role,message_json,created_at) VALUES (?,?,?,?,?,?)",
                        (
                            row["thread_id"],
                            seq,
                            wire["data"]["id"],
                            wire["type"],
                            json.dumps(wire, ensure_ascii=False),
                            ts,
                        ),
                    )
                conn.execute(
                    "INSERT INTO conversation_origins "
                    "(origin_id,thread_id,user_id,source,external_id,source_archive_sha256,source_title,imported_at) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        row["origin_id"],
                        row["thread_id"],
                        user_id,
                        source,
                        row["external_id"],
                        sha,
                        row["title"],
                        ts,
                    ),
                )
