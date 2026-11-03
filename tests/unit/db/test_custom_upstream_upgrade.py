"""Keep local v22/v23 data while introducing upstream's colliding schema versions."""

from pathlib import Path

import pytest

from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.repos.agents import AgentRepo
from octop.infra.db.repos.tasks import TaskRepo
from octop.infra.db.repos.threads import ThreadRepo
from octop.infra.db.repos.users import UserRepo


@pytest.mark.parametrize("legacy_version", [22, 23])
def test_upgrade_custom_watermark_preserves_projects_and_workflows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, legacy_version: int
) -> None:
    monkeypatch.setenv("OCTOP_HOME", str(tmp_path))
    pool = SqlitePool(tmp_path / "upgrade.db")
    run_migrations(pool)
    user_id = UserRepo(pool).create(username="owner", password_hash="test-only", role="admin")
    AgentRepo(pool).create(
        agent_id="custom-expert", user_id=user_id, name="小通", config_json='{"custom":true}'
    )
    ThreadRepo(pool).insert(
        thread_id="custom-thread",
        agent_id="custom-expert",
        user_id=user_id,
        channel_type="web",
        session_key="kept-session",
        title="保留的会话",
    )
    TaskRepo(pool).create_workflow(
        workflow_id="kept-workflow",
        user_id=user_id,
        name="保留的工作流",
        definition={"steps": []},
        enabled=False,
        next_run_at=None,
    )
    project = str(tmp_path / "project")
    with pool.connect() as conn:
        conn.execute(
            "UPDATE threads SET project_path=?,project_name=?,archived=1 WHERE thread_id=?",
            (project, "项目甲", "custom-thread"),
        )
        conn.execute(
            "INSERT INTO thread_projects(agent_id,user_id,project_path,project_name,created_at) "
            "VALUES(?,?,?,?,?)",
            ("custom-expert", user_id, project, "项目甲", 123),
        )
        # Reproduce the physical custom schema before upstream published 22-25.
        for table in (
            "user_totp",
            "user_webauthn_credentials",
            "user_recovery_codes",
            "auth_challenges",
            "resource_group_grant",
            "user_group_member",
            "user_group",
        ):
            conn.execute(f"DROP TABLE {table}")
        for column in ("mfa_version", "mfa_failed_count", "mfa_locked_until", "password_version"):
            conn.execute(f"ALTER TABLE users DROP COLUMN {column}")
        conn.execute("ALTER TABLE skill_packages DROP COLUMN shared")
        conn.execute("UPDATE _schema_version SET version=?", (legacy_version,))

    run_migrations(pool)
    run_migrations(pool)
    with pool.connect() as conn:
        assert conn.execute("SELECT version FROM _schema_version").fetchone()[0] == 28
        tables = {
            row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {"user_group", "user_group_member", "resource_group_grant", "user_totp"} <= tables
        user_columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
        assert {"mfa_version", "password_version"} <= user_columns
        group_columns = {row["name"] for row in conn.execute("PRAGMA table_info(user_group)")}
        assert {"enabled", "avatar_icon"} <= group_columns
        package_columns = {row["name"] for row in conn.execute("PRAGMA table_info(skill_packages)")}
        assert "shared" in package_columns
        thread = conn.execute(
            "SELECT title,session_key,project_path,project_name,archived FROM threads "
            "WHERE thread_id=?",
            ("custom-thread",),
        ).fetchone()
        assert tuple(thread) == ("保留的会话", "kept-session", project, "项目甲", 1)
        assert conn.execute("SELECT COUNT(*) FROM thread_projects").fetchone()[0] == 1
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
    workflow = TaskRepo(pool).workflow("kept-workflow")
    assert workflow is not None and workflow.name == "保留的工作流"
    assert AgentRepo(pool).get("custom-expert").name == "小通"
