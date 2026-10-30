"""Primary identity and project ownership regressions; no live model requests."""
from types import SimpleNamespace as NS
import unittest
from langchain_core.messages import AIMessage
from octop.infra.agents.manager import AgentManager
from octop.infra.agents.teams.primary import (
    PrimaryRoom, current_primary_room, primary_request, primary_room_scope, stamp_primary_chunk,
)


class PrimaryTeamTests(unittest.TestCase):
    def test_same_primary_request_preserves_explicit_tools_and_model(self):
        room = PrimaryRoom("group", "lead", "thread", 1)
        original = {"thread_id": "thread", "model": "selected", "mcp_servers": ["cli"],
                    "configurable": {"session_key": "session", "user": "1"}}
        prepared = primary_request(original, room, ["lead", "member"])
        self.assertEqual(prepared["agent_id"], "lead")
        self.assertEqual(prepared["model"], "selected")
        self.assertEqual(prepared["mcp_servers"], ["cli"])
        self.assertEqual(prepared["configurable"]["team_peers"], ["member"])
        self.assertNotIn("octop_team_id", original["configurable"])

    def test_actor_and_transport_are_distinct_without_mutating_messages(self):
        room = PrimaryRoom("group", "lead", "thread", 1)
        message = AIMessage(content="回答")
        chunk = {"type": "state_snapshot", "data": {"messages": [message]}}
        stamped = stamp_primary_chunk(chunk, room)
        self.assertEqual(stamped["agent_id"], "group")
        self.assertEqual(stamped["speaker_agent_id"], "lead")
        self.assertEqual(stamped["turn_owner_agent_id"], "group")
        self.assertEqual(stamped["data"]["messages"][0].additional_kwargs["speaker_agent_id"], "lead")
        self.assertEqual(message.additional_kwargs, {})

    def test_scope_restores_after_nested_rooms(self):
        a, b = PrimaryRoom("a", "lead", "a-t", 1), PrimaryRoom("b", "lead", "b-t", 1)
        with primary_room_scope(a):
            with primary_room_scope(b):
                self.assertEqual(current_primary_room(), b)
            self.assertEqual(current_primary_room(), a)
        self.assertIsNone(current_primary_room())

    def test_project_path_uses_owned_room_binding_for_primary_only(self):
        manager = AgentManager.__new__(AgentManager)
        manager._repos = NS(thread_repo=NS(get=lambda tid: NS(agent_id="group", project_path="owned-project", project_name="Demo", user_id=1)))
        with primary_room_scope(PrimaryRoom("group", "lead", "thread", 1)):
            self.assertEqual(manager._thread_project_config("lead", "thread"), {"octop_project_path": "owned-project", "octop_project_name": "Demo"})
            self.assertEqual(manager._thread_project_config("other", "thread"), {})


if __name__ == "__main__":
    unittest.main()
