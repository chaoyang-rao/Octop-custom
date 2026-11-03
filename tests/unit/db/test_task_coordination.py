"""Bounded review scopes retain owner authority and consume human resumes once."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.unit.db.test_task_dispatches import seeded, task

from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.tasks.models import CoordinationScopeView


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[SimpleNamespace]:
    monkeypatch.setenv("OCTOP_HOME", str(tmp_path))
    db = SqlitePool(tmp_path / "coordination.sqlite")
    try:
        yield seeded(db)
    finally:
        db.close()


def scope(env, scope_id="scope", **changes):
    return {
        "scope_id": scope_id,
        "user_id": env.owner,
        "origin_agent_id": "host",
        "origin_thread_id": "host-thread",
        "source_message_id": "real-user-message",
        "goal_text": "交付原始用户要求的报告",
        "allow_publish": False,
        "initial_user_turn": True,
        **changes,
    }


def member(env, scope_id="scope", task_id="member", **changes):
    context = env.repos.task_coordination_repo.get(scope_id)
    body = task(env, task_id)
    body["dispatch"].update(
        scope_id=scope_id,
        parent_task_id=context["parent_task_id"],
        parent_attempt=context["parent_attempt"],
        request_key=None,
        **changes,
    )
    env.repos.task_repo.enqueue([body])


def test_ensure_does_not_let_callbacks_expand_or_replace_the_original_goal(env):
    repo = env.repos.task_coordination_repo
    original = scope(env)
    record = repo.ensure(original)
    assert record["id"] == record["scope_id"] == "scope"
    assert CoordinationScopeView.model_validate(record).id == "scope"
    assert not repo.ensure({**original, "allow_publish": True, "initial_user_turn": False})[
        "allow_publish"
    ]
    changed = repo.ensure({**original, "goal_text": "replace the goal", "allow_publish": True})
    assert changed["allow_publish"] is True
    assert changed["goal_text"] == original["goal_text"]
    callback = repo.ensure(
        scope(env, "callback-created", allow_publish=True, initial_user_turn=False)
    )
    assert callback["allow_publish"] is False
    second = scope(env, "already-reviewed")
    repo.ensure(second)
    assert repo.claim("already-reviewed", "first")
    assert repo.finish("already-reviewed", "first", "idle")
    assert not repo.ensure({**second, "allow_publish": True})["allow_publish"]
    third = scope(env, "wrong-message")
    repo.ensure(third)
    assert not repo.ensure({**third, "source_message_id": "callback", "allow_publish": True})[
        "allow_publish"
    ]
    with pytest.raises(ValueError, match="different owner or origin"):
        repo.ensure(
            scope(env, user_id=env.other, origin_agent_id="other", origin_thread_id="other-thread")
        )
    assert repo.get("scope")["user_id"] == env.owner


def test_scope_members_keep_code_requirements_and_durable_execution_receipts(env):
    repo = env.repos.task_coordination_repo
    repo.ensure(scope(env))
    assert not repo.candidates()
    coding = {"project_path": "project", "test_commands": ["make all"]}
    member(env, coding_spec=coding)
    assert repo.candidates()[0]["scope_id"] == "scope"
    assert env.repos.task_dispatch_repo.get("member")["scope_id"] == "scope"
    assert env.repos.task_repo.claim("member")
    env.repos.task_repo.transition(
        "member",
        expected={"running"},
        state="completed",
        action="completed",
        fields={"result": "verified output"},
    )
    context = env.repos.task_dispatch_repo.get("member")
    env.repos.task_dispatch_repo.update_coding("member", {"phase": "verified"})
    assert env.repos.task_dispatch_repo.mark_returned(
        "member", 1, state="completed", event_id=context["current_event_id"]
    )
    record = repo.members("scope")[0]
    assert record["coding_spec"] == coding and record["coding_run"] == {"phase": "verified"}
    assert record["result"] == "verified output"
    assert record["event_id"] == record["returned_event_id"]
    event = record["event_id"]
    for action in ["archive", "restore", "reassign"]:
        env.repos.task_repo.transition(
            "member", expected={"completed"}, state="completed", action=action
        )
        assert repo.members("scope")[0]["event_id"] == event
    foreign = task(env, "foreign-scope-member", user_id=env.other, agent_id="other")
    foreign["dispatch"]["scope_id"] = "scope"
    with pytest.raises(ValueError, match="different owner or origin"):
        env.repos.task_repo.enqueue([foreign])
    assert env.repos.task_repo.get("foreign-scope-member") is None


def test_claim_defer_signatures_and_review_budget_are_compare_and_set(env):
    repo = env.repos.task_coordination_repo
    repo.ensure(scope(env))
    assert not repo.claim("scope", "first", max_turns=0)
    assert repo.claim("scope", "first")
    assert not repo.claim("scope", "another")
    assert not repo.finish("scope", "wrong", "idle")
    assert not repo.defer("scope", "wrong")
    assert repo.defer("scope", "first")
    assert not repo.defer("scope", "first")
    assert repo.get("scope")["review_turns"] == 0
    assert repo.get("scope")["last_signature"] == ""
    assert repo.claim("scope", "first")
    assert repo.decide("scope", "continue", "已核实产物", "")
    assert repo.finish("scope", "first", "idle")
    assert repo.get("scope")["summary"] == "已核实产物"
    assert not repo.claim("scope", "first")
    assert not repo.decide("scope", "complete", "late", "")
    for turn in range(2, 9):
        assert repo.claim("scope", f"signature-{turn}")
        assert repo.finish("scope", f"signature-{turn}", "idle")
    assert repo.get("scope")["review_turns"] == 8
    assert not repo.claim("scope", "ninth")
    previous = repo.get("scope")
    assert repo.require_user("scope", "请确认是否继续复核")
    waiting = repo.get("scope")
    assert waiting["last_signature"] == previous["last_signature"]
    assert waiting["decision"] == previous["decision"]
    assert waiting["review_turns"] == 8 and waiting["state"] == "needs_user"
    assert waiting["question"] == "请确认是否继续复核"


def test_explicit_owner_resume_consumes_human_input_once_and_can_revoke_publish(env):
    repo = env.repos.task_coordination_repo
    original = scope(env)
    repo.ensure(original)
    assert repo.claim("scope", "first")
    assert repo.decide("scope", "needs_user", "需要补充信息", "请选择范围")
    assert repo.finish("scope", "first", "needs_user")
    assert not repo.resume("scope", env.other, "foreign answer", allow_publish=True)
    assert repo.resume("scope", env.owner, "真实用户答复", allow_publish=True)
    resumed = repo.get("scope")
    assert resumed["state"] == "pending" and resumed["review_turns"] == 0
    assert resumed["goal_text"] == original["goal_text"]
    assert resumed["user_input"] == "真实用户答复"
    assert resumed["resume_seq"] == 1 and resumed["handled_resume_seq"] == 0
    assert resumed["allow_publish"] is True and not resumed["question"]
    assert not repo.resume("scope", env.owner, "not a waiting scope")
    assert repo.claim("scope", "resumed")
    assert repo.finish("scope", "resumed", "idle")
    assert repo.get("scope")["handled_resume_seq"] == 1
    assert repo.claim("scope", "new-member-results")
    assert repo.finish("scope", "new-member-results", "idle")
    assert repo.get("scope")["resume_seq"] == repo.get("scope")["handled_resume_seq"] == 1
    assert repo.claim("scope", "interrupted")
    assert repo.interrupt_running() == 1
    assert not repo.claim("scope", "replay-after-restart")
    assert not repo.candidates()
    assert repo.resume("scope", env.owner, "再试一次，不发布", allow_publish=False)
    assert repo.get("scope")["resume_seq"] == 2
    assert repo.get("scope")["handled_resume_seq"] == 1
    assert repo.get("scope")["allow_publish"] is False


def test_parent_stop_and_candidate_pagination_preserve_scope_identity(env):
    repo = env.repos.task_coordination_repo
    env.repos.task_repo.enqueue([task(env, "parent", agent_id="host", dispatch=None)])
    for attempt in (1, 2):
        repo.ensure(scope(env, f"scope-{attempt}", parent_task_id="parent", parent_attempt=attempt))
        member(env, f"scope-{attempt}", f"member-{attempt}")
    assert [row["scope_id"] for row in repo.for_parent("parent", 1)] == ["scope-1"]
    assert repo.candidates(limit=1, offset=1)[0]["scope_id"] == "scope-2"
    assert repo.claim("scope-1", "review")
    assert repo.stop_parent("parent", 1) == 1
    assert not repo.finish("scope-1", "review", "idle")
    assert not repo.resume("scope-1", env.owner, "resume stopped")
    assert [row["scope_id"] for row in repo.candidates()] == ["scope-2"]


def test_explicit_owner_stop_is_idempotent_and_invalidates_a_live_review(env):
    repo = env.repos.task_coordination_repo
    repo.ensure(scope(env))
    assert repo.claim("scope", "active-review")
    assert not repo.stop("scope", env.other)
    assert repo.get("scope")["state"] == "running"
    assert repo.stop("scope", env.owner)
    assert repo.stop("scope", env.owner)
    assert not repo.finish("scope", "active-review", "idle")
    assert not repo.resume("scope", env.owner, "not a stopped-goal restart")
    assert not repo.require_user("scope", "do not re-open")


def test_partial_v27_scope_columns_repair_preserves_goals_members_and_authority(env):
    repo = env.repos.task_coordination_repo
    original = repo.ensure(scope(env, allow_publish=True))
    member(env)
    with env.db.connect() as conn:
        conn.execute("ALTER TABLE task_coordination_scopes DROP COLUMN resume_seq")
        conn.execute("ALTER TABLE task_coordination_scopes DROP COLUMN handled_resume_seq")
    run_migrations(env.db)
    run_migrations(env.db)
    recovered = repo.get("scope")
    assert recovered["id"] == "scope" and recovered["allow_publish"] is True
    assert recovered["goal_text"] == original["goal_text"]
    assert recovered["resume_seq"] == recovered["handled_resume_seq"] == 0
    assert repo.members("scope")[0]["task_id"] == "member"
    with env.db.connect() as conn:
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
