"""SQL-only persistence of task origins, code delivery and return receipts."""

from __future__ import annotations

import json
from typing import Any

from octop.infra.db.pool import DatabasePool

_CURRENT_EVENT = (
    "COALESCE((SELECT MAX(e.id) FROM task_events e WHERE e.task_id=d.task_id "
    "AND e.action NOT IN ('archive','restore','reassign')),0)"
)
_COLUMNS = (
    "d.task_id,d.origin_agent_id,d.origin_thread_id,d.parent_task_id,d.parent_attempt,d.scope_id,d.coding_spec_json,"
    "d.coding_run_json,d.returned_attempt,d.returned_state,d.returned_event_id,"
    + _CURRENT_EVENT
    + " AS current_event_id"
)


def _record(row: Any) -> dict[str, Any]:
    data = dict(row)
    specification = data.pop("coding_spec_json")
    data["coding_spec"] = json.loads(specification) if specification is not None else None
    data["coding_run"] = json.loads(data.pop("coding_run_json"))
    return data


class TaskDispatchRepo:
    def __init__(self, db: DatabasePool) -> None:
        self._db = db

    def get(self, task_id: str) -> dict[str, Any] | None:
        with self._db.connect() as conn:
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM task_dispatch_context d WHERE d.task_id=?", (task_id,)
            ).fetchone()
        return _record(row) if row else None

    def get_many(self, task_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not task_ids:
            return {}
        records: dict[str, dict[str, Any]] = {}
        with self._db.connect() as conn:
            for start in range(0, len(task_ids), 500):
                batch = task_ids[start : start + 500]
                placeholders = ",".join("?" for _ in batch)
                rows = conn.execute(
                    f"SELECT {_COLUMNS} FROM task_dispatch_context d "
                    f"WHERE d.task_id IN ({placeholders})",
                    batch,
                ).fetchall()
                records.update((str(row["task_id"]), _record(row)) for row in rows)
        return records

    def children(self, parent_task_id: str, parent_attempt: int) -> list[str]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT d.task_id FROM task_dispatch_context d "
                "JOIN agent_tasks t ON t.task_id=d.task_id "
                "WHERE d.parent_task_id=? AND d.parent_attempt=? ORDER BY t.id",
                (parent_task_id, parent_attempt),
            ).fetchall()
        return [str(row["task_id"]) for row in rows]

    def update_coding(
        self,
        task_id: str,
        coding_run: dict[str, Any],
        *,
        expected_attempt: int | None = None,
        expected_states: set[str] | None = None,
    ) -> bool:
        sql = "UPDATE task_dispatch_context SET coding_run_json=? WHERE task_id=?"
        values: list[object] = [json.dumps(coding_run, ensure_ascii=False), task_id]
        if expected_attempt is not None:
            sql += " AND EXISTS (SELECT 1 FROM agent_tasks t WHERE t.task_id=? AND t.attempt=?)"
            values.extend((task_id, expected_attempt))
        if expected_states is not None:
            if not expected_states:
                return False
            placeholders = ",".join("?" for _ in expected_states)
            sql += (
                " AND EXISTS (SELECT 1 FROM agent_tasks t "
                f"WHERE t.task_id=? AND t.state IN ({placeholders}))"
            )
            values.extend((task_id, *sorted(expected_states)))
        with self._db.transaction() as conn:
            return bool(conn.execute(sql, values).rowcount)

    def mark_returned(
        self,
        task_id: str,
        attempt: int,
        *,
        state: str,
        event_id: int | None = None,
        expected_attempt: int | None = None,
    ) -> bool:
        sql = (
            "UPDATE task_dispatch_context SET returned_attempt=?,returned_state=?,returned_event_id=? "
            "WHERE task_id=? AND returned_event_id<? "
            "AND EXISTS (SELECT 1 FROM agent_tasks t "
            "WHERE t.task_id=? AND t.attempt=? AND t.state=? AND t.archived=0 "
            "AND COALESCE((SELECT MAX(e.id) FROM task_events e WHERE e.task_id=t.task_id "
            "AND e.action NOT IN ('archive','restore','reassign')),0)=?)"
        )
        with self._db.transaction() as conn:
            if event_id is None:
                row = conn.execute(
                    "SELECT COALESCE(MAX(id),0) AS event_id FROM task_events WHERE task_id=? "
                    "AND action NOT IN ('archive','restore','reassign')",
                    (task_id,),
                ).fetchone()
                event_id = int(row["event_id"])
            values: list[object] = [
                attempt,
                state,
                event_id,
                task_id,
                event_id,
                task_id,
                attempt,
                state,
                event_id,
            ]
            if expected_attempt is not None:
                sql += " AND EXISTS (SELECT 1 FROM agent_tasks t WHERE t.task_id=? AND t.attempt=?)"
                values.extend((task_id, expected_attempt))
            return bool(conn.execute(sql, values).rowcount)

    def pending_returns(
        self, user_id: int | None = None, *, limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        sql = (
            f"SELECT {_COLUMNS} FROM task_dispatch_context d "
            "JOIN agent_tasks t ON t.task_id=d.task_id "
            "WHERE d.origin_thread_id IS NOT NULL AND t.archived=0 "
            "AND t.state IN ('completed','failed','cancelled','interrupted','waiting') "
            f"AND {_CURRENT_EVENT}>d.returned_event_id"
        )
        values: list[object] = []
        if user_id is not None:
            sql += " AND t.user_id=?"
            values.append(user_id)
        sql += " ORDER BY t.id LIMIT ? OFFSET ?"
        values.extend((limit, offset))
        with self._db.connect() as conn:
            return [_record(row) for row in conn.execute(sql, values).fetchall()]
