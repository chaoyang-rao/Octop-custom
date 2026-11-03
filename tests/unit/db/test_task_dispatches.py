"""Task receipts survive upgrades and keep retries inside their original owner scope."""

from __future__ import annotations

import os
import sqlite3
import uuid
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.support.postgresql import requires_postgresql

from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import DatabasePool, SqlitePool
from octop.infra.db.services import RepoBundle


def seeded(db: DatabasePool) -> SimpleNamespace:
    run_migrations(db)
    repos = RepoBundle.from_pool(db)
    owner = repos.user_repo.create(username="owner", password_hash="test", role="admin")
    other = repos.user_repo.create(username="other", password_hash="test", role="admin")
    for agent_id, user_id in (("host", owner), ("worker", owner), ("other", other)):
        repos.agent_repo.create(agent_id=agent_id, user_id=user_id, name=agent_id)
        repos.thread_repo.insert(
            thread_id=f"{agent_id}-thread",
            agent_id=agent_id,
            user_id=user_id,
            channel_type="dashboard",
            session_key=f"{agent_id}-session",
            title="保留的会话",
        )
    return SimpleNamespace(db=db, repos=repos, owner=owner, other=other)


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[SimpleNamespace]:
    monkeypatch.setenv("OCTOP_HOME", str(tmp_path))
    db = SqlitePool(tmp_path / "dispatch.sqlite")
    try:
        yield seeded(db)
    finally:
        db.close()


def task(env: SimpleNamespace, task_id: str = "task", **changes: object) -> dict:
    return {
        "task_id": task_id,
        "user_id": env.owner,
        "agent_id": "worker",
        "title": "可交付的任务",
        "prompt": "完成任务并交付产物",
        "dispatch": {
            "origin_agent_id": "host",
            "origin_thread_id": "host-thread",
            "request_key": f"owner:{env.owner}:request-1",
            "coding_spec": None,
        },
        **changes,
    }


def test_enqueue_receipt_is_atomic_idempotent_and_not_public(env: SimpleNamespace) -> None:
    repo = env.repos.task_repo
    dispatches = env.repos.task_dispatch_repo
    assert repo.enqueue([task(env)]) is None
    assert repo.enqueue([task(env, "duplicate")]) == "task"
    assert repo.get("duplicate") is None
    receipt = dispatches.get("task")
    assert receipt is not None
    assert receipt["origin_agent_id"] == "host"
    assert receipt["origin_thread_id"] == "host-thread"
    assert receipt["coding_spec"] is None and receipt["coding_run"] == {}
    assert "request_key" not in receipt
    assert dispatches.get_many(["task", "missing"]) == {"task": receipt}
    assert dispatches.get_many([]) == {}
    assert len(repo.list(env.owner)) == 1
    assert len(repo.events("task")) == 1

    invalid = task(env, "invalid", dispatch={"origin_thread_id": "missing-thread"})
    with pytest.raises(sqlite3.IntegrityError):
        repo.enqueue([invalid])
    assert repo.get("invalid") is None


@pytest.mark.parametrize("other_scope", ["owner", "thread", "agent"])
def test_same_request_key_cannot_escape_owner_or_origin(
    env: SimpleNamespace, other_scope: str
) -> None:
    original = task(env)
    env.repos.task_repo.enqueue([original])
    changed = task(env, "collision")
    if other_scope == "owner":
        changed.update(user_id=env.other, agent_id="other")
    else:
        changed["dispatch"] = {
            **original["dispatch"],
            ("origin_thread_id" if other_scope == "thread" else "origin_agent_id"): "worker"
            if other_scope == "agent"
            else "worker-thread",
        }
    with pytest.raises(ValueError, match="different owner or origin"):
        env.repos.task_repo.enqueue([changed])
    assert env.repos.task_repo.get("collision") is None


def test_coding_attempt_fences_and_waiting_completion_receipts(env: SimpleNamespace) -> None:
    repo = env.repos.task_repo
    dispatches = env.repos.task_dispatch_repo
    code = {
        "project_path": "opaque-project-path",
        "base_ref": "HEAD",
        "test_commands": ["make all"],
        "publish_pr": False,
    }
    spec = task(env)
    spec["dispatch"]["coding_spec"] = code
    repo.enqueue([spec])
    assert dispatches.get("task")["coding_spec"] == code
    assert repo.claim("task")
    assert not dispatches.update_coding("task", {"phase": "stale"}, expected_attempt=0)
    assert dispatches.update_coding("task", {"phase": "prepared"}, expected_attempt=1)
    assert dispatches.get("task")["coding_run"] == {"phase": "prepared"}
    assert not dispatches.pending_returns()
    repo.transition("task", expected={"running"}, state="waiting", action="waiting")
    assert [row["task_id"] for row in dispatches.pending_returns(env.owner)] == ["task"]
    assert not dispatches.pending_returns(env.other)
    assert dispatches.mark_returned("task", 1, state="waiting")
    assert not dispatches.mark_returned("task", 1, state="waiting")
    assert not dispatches.pending_returns()
    first_event = dispatches.get("task")["returned_event_id"]
    repo.transition("task", expected={"waiting"}, state="running", action="resumed")
    repo.transition("task", expected={"running"}, state="waiting", action="waiting_again")
    second_event = dispatches.pending_returns()[0]["current_event_id"]
    assert second_event > first_event
    assert not dispatches.mark_returned("task", 1, state="waiting", event_id=first_event)
    assert dispatches.mark_returned("task", 1, state="waiting", event_id=second_event)
    assert not dispatches.pending_returns()
    repo.transition("task", expected={"waiting"}, state="completed", action="completed")
    assert len(dispatches.pending_returns()) == 1
    assert not dispatches.mark_returned("task", 1, state="waiting")
    assert dispatches.mark_returned("task", 1, state="completed", expected_attempt=1)
    assert not dispatches.pending_returns()


def test_queued_cancellation_is_returned_at_attempt_zero(env: SimpleNamespace) -> None:
    repo, dispatches = env.repos.task_repo, env.repos.task_dispatch_repo
    repo.enqueue([task(env)])
    repo.transition("task", expected={"queued"}, state="cancelled", action="cancelled")
    assert len(dispatches.pending_returns()) == 1
    assert dispatches.mark_returned("task", 0, state="cancelled")
    assert not dispatches.pending_returns()
    assert not dispatches.mark_returned("task", 0, state="cancelled")


def test_coding_state_cas_rejects_a_cancelled_attempt(env: SimpleNamespace) -> None:
    repo, dispatches = env.repos.task_repo, env.repos.task_dispatch_repo
    repo.enqueue([task(env)])
    assert repo.claim("task")
    assert dispatches.update_coding(
        "task", {"phase": "verifying"}, expected_attempt=1, expected_states={"running", "waiting"}
    )
    repo.transition("task", expected={"running"}, state="cancelled", action="cancel")
    assert not dispatches.update_coding(
        "task", {"phase": "published"}, expected_attempt=1, expected_states={"running", "waiting"}
    )
    assert dispatches.get("task")["coding_run"] == {"phase": "verifying"}


def test_pending_returns_can_page_past_an_earlier_waiting_source(env: SimpleNamespace) -> None:
    for index in range(3):
        row = task(env, f"task-{index}")
        row["dispatch"]["request_key"] = None
        env.repos.task_repo.enqueue([row])
        assert env.repos.task_repo.claim(f"task-{index}")
        env.repos.task_repo.transition(
            f"task-{index}", expected={"running"}, state="completed", action="completed"
        )
    page = env.repos.task_dispatch_repo.pending_returns(env.owner, limit=1, offset=1)
    assert [row["task_id"] for row in page] == ["task-1"]


def test_parent_links_select_only_the_current_parent_attempt(env: SimpleNamespace) -> None:
    parent = task(env, "parent", agent_id="host", dispatch=None)
    env.repos.task_repo.enqueue([parent])
    for attempt in (1, 2):
        child = task(env, f"child-{attempt}")
        child["dispatch"].update(
            parent_task_id="parent",
            parent_attempt=attempt,
            request_key=f"parent-request:{attempt}",
        )
        env.repos.task_repo.enqueue([child])
    dispatches = env.repos.task_dispatch_repo
    assert dispatches.children("parent", 1) == ["child-1"]
    assert dispatches.children("parent", 2) == ["child-2"]
    assert dispatches.children("parent", 3) == []
    assert dispatches.get("child-1")["parent_task_id"] == "parent"
    assert dispatches.get_many(["child-2"])["child-2"]["parent_attempt"] == 2


def test_archive_restore_and_reassign_do_not_replay_execution_returns(env: SimpleNamespace) -> None:
    repo, dispatches = env.repos.task_repo, env.repos.task_dispatch_repo
    repo.enqueue([task(env)])
    assert repo.claim("task")
    repo.transition("task", expected={"running"}, state="completed", action="completed")
    event_id = dispatches.get("task")["current_event_id"]
    repo.transition(
        "task", expected={"completed"}, state="completed", action="archive", fields={"archived": 1}
    )
    assert not dispatches.pending_returns()
    assert not dispatches.mark_returned("task", 1, state="completed", event_id=event_id)
    repo.transition(
        "task", expected={"completed"}, state="completed", action="restore", fields={"archived": 0}
    )
    assert dispatches.pending_returns()[0]["current_event_id"] == event_id
    assert dispatches.mark_returned("task", 1, state="completed", event_id=event_id)
    for action in ("archive", "restore", "reassign"):
        repo.transition("task", expected={"completed"}, state="completed", action=action)
        assert dispatches.get("task")["current_event_id"] == event_id
        assert not dispatches.pending_returns()


@pytest.mark.parametrize("suffix", [".sql", ".pg.sql"])
def test_v26_upgrade_ddl_and_repair_preserve_existing_rows(
    env: SimpleNamespace, suffix: str
) -> None:
    # Only driver-specific identity syntax is normalized for this SQLite check.
    # A gated PostgreSQL instance test exercises the unchanged PostgreSQL file.
    repo = env.repos.task_repo
    plain = task(env)
    plain.pop("dispatch")
    repo.enqueue([plain])
    with env.db.connect() as conn:
        before = dict(conn.execute("SELECT * FROM agent_tasks WHERE task_id='task'").fetchone())
        conn.execute("DROP TABLE task_dispatch_context")
        conn.execute("DROP TABLE task_coordination_scopes")
        conn.execute("UPDATE _schema_version SET version=26")
        path = Path(__file__).resolve().parents[3] / "src/octop/infra/db/migrations"
        sql = (path / ("027_task_dispatch" + suffix)).read_text()
        if suffix == ".pg.sql":
            sql = sql.replace(
                "id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY",
                "id INTEGER PRIMARY KEY AUTOINCREMENT",
            )
        conn.executescript(sql)
        conn.executescript(sql)
    run_migrations(env.db)
    run_migrations(env.db)
    with env.db.connect() as conn:
        assert conn.execute("SELECT version FROM _schema_version").fetchone()[0] == 28
        after = dict(conn.execute("SELECT * FROM agent_tasks WHERE task_id='task'").fetchone())
        assert after == before
        assert conn.execute("SELECT COUNT(*) FROM threads").fetchone()[0] == 3
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
        conn.execute("DROP TABLE task_dispatch_context")
    # A restored watermark at 27 must still restore a missing extension table.
    run_migrations(env.db)
    assert env.repos.task_dispatch_repo.get("task") is None


def test_v26_watermark_uses_numbered_migration(env: SimpleNamespace) -> None:
    with env.db.connect() as conn:
        conn.execute("DROP TABLE task_dispatch_context")
        conn.execute("DROP TABLE task_coordination_scopes")
        conn.execute("UPDATE _schema_version SET version=26")
    run_migrations(env.db)
    env.repos.task_repo.enqueue([task(env)])
    assert env.repos.task_dispatch_repo.get("task") is not None


def test_partial_v27_receipt_column_is_repaired_without_losing_context(
    env: SimpleNamespace,
) -> None:
    env.repos.task_repo.enqueue([task(env)])
    env.repos.task_dispatch_repo.update_coding("task", {"phase": "prepared"})
    with env.db.connect() as conn:
        conn.execute("ALTER TABLE task_dispatch_context DROP COLUMN returned_event_id")
        conn.execute("DROP INDEX idx_task_dispatch_parent")
        conn.execute("ALTER TABLE task_dispatch_context DROP COLUMN parent_task_id")
        conn.execute("ALTER TABLE task_dispatch_context DROP COLUMN parent_attempt")
        conn.execute("DROP INDEX idx_task_dispatch_scope")
        conn.execute("ALTER TABLE task_dispatch_context DROP COLUMN scope_id")
        conn.execute("DROP TABLE task_coordination_scopes")
    run_migrations(env.db)
    context = env.repos.task_dispatch_repo.get("task")
    assert context["origin_thread_id"] == "host-thread"
    assert context["coding_run"] == {"phase": "prepared"}
    assert context["returned_event_id"] == 0
    assert context["parent_task_id"] is None and context["parent_attempt"] is None


@requires_postgresql
@pytest.mark.postgresql
def test_postgresql_dispatch_roundtrip_uses_an_isolated_schema(tmp_path: Path, monkeypatch) -> None:
    from psycopg.conninfo import make_conninfo

    from octop.infra.db.pool import PostgresPool

    monkeypatch.setenv("OCTOP_HOME", str(tmp_path))
    schema = "octop_dispatch_test_" + uuid.uuid4().hex
    control = PostgresPool(os.environ["OCTOP_TEST_DATABASE_URL"], max_size=1)
    isolated = None
    try:
        with control.connect() as conn:
            conn.execute(f'CREATE SCHEMA "{schema}"')
        isolated = PostgresPool(
            make_conninfo(
                os.environ["OCTOP_TEST_DATABASE_URL"], options=f"-c search_path={schema}"
            ),
            max_size=1,
        )
        env = seeded(isolated)
        env.repos.task_repo.enqueue([task(env)])
        assert env.repos.task_repo.enqueue([task(env, "retry")]) == "task"
        assert env.repos.task_dispatch_repo.get("task")["origin_thread_id"] == "host-thread"
        assert env.repos.task_repo.claim("task")
        assert env.repos.task_dispatch_repo.update_coding(
            "task", {"phase": "ready"}, expected_attempt=1
        )
        run_migrations(isolated)
        assert env.repos.task_dispatch_repo.get("task")["coding_run"] == {"phase": "ready"}
        scope_repo = env.repos.task_coordination_repo
        record = scope_repo.ensure(
            {
                "scope_id": "pg-scope",
                "user_id": env.owner,
                "origin_agent_id": "host",
                "origin_thread_id": "host-thread",
                "source_message_id": "human",
                "goal_text": "review",
            }
        )
        assert record["id"] == "pg-scope"
        coordinated = task(env, "coordinated")
        coordinated["dispatch"].update(request_key=None, scope_id="pg-scope")
        env.repos.task_repo.enqueue([coordinated])
        assert scope_repo.members("pg-scope")[0]["task_id"] == "coordinated"
        assert scope_repo.claim("pg-scope", "result-signature")
        assert scope_repo.decide("pg-scope", "complete", "verified", "")
        assert scope_repo.finish("pg-scope", "result-signature", "idle")
        assert not scope_repo.claim("pg-scope", "result-signature")
    finally:
        if isolated is not None:
            isolated.close()
        with control.connect() as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        control.close()
