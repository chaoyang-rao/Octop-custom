"""Server-owned project metadata must override caller-supplied values."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from octop.infra.agents.manager import AgentManager
from octop.infra.agents.threads.project_runtime import thread_project_config


class ProjectRequestTests(unittest.TestCase):
    def manager(self, row):
        manager = AgentManager.__new__(AgentManager)
        manager._repos = SimpleNamespace(thread_repo=SimpleNamespace(get=lambda tid: row))
        manager.get_config = lambda agent_id: {}
        return manager

    def row(self, path="/trusted/project", agent_id="codex"):
        return SimpleNamespace(agent_id=agent_id, project_path=path, project_name="Demo", user_id=2)

    def test_request_uses_database_binding_and_preserves_other_config(self):
        manager = self.manager(self.row())
        request = {
            "thread_id": "t1",
            "messages": [],
            "user": "2",
            "configurable": {
                "thread_id": "t1",
                "session_key": "dashboard",
                "octop_project_path": "/forged",
                "octop_project_name": "Forged",
            },
        }
        for source in ("web", "team"):
            with self.subTest(source=source):
                result = manager._prepare_stream_request("codex", {**request, "source": source})
                self.assertEqual(result["configurable"]["octop_project_path"], "/trusted/project")
                self.assertEqual(result["configurable"]["octop_project_name"], "Demo")
                self.assertEqual(result["configurable"]["thread_id"], "t1")
                self.assertEqual(result["configurable"]["session_key"], "dashboard")
        self.assertEqual(request["configurable"]["octop_project_path"], "/forged")

    def test_unbound_thread_cannot_forge_project_config(self):
        manager = self.manager(self.row(path=None))
        result = manager._prepare_stream_request(
            "codex",
            {
                "thread_id": "t1",
                "messages": [],
                "configurable": {"octop_project_path": "/forged", "octop_project_name": "fake"},
            },
        )
        self.assertNotIn("octop_project_path", result["configurable"])
        self.assertNotIn("octop_project_name", result["configurable"])

    def test_binding_is_refreshed_on_each_turn(self):
        row = self.row()
        manager = self.manager(row)
        req = {"thread_id": "t1", "messages": []}
        self.assertEqual(
            manager._prepare_stream_request("codex", req)["configurable"]["octop_project_path"],
            row.project_path,
        )
        row.project_path = "/another/project"
        self.assertEqual(
            manager._prepare_stream_request("codex", req)["configurable"]["octop_project_path"],
            row.project_path,
        )

    def test_another_experts_row_is_not_used(self):
        repo = SimpleNamespace(get=lambda tid: self.row(agent_id="other"))
        self.assertEqual(thread_project_config(repo, agent_id="codex", thread_id="t1"), {})

    def test_conflicting_thread_ids_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            self.manager(self.row())._prepare_stream_request(
                "codex", {"thread_id": "t1", "messages": [], "configurable": {"thread_id": "other"}}
            )


def test_avatar_only_save_preserves_runtime_and_other_config():
    from octop.infra.agents.settings.profile import parse_config_json

    row = SimpleNamespace(config_json='{"workspace_dir":"keep","avatar":{"shape":"blob"}}')
    repo = SimpleNamespace(get=lambda _: row, update_config=Mock())
    manager = AgentManager.__new__(AgentManager)
    manager._repos = SimpleNamespace(agent_repo=repo)
    manager._schedule_reload = Mock()
    manager.set_avatar_config("expert", {"shape": "cloud", "color": "jade"})
    persisted = parse_config_json(repo.update_config.call_args.kwargs["config_json"])
    assert persisted["workspace_dir"] == "keep"
    assert persisted["avatar"] == {"shape": "cloud", "color": "jade"}
    manager._schedule_reload.assert_not_called()
