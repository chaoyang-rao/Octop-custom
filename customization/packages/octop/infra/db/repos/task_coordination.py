"""SQL-only state for bounded, explicitly scoped coordinator review turns."""

from __future__ import annotations

import json
from typing import Any

from octop.infra.db.pool import DatabasePool
from octop.infra.db.repos._base import now_ts


def _record(row: Any) -> dict[str, Any]:
    data = dict(row)
    data["id"] = str(data["scope_id"])
    data["allow_publish"] = bool(data["allow_publish"])
    return data


class TaskCoordinationRepo:
    def __init__(self, db: DatabasePool) -> None:
        self._db = db

    def ensure(self, scope: dict[str, Any]) -> dict[str, Any]:
        with self._db.transaction() as conn:
            origin = conn.execute(
                "SELECT 1 FROM threads WHERE thread_id=? AND agent_id=? AND user_id=?",
                (scope["origin_thread_id"], scope["origin_agent_id"], scope["user_id"]),
            ).fetchone()
            if origin is None:
                raise ValueError("coordination origin does not belong to the scope owner")
            timestamp = now_ts()
            conn.execute(
                "INSERT INTO task_coordination_scopes "
                "(scope_id,user_id,origin_agent_id,origin_thread_id,parent_task_id,parent_attempt,"
                "source_message_id,goal_text,allow_publish,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(scope_id) DO NOTHING",
                (
                    scope["scope_id"],
                    scope["user_id"],
                    scope["origin_agent_id"],
                    scope["origin_thread_id"],
                    scope.get("parent_task_id"),
                    scope.get("parent_attempt"),
                    scope.get("source_message_id", ""),
                    scope.get("goal_text", ""),
                    int(
                        scope.get("allow_publish") is True
                        and scope.get("initial_user_turn") is True
                    ),
                    timestamp,
                    timestamp,
                ),
            )
            row = conn.execute(
                "SELECT * FROM task_coordination_scopes WHERE scope_id=?", (scope["scope_id"],)
            ).fetchone()
            if any(
                row[name] != scope.get(name)
                for name in (
                    "user_id",
                    "origin_agent_id",
                    "origin_thread_id",
                    "parent_task_id",
                    "parent_attempt",
                )
            ):
                raise ValueError("coordination scope belongs to a different owner or origin")
            if (
                scope.get("initial_user_turn") is True
                and scope.get("source_message_id")
                and scope["source_message_id"] == row["source_message_id"]
                and scope.get("allow_publish") is True
            ):
                conn.execute(
                    "UPDATE task_coordination_scopes SET allow_publish=1,updated_at=? "
                    "WHERE scope_id=? AND review_turns=0 AND state IN ('pending','idle')",
                    (timestamp, scope["scope_id"]),
                )
                row = conn.execute(
                    "SELECT * FROM task_coordination_scopes WHERE scope_id=?", (scope["scope_id"],)
                ).fetchone()
            return _record(row)

    def get(self, scope_id: str) -> dict[str, Any] | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM task_coordination_scopes WHERE scope_id=?", (scope_id,)
            ).fetchone()
        return _record(row) if row is not None else None

    def room(self, scope_id: str) -> dict[str, Any] | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM task_coordination_rooms WHERE scope_id=?", (scope_id,)
            ).fetchone()
        return dict(row) if row is not None else None

    def bind_room(self, scope_id: str, agent_id: str, thread_id: str) -> dict[str, Any]:
        with self._db.transaction() as conn:
            owned = conn.execute(
                "SELECT 1 FROM task_coordination_scopes s JOIN agents a ON a.user_id=s.user_id "
                "JOIN threads t ON t.agent_id=a.agent_id AND t.user_id=s.user_id "
                "WHERE s.scope_id=? AND a.agent_id=? AND t.thread_id=?",
                (scope_id, agent_id, thread_id),
            ).fetchone()
            if owned is None:
                raise ValueError("task room does not belong to the goal owner")
            conn.execute(
                "INSERT INTO task_coordination_rooms(scope_id,agent_id,thread_id,created_at) "
                "VALUES (?,?,?,?) ON CONFLICT(scope_id) DO NOTHING",
                (scope_id, agent_id, thread_id, now_ts()),
            )
            row = conn.execute(
                "SELECT * FROM task_coordination_rooms WHERE scope_id=?", (scope_id,)
            ).fetchone()
            return dict(row)

    def peer_sources(self, scope_id: str) -> list[dict[str, Any]]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM task_room_sources WHERE scope_id=? ORDER BY thread_id", (scope_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def bump_peer_revision(self, scope_id: str) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE task_coordination_scopes SET peer_revision=peer_revision+1,updated_at=? WHERE scope_id=?",
                (now_ts(), scope_id),
            )

    def scope_for_peer_thread(
        self, user_id: int, thread_id: str, *, include_closed: bool = False
    ) -> dict[str, Any] | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT s.*,p.parent_task_id AS execution_task_id,p.parent_attempt AS execution_attempt "
                "FROM task_room_sources p JOIN task_coordination_scopes s ON s.scope_id=p.scope_id "
                "JOIN threads t ON t.thread_id=p.thread_id AND t.user_id=s.user_id "
                "WHERE s.user_id=? AND p.thread_id=? "
                "ORDER BY s.id DESC LIMIT 1",
                (user_id, thread_id),
            ).fetchone()
        return (
            _record(row)
            if row is not None
            and (
                include_closed
                or row["state"] in {"pending", "running", "needs_user", "interrupted"}
            )
            else None
        )

    def register_peer_source(
        self,
        scope_id: str,
        thread_id: str,
        agent_id: str,
        caller_id: str,
        parent_task_id: str | None,
        parent_attempt: int | None,
        via_caller: bool,
    ) -> None:
        with self._db.transaction() as conn:
            owned = conn.execute(
                "SELECT 1 FROM task_coordination_scopes s JOIN threads t ON t.user_id=s.user_id "
                "WHERE s.scope_id=? AND t.thread_id=? AND t.agent_id=?",
                (scope_id, thread_id, agent_id),
            ).fetchone()
            if owned is None:
                raise ValueError("Peer history does not belong to this goal owner")
            conn.execute(
                "INSERT INTO task_room_sources(scope_id,thread_id,agent_id,caller_id,parent_task_id,parent_attempt,via_caller) "
                "VALUES (?,?,?,?,?,?,?) ON CONFLICT(scope_id,thread_id) DO UPDATE SET "
                "caller_id=excluded.caller_id,parent_task_id=excluded.parent_task_id,parent_attempt=excluded.parent_attempt,via_caller=excluded.via_caller",
                (
                    scope_id,
                    thread_id,
                    agent_id,
                    caller_id,
                    parent_task_id,
                    parent_attempt,
                    int(via_caller),
                ),
            )

    def scope_for_room(
        self, user_id: int, thread_id: str, *, include_stopped: bool = False
    ) -> dict[str, Any] | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT s.* FROM task_coordination_scopes s "
                "JOIN task_coordination_rooms r ON r.scope_id=s.scope_id "
                "JOIN threads t ON t.thread_id=r.thread_id AND t.agent_id=r.agent_id "
                "WHERE s.user_id=? AND t.user_id=? AND r.thread_id=? "
                "ORDER BY s.id DESC LIMIT 1",
                (user_id, user_id, thread_id),
            ).fetchone()
        return (
            _record(row)
            if row is not None and (include_stopped or row["state"] != "stopped")
            else None
        )

    def room_candidates(self, limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT s.* FROM task_coordination_scopes s WHERE "
                "EXISTS (SELECT 1 FROM task_room_sources p WHERE p.scope_id=s.scope_id) OR "
                "EXISTS (SELECT 1 FROM task_coordination_rooms r WHERE r.scope_id=s.scope_id) "
                "OR (s.state IN ('pending','running','needs_user','interrupted') AND "
                "(SELECT COUNT(DISTINCT t.agent_id) FROM task_dispatch_context d "
                "JOIN agent_tasks t ON t.task_id=d.task_id WHERE d.scope_id=s.scope_id "
                "AND t.user_id=s.user_id)>=2) OR "
                "(s.state IN ('pending','running','needs_user','interrupted') AND EXISTS "
                "(SELECT 1 FROM task_dispatch_context d JOIN agent_tasks t ON t.task_id=d.task_id "
                "JOIN agents a ON a.agent_id=t.agent_id WHERE d.scope_id=s.scope_id "
                "AND t.user_id=s.user_id AND a.kind='team')) ORDER BY s.id LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [_record(row) for row in rows]

    def room_cursor(self, scope_id: str, source_thread_id: str) -> int:
        return int(self.room_position(scope_id, source_thread_id)["last_seq"])

    def room_position(self, scope_id: str, source_thread_id: str) -> dict[str, Any]:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT last_seq,source_kind,last_id FROM task_room_cursors WHERE scope_id=? AND source_thread_id=?",
                (scope_id, source_thread_id),
            ).fetchone()
        return (
            dict(row)
            if row is not None
            else {"last_seq": 0, "source_kind": "projection", "last_id": ""}
        )

    def advance_room_cursor(
        self,
        scope_id: str,
        source_thread_id: str,
        last_seq: int,
        source_kind: str = "projection",
        last_id: str = "",
    ) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO task_room_cursors(scope_id,source_thread_id,last_seq,source_kind,last_id) VALUES (?,?,?,?,?) "
                "ON CONFLICT(scope_id,source_thread_id) DO UPDATE SET last_seq=excluded.last_seq,source_kind=excluded.source_kind,last_id=excluded.last_id "
                "WHERE task_room_cursors.last_seq<excluded.last_seq OR task_room_cursors.source_kind<>excluded.source_kind "
                "OR (excluded.source_kind='checkpoint' AND task_room_cursors.last_id<>excluded.last_id)",
                (scope_id, source_thread_id, last_seq, source_kind, last_id),
            )

    def record_room_input(
        self,
        scope_id: str,
        user_id: int,
        thread_id: str,
        message_id: str,
        text: str,
        *,
        resume: bool = True,
    ) -> bool:
        with self._db.transaction() as conn:
            owned = conn.execute(
                "SELECT 1 FROM task_coordination_rooms r JOIN task_coordination_scopes s "
                "ON s.scope_id=r.scope_id WHERE r.scope_id=? AND r.thread_id=? "
                "AND s.user_id=? AND s.state<>'stopped'",
                (scope_id, thread_id, user_id),
            ).fetchone()
            if owned is None:
                return False
            inserted = conn.execute(
                "INSERT INTO task_room_inputs(scope_id,message_id,input_text,created_at) VALUES (?,?,?,?) "
                "ON CONFLICT(scope_id,message_id) DO NOTHING",
                (scope_id, message_id, text, now_ts()),
            ).rowcount
            if not inserted:
                return False
            conn.execute(
                "UPDATE task_coordination_rooms SET last_input_id=? WHERE scope_id=?",
                (message_id, scope_id),
            )
            if not resume:
                conn.execute(
                    "UPDATE task_coordination_scopes SET user_input=?,resume_seq=resume_seq+1,updated_at=? WHERE scope_id=? AND user_id=?",
                    (text, now_ts(), scope_id, user_id),
                )
                return True
            conn.execute(
                "UPDATE task_coordination_scopes SET state='pending',user_input=?,resume_seq=resume_seq+1,"
                "review_turns=0,last_signature='',active_signature='',decision='',question='',updated_at=? "
                "WHERE scope_id=? AND user_id=? AND state<>'stopped'",
                (text, now_ts(), scope_id, user_id),
            )
            return True

    def for_parent(self, parent_task_id: str, parent_attempt: int) -> list[dict[str, Any]]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM task_coordination_scopes WHERE parent_task_id=? AND parent_attempt=? ORDER BY id",
                (parent_task_id, parent_attempt),
            ).fetchall()
        return [_record(row) for row in rows]

    def candidates(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT s.* FROM task_coordination_scopes s WHERE s.state IN ('pending','idle') "
                "AND EXISTS (SELECT 1 FROM task_dispatch_context d WHERE d.scope_id=s.scope_id) "
                "ORDER BY s.id LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [_record(row) for row in rows]

    def members(self, scope_id: str) -> list[dict[str, Any]]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT t.task_id,t.agent_id,t.thread_id,t.title,t.state,t.attempt,t.result,"
                "t.archived,d.coding_spec_json,d.coding_run_json,d.returned_event_id,"
                "COALESCE((SELECT MAX(e.id) FROM task_events e WHERE e.task_id=t.task_id "
                "AND e.action NOT IN ('archive','restore','reassign')),0) AS event_id "
                "FROM task_dispatch_context d JOIN agent_tasks t ON t.task_id=d.task_id "
                "JOIN task_coordination_scopes s ON s.scope_id=d.scope_id "
                "WHERE d.scope_id=? AND t.user_id=s.user_id ORDER BY t.id",
                (scope_id,),
            ).fetchall()
        result = []
        for row in rows:
            data = dict(row)
            data["coding_run"] = json.loads(data.pop("coding_run_json"))
            specification = data.pop("coding_spec_json")
            data["coding_spec"] = json.loads(specification) if specification is not None else None
            data["archived"] = bool(data["archived"])
            result.append(data)
        return result

    def claim(self, scope_id: str, signature: str, max_turns: int = 8) -> bool:
        with self._db.transaction() as conn:
            return bool(
                conn.execute(
                    "UPDATE task_coordination_scopes SET state='running',active_signature=?,"
                    "review_turns=review_turns+1,decision='',updated_at=? "
                    "WHERE scope_id=? AND state IN ('pending','idle') "
                    "AND last_signature<>? AND review_turns<?",
                    (signature, now_ts(), scope_id, signature, max_turns),
                ).rowcount
            )

    def decide(self, scope_id: str, decision: str, summary: str, question: str) -> bool:
        with self._db.transaction() as conn:
            return bool(
                conn.execute(
                    "UPDATE task_coordination_scopes SET decision=?,summary=?,question=?,updated_at=? "
                    "WHERE scope_id=? AND state='running'",
                    (decision, summary, question, now_ts(), scope_id),
                ).rowcount
            )

    def defer(self, scope_id: str, signature: str) -> bool:
        with self._db.transaction() as conn:
            return bool(
                conn.execute(
                    "UPDATE task_coordination_scopes SET state='pending',active_signature='',"
                    "review_turns=CASE WHEN review_turns>0 THEN review_turns-1 ELSE 0 END,updated_at=? "
                    "WHERE scope_id=? AND state='running' AND active_signature=?",
                    (now_ts(), scope_id, signature),
                ).rowcount
            )

    def finish(
        self, scope_id: str, signature: str, state: str, summary: str = "", question: str = ""
    ) -> bool:
        with self._db.transaction() as conn:
            return bool(
                conn.execute(
                    "UPDATE task_coordination_scopes SET state=?,last_signature=?,active_signature='',"
                    "handled_resume_seq=resume_seq,"
                    "summary=CASE WHEN ?<>'' THEN ? ELSE summary END,"
                    "question=CASE WHEN ?<>'' THEN ? ELSE question END,updated_at=? "
                    "WHERE scope_id=? AND state='running' AND active_signature=?",
                    (
                        state,
                        signature,
                        summary,
                        summary,
                        question,
                        question,
                        now_ts(),
                        scope_id,
                        signature,
                    ),
                ).rowcount
            )

    def resume(
        self, scope_id: str, user_id: int, user_input: str, allow_publish: bool | None = None
    ) -> bool:
        sql = (
            "UPDATE task_coordination_scopes SET state='pending',review_turns=0,user_input=?,"
            "last_signature='',active_signature='',decision='',question='',resume_seq=resume_seq+1,updated_at=?"
        )
        values: list[object] = [user_input, now_ts()]
        if allow_publish is not None:
            sql += ",allow_publish=?"
            values.append(int(allow_publish))
        sql += " WHERE scope_id=? AND user_id=? AND state IN ('needs_user','interrupted')"
        values.extend((scope_id, user_id))
        with self._db.transaction() as conn:
            changed = bool(conn.execute(sql, values).rowcount)
            if changed:
                conn.execute(
                    "UPDATE task_coordination_rooms SET last_input_id='' WHERE scope_id=?",
                    (scope_id,),
                )
            return changed

    def interrupt_running(self) -> int:
        with self._db.transaction() as conn:
            return int(
                conn.execute(
                    "UPDATE task_coordination_scopes SET state='interrupted',active_signature='',"
                    "decision='',updated_at=? WHERE state='running'",
                    (now_ts(),),
                ).rowcount
            )

    def require_user(self, scope_id: str, question: str) -> bool:
        """The controller has established its review limit without another model call."""
        with self._db.transaction() as conn:
            return bool(
                conn.execute(
                    "UPDATE task_coordination_scopes SET state='needs_user',question=?,updated_at=? "
                    "WHERE scope_id=? AND state IN ('pending','idle')",
                    (question, now_ts(), scope_id),
                ).rowcount
            )

    def stop(self, scope_id: str, user_id: int) -> bool:
        with self._db.transaction() as conn:
            return bool(
                conn.execute(
                    "UPDATE task_coordination_scopes SET state='stopped',active_signature='',updated_at=? "
                    "WHERE scope_id=? AND user_id=?",
                    (now_ts(), scope_id, user_id),
                ).rowcount
            )

    def stop_parent(self, parent_task_id: str, parent_attempt: int) -> int:
        with self._db.transaction() as conn:
            return int(
                conn.execute(
                    "UPDATE task_coordination_scopes SET state='stopped',active_signature='',updated_at=? "
                    "WHERE parent_task_id=? AND parent_attempt=? AND state<>'stopped'",
                    (now_ts(), parent_task_id, parent_attempt),
                ).rowcount
            )
