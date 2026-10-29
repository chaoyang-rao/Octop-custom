"""Project grouping safety/API regression checks. All state is temporary."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage

from octop.api.deps import current_user, get_server
from octop.api.routers.chat.history import router
from octop.infra.agents.threads.fork import fork_dashboard_thread
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.repos.sessions import SessionRepo
from octop.infra.db.repos.threads import ThreadRepo
from octop.infra.db.repos.thread_messages import ThreadMessageInput, ThreadMessageRepo
from octop.infra.errors import OctopError
from octop.infra.gateway.threads import ThreadRegistry


class ProjectApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(prefix="octop-project-tests-")
        self.root = Path(self.tmp.name).resolve()
        self.project = self.root / "项目 A"
        self.project.mkdir()
        self.marker = self.project / "business.txt"
        self.marker.write_text("business data must survive grouping removal")
        self.db = SqlitePool(self.root / "control.sqlite3")
        run_migrations(self.db)
        with self.db.connect() as c:
            for uid in (1, 2):
                c.execute("INSERT INTO users(id,username,role,created_at) VALUES (?,?,?,?)",
                          (uid, f"test{uid}", "user", 1))
            for aid, shared in (("expert", 0), ("shared", 1), ("other", 0)):
                c.execute("INSERT INTO agents(agent_id,user_id,name,is_shared,created_at,updated_at) "
                          "VALUES (?,?,?,?,1,1)", (aid, 1, aid, shared))
        self.threads = ThreadRepo(self.db)
        self.messages = ThreadMessageRepo(self.db)
        self.registry = ThreadRegistry(session_repo=SessionRepo(self.db), thread_repo=self.threads)
        self.active = set()
        self.awaiting = set()
        self.policy = {}
        self.user = NS(id=1, is_admin=False)
        def get_row(aid):
            with self.db.connect() as c:
                row = c.execute("SELECT * FROM agents WHERE agent_id=?", (aid,)).fetchone()
            return NS(**dict(row)) if row else None
        agents = NS(get_row=get_row, get_config=lambda aid: {"workspace_dir": str(self.root)})
        gateway = NS(thread_registry=self.registry,
                     ws_hub=NS(is_turn_active=lambda tid: tid in self.active),
                     processor=NS(hitl_coordinator=NS(store=NS(
                         pending_thread_ids=lambda **kw: self.awaiting))))
        self.server = NS(user_manager=NS(get_by_id=lambda uid: NS(id=uid) if uid in (1,2) else None),
                         app_runtime=NS(agent_registry=agents, gateway=gateway),
                         services=NS(user_policy_repo=NS(get=lambda uid, key: self.policy.get(uid))))
        app = FastAPI()
        app.include_router(router, prefix="/api")
        app.dependency_overrides[current_user] = lambda: self.user
        app.dependency_overrides[get_server] = lambda: self.server
        @app.exception_handler(OctopError)
        async def error_handler(request, error):
            return JSONResponse(error.to_envelope(), status_code=error.status)
        self.client = TestClient(app)
        self.base = "/api/agents/expert"

    def tearDown(self):
        self.client.close()
        self.db.close()
        self.tmp.cleanup()

    def create(self, agent="expert", path=None):
        kwargs = {"json": {"project_path": path}} if path else {}
        response = self.client.post(f"/api/agents/{agent}/threads", **kwargs)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["thread_id"]

    def test_fresh_and_existing_database_upgrade_preserve_history_and_are_idempotent(self):
        tid = self.create()
        self.messages.append_if_ready(tid, [ThreadMessageInput("m1", "user", "{}", 1)])
        with self.db.connect() as c:
            c.execute("DROP TABLE thread_projects")
            c.execute("DROP INDEX idx_threads_project")
            c.execute("ALTER TABLE threads DROP COLUMN project_path")
            c.execute("ALTER TABLE threads DROP COLUMN project_name")
            c.execute("UPDATE _schema_version SET version=21")
        run_migrations(self.db)
        run_migrations(self.db)
        with self.db.connect() as c:
            self.assertEqual(c.execute("SELECT version FROM _schema_version").fetchone()[0], 22)
            self.assertEqual(c.execute("SELECT count(*) FROM threads").fetchone()[0], 1)
            self.assertEqual(c.execute("SELECT count(*) FROM thread_messages").fetchone()[0], 1)
        self.assertIsNone(self.threads.get(tid).project_path)
        self.assertEqual(self.registry.list_projects(agent_id="expert", user_id=1), [])

    def test_empty_project_persists_and_new_thread_reuses_custom_name(self):
        result = self.client.post(self.base+"/projects", json={
            "project_path": str(self.project), "project_name": "售后项目"})
        self.assertEqual(result.status_code, 201, result.text)
        self.assertEqual(result.json()["thread_count"], 0)
        # Close/reopen the actual pool to prove empty project grouping is durable.
        self.db.close()
        self.db = SqlitePool(self.root / "control.sqlite3")
        self.threads = ThreadRepo(self.db)
        self.messages = ThreadMessageRepo(self.db)
        self.registry.replace_repos(session_repo=SessionRepo(self.db), thread_repo=self.threads)
        tid = self.create(path=str(self.project))
        row = self.threads.get(tid)
        self.assertEqual((row.project_path, row.project_name), (str(self.project), "售后项目"))
        listed = self.client.get(self.base+"/threads").json()
        self.assertEqual(listed[0]["project_path"], str(self.project))
        self.assertEqual(self.client.get(self.base+"/projects").json()[0]["thread_count"], 1)
        legacy = self.create()
        self.assertIsNone(self.threads.get(legacy).project_path)

    def test_absolute_existing_directory_validation_and_symlink_policy_escape(self):
        for path in ("relative/project", str(self.root/"missing"), str(self.marker)):
            result = self.client.post(self.base+"/projects", json={"project_path": path})
            self.assertEqual(result.status_code, 400, result.text)
        allowed = self.root/"allowed"
        allowed.mkdir()
        self.policy[1] = str(allowed)
        rejected_paths = [str(self.project)]
        try:
            (allowed/"escape").symlink_to(self.project, target_is_directory=True)
        except OSError as error:
            # Windows may deny symlink creation without Developer Mode or the
            # create-symlink privilege; keep the remaining policy checks active.
            if os.name != "nt" or getattr(error, "winerror", None) != 1314:
                raise
        else:
            rejected_paths.append(str(allowed/"escape"))
        for path in rejected_paths:
            result = self.client.post(self.base+"/projects", json={"project_path": path})
            self.assertEqual(result.status_code, 400, result.text)
        self.assertEqual(self.client.post(self.base+"/projects", json={"project_path": str(allowed)}).status_code, 201)

    def test_project_data_is_isolated_by_user_and_expert(self):
        path = str(self.project)
        self.create(agent="shared", path=path)
        self.create(path=path)
        self.assertEqual(self.client.get("/api/agents/other/projects").json(), [])
        self.user = NS(id=2, is_admin=False)
        self.assertEqual(self.client.get(self.base+"/projects").status_code, 403)
        self.assertEqual(self.client.get("/api/agents/shared/projects").json(), [])
        other_tid = self.create(agent="shared", path=path)
        result = self.client.request("DELETE", "/api/agents/shared/projects", json={"project_path": path})
        self.assertEqual(result.status_code, 200)
        self.assertIsNone(self.threads.get(other_tid).project_path)
        self.assertEqual(self.registry.list_projects(agent_id="shared", user_id=1)[0]["thread_count"], 1)

    def test_cross_user_and_agent_thread_assignment_cannot_modify_rows(self):
        tid = self.create(agent="shared")
        body = {"project_path": str(self.project)}
        self.assertEqual(self.client.patch(self.base+f"/threads/{tid}/project", json=body).status_code, 404)
        self.user = NS(id=2, is_admin=False)
        result = self.client.patch(f"/api/agents/shared/threads/{tid}/project", json=body)
        self.assertEqual(result.status_code, 403)
        self.assertIsNone(self.threads.get(tid).project_path)

    def test_busy_and_awaiting_threads_reject_reassignment_and_project_removal(self):
        tid = self.create(path=str(self.project))
        target = self.root/"second"
        target.mkdir()
        for busy_set in (self.active, self.awaiting):
            busy_set.add(tid)
            moved = self.client.patch(self.base+f"/threads/{tid}/project",
                                      json={"project_path": str(target)})
            removed = self.client.request("DELETE", self.base+"/projects",
                                          json={"project_path": str(self.project)})
            self.assertEqual(moved.status_code, 409)
            self.assertEqual(removed.status_code, 409)
            self.assertEqual(self.threads.get(tid).project_path, str(self.project))
            busy_set.clear()
        moved = self.client.patch(self.base+f"/threads/{tid}", json={"project_path": str(target)})
        self.assertEqual(moved.status_code, 200, moved.text)
        self.assertEqual(moved.json()["project_path"], str(target))

    def test_group_removal_preserves_transcript_and_business_files(self):
        tid = self.create(path=str(self.project))
        self.messages.append_if_ready(tid, [ThreadMessageInput("m1", "user", "{}", 1)])
        result = self.client.request("DELETE", self.base+"/projects", json={"project_path": str(self.project)})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["unassigned_threads"], 1)
        self.assertTrue(self.marker.is_file())
        self.assertEqual(self.marker.read_text(), "business data must survive grouping removal")
        self.assertIsNone(self.threads.get(tid).project_path)
        self.assertEqual(self.messages.head(tid), 1)
        self.assertEqual(self.client.get(self.base+"/projects").json(), [])

    def test_ungrouping_and_missing_directory_removal_are_metadata_only(self):
        tid = self.create(path=str(self.project))
        moved = self.client.patch(self.base+f"/threads/{tid}/project", json={"project_path": None})
        self.assertEqual(moved.status_code, 200)
        self.assertIsNone(self.threads.get(tid).project_path)
        self.assertTrue(self.marker.is_file())
        # Removing a stale grouping must still be possible after an external rename.
        renamed = self.root/"renamed outside Octop"
        self.project.rename(renamed)
        removed = self.client.request("DELETE", self.base+"/projects",
                                      json={"project_path": str(self.project)})
        self.assertEqual(removed.status_code, 200)
        self.assertTrue((renamed/"business.txt").is_file())
        self.assertIsNotNone(self.threads.get(tid))

    def test_admin_impersonation_uses_target_users_policy(self):
        self.user = NS(id=2, is_admin=True)
        allowed = self.root/"allowed"
        allowed.mkdir()
        self.policy[1] = str(allowed)
        denied = self.client.post(self.base+"/projects?as_user=1",
                                  json={"project_path": str(self.project)})
        self.assertEqual(denied.status_code, 400)
        accepted = self.client.post(self.base+"/projects?as_user=1",
                                    json={"project_path": str(allowed)})
        self.assertEqual(accepted.status_code, 201)
        self.assertEqual(self.registry.list_projects(agent_id="expert", user_id=2), [])
        self.user = NS(id=2, is_admin=False)
        self.assertEqual(self.client.get(self.base+"/projects?as_user=1").status_code, 403)

    def test_fork_and_slash_new_inherit_project(self):
        tid = self.create(path=str(self.project))
        source = self.threads.get(tid)
        graph = NS(aget_state=AsyncMock(return_value=NS(values={"messages": [
            HumanMessage(content="question", id="u1"), AIMessage(content="answer", id="a1")]})),
            aupdate_state=AsyncMock())
        result = asyncio.run(fork_dashboard_thread(thread_registry=self.registry,
                            harness=NS(graph=graph), source=source, user_id=1, message_id="a1"))
        self.assertEqual(self.threads.get(result["thread_id"]).project_path, str(self.project))
        self.assertEqual(result["project_name"], self.project.name)
        self.assertEqual(graph.aupdate_state.await_count, 1)
        new_id = asyncio.run(self.registry.reset_by_session_key(result["session_key"]))
        self.assertEqual(self.threads.get(new_id).project_path, str(self.project))


if __name__ == "__main__":
    unittest.main()
