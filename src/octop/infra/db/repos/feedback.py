"""Feedback persistence; author identity is supplied by the authenticated domain."""

from __future__ import annotations

from typing import Any

from octop.infra.db.pool import DatabasePool


class FeedbackRepo:
    def __init__(self, db: DatabasePool) -> None:
        self.db = db

    def create(self, values: dict[str, Any]) -> dict[str, Any]:
        columns = (
            "feedback_id",
            "submission_key",
            "user_id",
            "author_name",
            "section",
            "kind",
            "title",
            "content",
            "client_version",
            "client_platform",
            "created_at",
            "updated_at",
        )
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO feedback("
                + ",".join(columns)
                + ") VALUES("
                + ",".join("?" for _ in columns)
                + ") ON CONFLICT(user_id,submission_key) DO NOTHING",
                tuple(values[key] for key in columns),
            )
            row = conn.execute(
                "SELECT * FROM feedback WHERE user_id=? AND submission_key=?",
                (values["user_id"], values["submission_key"]),
            ).fetchone()
        return dict(row)

    def get(self, feedback_id: str) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM feedback WHERE feedback_id=?", (feedback_id,)
            ).fetchone()
        return dict(row) if row is not None else None

    def list(
        self,
        *,
        user_id: int | None = None,
        section: str | None = None,
        status: str | None = None,
        query: str = "",
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        conditions: list[str] = []
        args: list[Any] = []
        for name, value in (("user_id", user_id), ("section", section), ("status", status)):
            if value is not None:
                conditions.append(name + "=?")
                args.append(value)
        if query:
            conditions.append(
                "(LOWER(title) LIKE ? OR LOWER(content) LIKE ? OR LOWER(author_name) LIKE ?)"
            )
            args.extend(["%" + query.lower() + "%"] * 3)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        with self.db.connect() as conn:
            count = conn.execute("SELECT COUNT(*) AS total FROM feedback" + where, args).fetchone()
            rows = conn.execute(
                "SELECT * FROM feedback"
                + where
                + " ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?",
                (*args, limit, offset),
            ).fetchall()
        return [dict(row) for row in rows], int(count["total"])

    def update(
        self,
        feedback_id: str,
        *,
        expected_revision: int,
        status: str,
        reply: str,
        updated_at: int,
    ) -> bool:
        with self.db.transaction() as conn:
            result = conn.execute(
                "UPDATE feedback SET status=?,reply=?,updated_at=?,revision=revision+1 "
                "WHERE feedback_id=? AND revision=?",
                (status, reply, updated_at, feedback_id, expected_revision),
            )
        return bool(result.rowcount == 1)
