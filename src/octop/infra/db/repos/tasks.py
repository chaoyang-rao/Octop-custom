"""SQL persistence for task queues, workflow definitions and immutable run membership."""

from __future__ import annotations

import builtins
import json
from dataclasses import asdict, dataclass
from typing import Any

from octop.infra.db.pool import DatabasePool
from octop.infra.db.repos._base import DbRow, now_ts


@dataclass(frozen=True)
class TaskRow:
    pk: int
    task_id: str
    user_id: int
    agent_id: str
    thread_id: str | None
    title: str
    prompt: str
    options_json: str
    state: str
    run_id: str | None
    step_key: str | None
    dependency_ids: str
    result: str
    error_code: str | None
    archived: int
    attempt: int
    created_at: int
    updated_at: int
    started_at: int | None
    finished_at: int | None

    @classmethod
    def from_row(cls, row: DbRow) -> TaskRow:
        values = dict(row)
        values["pk"] = values.pop("id")
        return cls(**values)

    @property
    def id(self) -> str:
        return self.task_id

    def to_public(self, *, detail: bool = True) -> dict[str, Any]:
        result = asdict(self)
        result.pop("pk")
        result.pop("options_json")
        result.pop("dependency_ids")
        result["id"] = self.task_id
        result["archived"] = bool(self.archived)
        result["dependencies"] = json.loads(self.dependency_ids)
        if detail:
            result["options"] = json.loads(self.options_json)
        else:
            result.pop("prompt")
            result.pop("result")
        return result


@dataclass(frozen=True)
class WorkflowRow:
    pk: int
    workflow_id: str
    user_id: int
    name: str
    definition_json: str
    enabled: int
    webhook_hash: str | None
    next_run_at: int | None
    last_run_at: int | None
    schedule_paused: int
    created_at: int
    updated_at: int

    @classmethod
    def from_row(cls, row: DbRow) -> WorkflowRow:
        values = dict(row)
        values["pk"] = values.pop("id")
        return cls(**values)

    def to_public(self) -> dict[str, Any]:
        return {
            "id": self.workflow_id,
            "user_id": self.user_id,
            "name": self.name,
            "definition": json.loads(self.definition_json),
            "enabled": bool(self.enabled),
            "webhook_enabled": bool(self.webhook_hash),
            "next_run_at": self.next_run_at,
            "last_run_at": self.last_run_at,
            "schedule_paused": bool(self.schedule_paused),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class TaskRepo:
    def __init__(self, db: DatabasePool) -> None:
        self._db = db

    def create_upload_receipt(
        self,
        *,
        receipt_id: str,
        token_hash: str,
        user_id: int,
        agent_id: str,
        path: str,
        filename: str,
        mime_type: str,
        size: int,
        sha256: str,
    ) -> None:
        ts = now_ts()
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO task_upload_receipts(receipt_id,token_hash,user_id,agent_id,workspace_path,filename,mime_type,byte_size,sha256,created_at,expires_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    receipt_id,
                    token_hash,
                    user_id,
                    agent_id,
                    path,
                    filename,
                    mime_type,
                    size,
                    sha256,
                    ts,
                    ts + 30 * 86400,
                ),
            )

    def upload_receipt(
        self, token_hash: str, *, user_id: int, agent_id: str, path: str
    ) -> dict[str, Any] | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT filename,mime_type,byte_size,sha256,expires_at FROM task_upload_receipts WHERE token_hash=? AND user_id=? AND agent_id=? AND workspace_path=?",
                (token_hash, user_id, agent_id, path),
            ).fetchone()
        return dict(row) if row else None

    def get(self, task_id: str) -> TaskRow | None:
        with self._db.connect() as conn:
            row = conn.execute("SELECT * FROM agent_tasks WHERE task_id = ?", (task_id,)).fetchone()
        return TaskRow.from_row(row) if row else None

    def list(
        self, user_id: int, *, archived: bool = False, agent_id: str | None = None, limit: int = 100
    ) -> builtins.list[TaskRow]:
        sql = "SELECT * FROM agent_tasks WHERE user_id = ? AND archived = ?"
        args: builtins.list[object] = [user_id, int(archived)]
        if agent_id:
            sql += " AND agent_id = ?"
            args.append(agent_id)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        with self._db.connect() as conn:
            rows = conn.execute(sql, args).fetchall()
        return [TaskRow.from_row(row) for row in rows]

    @staticmethod
    def _event(conn: Any, task_id: str, action: str, state: str, actor_user_id: int | None) -> None:
        conn.execute(
            "INSERT INTO task_events(task_id,action,state,actor_user_id,created_at) VALUES (?,?,?,?,?)",
            (task_id, action, state, actor_user_id, now_ts()),
        )

    def enqueue(
        self, tasks: builtins.list[dict[str, Any]], *, run: dict[str, Any] | None = None
    ) -> str | None:
        """Insert every node of a workflow run atomically; return a deduplicated run id."""
        with self._db.transaction() as conn:
            if run:
                if run.get("trigger_key"):
                    existing = conn.execute(
                        "SELECT run_id FROM task_runs WHERE workflow_id = ? AND trigger_key = ?",
                        (run["workflow_id"], run["trigger_key"]),
                    ).fetchone()
                    if existing:
                        return str(existing["run_id"])
                inserted = conn.execute(
                    "INSERT INTO task_runs(run_id,workflow_id,user_id,name,source,definition_json,trigger_key,created_at) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(workflow_id,trigger_key) DO NOTHING",
                    (
                        run["run_id"],
                        run["workflow_id"],
                        run["user_id"],
                        run["name"],
                        run["source"],
                        json.dumps(run.get("definition", {})),
                        run.get("trigger_key"),
                        now_ts(),
                    ),
                )
                if not inserted.rowcount:
                    existing = conn.execute(
                        "SELECT run_id FROM task_runs WHERE workflow_id=? AND trigger_key=?",
                        (run["workflow_id"], run["trigger_key"]),
                    ).fetchone()
                    if existing:
                        return str(existing["run_id"])
                    raise RuntimeError("workflow run insert failed")
            for task in tasks:
                conn.execute(
                    "INSERT INTO agent_tasks(task_id,user_id,agent_id,thread_id,title,prompt,options_json,run_id,step_key,dependency_ids,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        task["task_id"],
                        task["user_id"],
                        task["agent_id"],
                        task.get("thread_id"),
                        task["title"],
                        task["prompt"],
                        json.dumps(task.get("options", {})),
                        task.get("run_id"),
                        task.get("step_key"),
                        json.dumps(task.get("dependencies", [])),
                        now_ts(),
                        now_ts(),
                    ),
                )
                self._event(conn, task["task_id"], "created", "queued", task["user_id"])
        return None

    def queue_heads(self) -> builtins.list[TaskRow]:
        # A paused or approval-waiting head deliberately blocks later tasks for that expert.
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT t.* FROM agent_tasks t LEFT JOIN task_queue_controls c ON c.agent_id=t.agent_id AND c.user_id=t.user_id WHERE t.archived=0 AND t.state IN ('queued','paused','running','waiting') AND COALESCE(c.paused,0)=0 ORDER BY t.id"
            ).fetchall()
        seen: set[str] = set()
        heads = []
        for raw in rows:
            row = TaskRow.from_row(raw)
            if row.agent_id not in seen:
                heads.append(row)
                seen.add(row.agent_id)
        return heads

    def dependencies(self, task: TaskRow) -> builtins.list[TaskRow]:
        ids = json.loads(task.dependency_ids)
        if not ids:
            return []
        sql = (
            "SELECT * FROM agent_tasks WHERE task_id IN ("
            + ",".join("?" for _ in ids)
            + ") ORDER BY id"
        )
        with self._db.connect() as conn:
            rows = conn.execute(sql, ids).fetchall()
        return [TaskRow.from_row(row) for row in rows]

    def claim(self, task_id: str) -> bool:
        with self._db.transaction() as conn:
            changed = bool(
                conn.execute(
                    "UPDATE agent_tasks AS t SET state='running',attempt=attempt+1,started_at=?,finished_at=NULL,error_code=NULL,updated_at=? "
                    "WHERE task_id=? AND state='queued' AND archived=0 "
                    "AND NOT EXISTS (SELECT 1 FROM task_queue_controls c WHERE c.agent_id=t.agent_id AND c.user_id=t.user_id AND c.paused=1) "
                    "AND NOT EXISTS (SELECT 1 FROM agent_tasks h WHERE h.agent_id=t.agent_id AND h.archived=0 AND h.id<t.id AND h.state IN ('queued','paused','running','waiting'))",
                    (now_ts(), now_ts(), task_id),
                ).rowcount
            )
            if changed:
                self._event(conn, task_id, "started", "running", None)
        return changed

    def transition(
        self,
        task_id: str,
        *,
        expected: set[str],
        state: str,
        action: str,
        actor_user_id: int | None = None,
        fields: dict[str, Any] | None = None,
        append_result: str | None = None,
        expected_attempt: int | None = None,
    ) -> bool:
        changes = {"state": state, "updated_at": now_ts(), **(fields or {})}
        if set(changes) - {
            "state",
            "updated_at",
            "thread_id",
            "agent_id",
            "result",
            "error_code",
            "attempt",
            "started_at",
            "finished_at",
            "archived",
        }:
            raise ValueError("unknown task column")
        if not expected:
            return False
        assignments = [f"{name}=?" for name in changes]
        values = builtins.list(changes.values())
        if append_result is not None:
            suffix = (
                "right(result || ?,128000)"
                if self._db.dialect == "postgresql"
                else "substr(result || ?, -128000)"
            )
            assignments.append("result=" + suffix)
            values.append(append_result[-128000:])
        sql = (
            "UPDATE agent_tasks SET "
            + ",".join(assignments)
            + " WHERE task_id=? AND state IN ("
            + ",".join("?" for _ in expected)
            + ")"
        )
        parameters = [*values, task_id, *sorted(expected)]
        if expected_attempt is not None:
            sql += " AND attempt=?"
            parameters.append(expected_attempt)
        with self._db.transaction() as conn:
            result = conn.execute(sql, parameters)
            changed = bool(result.rowcount)
            if changed:
                self._event(conn, task_id, action, state, actor_user_id)
        return changed

    def recover(self) -> builtins.list[str]:
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT task_id FROM agent_tasks WHERE state IN ('running','waiting')"
            ).fetchall()
            conn.execute(
                "UPDATE agent_tasks SET state='interrupted', error_code='interrupted', updated_at=?,finished_at=? WHERE state IN ('running','waiting')",
                (now_ts(), now_ts()),
            )
            for row in rows:
                self._event(conn, row["task_id"], "recovered", "interrupted", None)
        return [str(row["task_id"]) for row in rows]

    def events(self, task_id: str) -> builtins.list[dict[str, Any]]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT action,state,actor_user_id,created_at FROM task_events WHERE task_id=? ORDER BY id",
                (task_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def set_queue_paused(self, agent_id: str, user_id: int, paused: bool) -> None:
        with self._db.connect() as conn:
            conn.execute(
                "INSERT INTO task_queue_controls(agent_id,user_id,paused) VALUES(?,?,?) ON CONFLICT(agent_id,user_id) DO UPDATE SET paused=excluded.paused",
                (agent_id, user_id, int(paused)),
            )

    def queue_controls(self, user_id: int) -> dict[str, bool]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT agent_id,paused FROM task_queue_controls WHERE user_id=?", (user_id,)
            ).fetchall()
        return {str(row["agent_id"]): bool(row["paused"]) for row in rows}

    def create_workflow(
        self,
        *,
        workflow_id: str,
        user_id: int,
        name: str,
        definition: dict[str, Any],
        enabled: bool,
        next_run_at: int | None,
    ) -> None:
        with self._db.connect() as conn:
            conn.execute(
                "INSERT INTO task_workflows(workflow_id,user_id,name,definition_json,enabled,next_run_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (
                    workflow_id,
                    user_id,
                    name,
                    json.dumps(definition),
                    int(enabled),
                    next_run_at,
                    now_ts(),
                    now_ts(),
                ),
            )

    def workflow(self, workflow_id: str) -> WorkflowRow | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM task_workflows WHERE workflow_id=?", (workflow_id,)
            ).fetchone()
        return WorkflowRow.from_row(row) if row else None

    def workflows(self, user_id: int) -> builtins.list[WorkflowRow]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM task_workflows WHERE user_id=? ORDER BY id DESC", (user_id,)
            ).fetchall()
        return [WorkflowRow.from_row(row) for row in rows]

    def update_workflow(
        self,
        workflow_id: str,
        *,
        name: str,
        definition: dict[str, Any],
        enabled: bool,
        next_run_at: int | None,
    ) -> None:
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE task_workflows SET name=?,definition_json=?,enabled=?,next_run_at=?,updated_at=? WHERE workflow_id=?",
                (name, json.dumps(definition), int(enabled), next_run_at, now_ts(), workflow_id),
            )

    def set_webhook_hash(self, workflow_id: str, value: str | None) -> None:
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE task_workflows SET webhook_hash=?,updated_at=? WHERE workflow_id=?",
                (value, now_ts(), workflow_id),
            )

    def runs(self, user_id: int, *, limit: int = 100) -> builtins.list[dict[str, Any]]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT run_id,workflow_id,name,source,created_at FROM task_runs WHERE user_id=? ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def run_tasks(self, run_id: str, user_id: int) -> builtins.list[TaskRow]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_tasks WHERE run_id=? AND user_id=? ORDER BY id",
                (run_id, user_id),
            ).fetchall()
        return [TaskRow.from_row(row) for row in rows]

    def due_workflows(self, now: int) -> builtins.list[WorkflowRow]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM task_workflows WHERE enabled=1 AND schedule_paused=0 AND next_run_at IS NOT NULL AND next_run_at<=? ORDER BY next_run_at,id",
                (now,),
            ).fetchall()
        return [WorkflowRow.from_row(row) for row in rows]

    def advance_schedule(self, workflow_id: str, expected: int, next_run_at: int | None) -> None:
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE task_workflows SET next_run_at=?,last_run_at=?,updated_at=? WHERE workflow_id=? AND next_run_at=?",
                (next_run_at, expected, now_ts(), workflow_id, expected),
            )

    def pause_schedule(self, workflow_id: str, paused: bool, next_run_at: int | None) -> None:
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE task_workflows SET schedule_paused=?,next_run_at=?,updated_at=? WHERE workflow_id=?",
                (int(paused), next_run_at, now_ts(), workflow_id),
            )

    def run_workflow_id(self, run_id: str) -> str | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT workflow_id FROM task_runs WHERE run_id=?", (run_id,)
            ).fetchone()
        return str(row["workflow_id"]) if row and row["workflow_id"] else None

    def run_definition(self, run_id: str) -> dict[str, Any]:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT definition_json FROM task_runs WHERE run_id=?", (run_id,)
            ).fetchone()
        return dict(json.loads(row["definition_json"])) if row else {}

    def delete_workflow(self, workflow_id: str) -> None:
        with self._db.connect() as conn:
            conn.execute("DELETE FROM task_workflows WHERE workflow_id=?", (workflow_id,))

    def pending_exists(self) -> bool:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM agent_tasks WHERE state IN ('queued','paused','running','waiting') LIMIT 1"
            ).fetchone()
        return row is not None

    def active_in_thread(
        self, agent_id: str, user_id: int, thread_id: str
    ) -> builtins.list[TaskRow]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_tasks WHERE agent_id=? AND user_id=? AND thread_id=? AND state IN ('running','waiting') ORDER BY id",
                (agent_id, user_id, thread_id),
            ).fetchall()
        return [TaskRow.from_row(row) for row in rows]

    def latest_in_thread(self, agent_id: str, user_id: int, thread_id: str) -> TaskRow | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_tasks WHERE agent_id=? AND user_id=? AND thread_id=? ORDER BY id DESC LIMIT 1",
                (agent_id, user_id, thread_id),
            ).fetchone()
        return TaskRow.from_row(row) if row else None

    def runtime_rows(self) -> builtins.list[TaskRow]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT t.* FROM agent_tasks t WHERE t.attempt>0 AND t.thread_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM agent_tasks newer WHERE newer.agent_id=t.agent_id AND newer.user_id=t.user_id AND newer.thread_id=t.thread_id AND newer.attempt>0 AND newer.id>t.id) ORDER BY t.id"
            ).fetchall()
        return [TaskRow.from_row(row) for row in rows]
