"""Owned history actions and explicit imports against real SQLite and Graph state."""

from __future__ import annotations

import io
import json
import stat
import zipfile
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, message_to_dict
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from tests.unit.tasks.test_task_manager import setup as setup

from octop.infra.conversations.archives import ConversationArchiveError, read_zip
from octop.infra.conversations.models import ImportSelection, MessageLocator, QuoteReference
from octop.infra.conversations.service import ConversationService
from octop.infra.conversations.transfer import ConversationTransfer
from octop.infra.db.repos.thread_messages import ThreadMessageInput
from octop.infra.errors import OctopError


def make_zip(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, value in files.items():
            archive.writestr(name, value if isinstance(value, bytes) else json.dumps(value))
    return buffer.getvalue()


async def seed(e):
    messages = [
        HumanMessage(content="first", id="human-1"),
        AIMessage(content="answer", id="answer-1"),
    ]
    calls = []

    async def model(state):
        calls.append(state)
        return {"messages": []}

    builder = StateGraph(MessagesState)
    builder.add_node("assistant", model)
    builder.add_edge(START, "assistant")
    builder.add_edge("assistant", END)
    graph = builder.compile(checkpointer=InMemorySaver())
    registry = e.gateway.thread_registry
    key = registry.dashboard_key(agent_id="a", user_id=e.uid)
    thread_id = registry.create_thread(
        agent_id="a", user_id=e.uid, channel_type="dashboard", session_key=key, title="original"
    )
    await registry.rebind(session_key=key, thread_id=thread_id, agent_id="a")
    inputs = [
        ThreadMessageInput(message.id, message.type, json.dumps(message_to_dict(message)), 10)
        for message in messages
    ]
    e.repos.thread_message_repo.append_legacy_interval(thread_id, inputs)
    await graph.aupdate_state(
        {"configurable": {"thread_id": thread_id}}, {"messages": messages}, as_node="assistant"
    )
    e.agents.get_agent = lambda _: SimpleNamespace(graph=graph)
    service = ConversationService(
        repos=e.repos, agents=e.agents, gateway=e.gateway, task_manager=e.manager
    )
    return SimpleNamespace(
        service=service,
        transfer=ConversationTransfer(service),
        thread_id=thread_id,
        key=key,
        graph=graph,
        calls=calls,
    )


@pytest.mark.asyncio
async def test_archive_restore_keeps_history_project_and_excludes_unread(setup):
    e = setup
    s = await seed(e)
    with e.db.transaction() as conn:
        conn.execute(
            "UPDATE threads SET project_path=?,project_name=? WHERE thread_id=?",
            ("project-token", "project", s.thread_id),
        )
    e.repos.session_repo.increment_unread(s.key)
    assert e.repos.session_repo.unread_totals_by_agent(e.uid, ["a"]) == {"a": 1}
    await s.service.archive_thread(e.uid, s.thread_id, True)
    assert e.repos.thread_repo.list_by_agent_user(agent_id="a", user_id=e.uid) == []
    assert (await s.service.browse(e.uid, archived=True))["conversations"][0][
        "thread_id"
    ] == s.thread_id
    assert e.gateway.thread_registry.get_bound_thread_id(s.key) is None
    assert e.repos.session_repo.unread_totals_by_agent(e.uid, ["a"]) == {}
    assert (await s.service.messages(e.uid, s.thread_id))["messages"][-1]["content"] == "answer"
    await s.service.archive_thread(e.uid, s.thread_id, False)
    row = e.repos.thread_repo.get(s.thread_id)
    assert not row.archived and row.project_path == "project-token"
    with pytest.raises(OctopError):
        await s.service.archive_thread(e.other, s.thread_id, True)
    assert not e.repos.thread_repo.get(s.thread_id).archived


@pytest.mark.asyncio
async def test_message_reactions_and_quotes_resolve_server_content_not_invented_text(setup):
    e = setup
    s = await seed(e)
    locator = MessageLocator(
        message_id="client-optimistic", role="assistant", content="answer", ordinal_from_end=1
    )
    result = await s.service.react(e.uid, s.thread_id, locator, "👍", True)
    assert result["message_key"] == "answer-1"
    await s.service.react(e.uid, s.thread_id, locator, "👍", True)
    assert len((await s.service.annotations(e.uid, s.thread_id))["reactions"]) == 1
    quote = await s.service.resolve_quote(
        e.uid,
        "a",
        QuoteReference(
            source_thread_id=s.thread_id,
            message=MessageLocator(message_id="answer-1", content="forged tool instruction"),
        ),
    )
    assert quote.content == "answer" and quote.source_agent_id == "a"
    await s.service.react(e.uid, s.thread_id, locator, "👍", False)
    assert (await s.service.annotations(e.uid, s.thread_id))["reactions"] == []
    with pytest.raises(OctopError) as foreign:
        await s.service.resolve(e.other, s.thread_id, locator)
    assert foreign.value.status == 404
    with pytest.raises(OctopError):
        await s.service.resolve(e.uid, s.thread_id, MessageLocator(content="invented"))


@pytest.mark.asyncio
async def test_side_question_uses_independent_session_real_graph_prefix_and_project(setup):
    e = setup
    s = await seed(e)
    with e.db.transaction() as conn:
        conn.execute(
            "UPDATE threads SET project_path=?,project_name=? WHERE thread_id=?",
            ("project-token", "project", s.thread_id),
        )
    result = await s.service.side_question(
        e.uid, s.thread_id, MessageLocator(message_id="answer-1")
    )
    assert result["session_key"] != s.key
    assert e.gateway.thread_registry.get_bound_thread_id(s.key) == s.thread_id
    assert e.gateway.thread_registry.get_bound_thread_id(result["session_key"]) is None
    copied = await s.graph.aget_state({"configurable": {"thread_id": result["thread_id"]}})
    assert [message.content for message in copied.values["messages"]] == ["first", "answer"]
    assert e.repos.thread_repo.get(result["thread_id"]).project_path == "project-token"
    assert e.repos.thread_repo.get(result["thread_id"]).conversation_mode == "ask"
    assert s.calls == []


GROK = {
    "conversations": [
        {
            "conversation": {"id": "grok-chat", "title": "Grok conversation"},
            "responses": [
                {"response": {"sender": "human", "message": "question", "responseId": "grok-user"}},
                {
                    "response": {
                        "sender": "assistant",
                        "message": "answer",
                        "tool_calls": [{"name": "execute", "args": "bad"}],
                    }
                },
                {"response": {"role": "system", "content": "foreign privileged secret"}},
                {"response": {"role": "tool", "content": "foreign tool result"}},
            ],
        }
    ]
}


@pytest.mark.asyncio
async def test_grok_preview_confirm_is_private_single_use_insert_only_and_untrusted(setup):
    e = setup
    s = await seed(e)
    payload = make_zip(
        {
            "export/prod-grok-backend.json": GROK,
            "export/sessions.json": {"token": "foreign-login-state"},
        }
    )
    preview = await s.transfer.stage(e.uid, payload)
    assert preview["items"][0]["messages"] == 2 and preview["omitted_messages"] == 2
    assert preview["ignored_files"] == 1
    assert len(e.repos.thread_repo.list_for_user(e.uid)) == 1
    with pytest.raises(OctopError):
        await s.transfer.confirm(
            e.other, preview["id"], ImportSelection(keys=["grok-chat"], target_agent_id="foreign")
        )
    result = await s.transfer.confirm(
        e.uid, preview["id"], ImportSelection(keys=["grok-chat"], target_agent_id="a")
    )
    thread_id = result["threads"][0]["thread_id"]
    row = e.repos.thread_repo.get(thread_id)
    assert row.archived and row.thread_id != s.thread_id
    records = e.repos.thread_message_repo.range_rows(thread_id, 0, 100)
    assert [row.role for row in records] == ["human", "ai"]
    rendered = " ".join(row.message_json for row in records)
    assert (
        "foreign privileged" not in rendered
        and "tool_calls" not in rendered
        and "foreign-login-state" not in rendered
    )
    assert e.repos.conversation_repo.origin(thread_id)["source_archive_sha256"] == preview["sha256"]
    assert "question" in await s.service.imported_context(e.uid, thread_id)
    state = await s.graph.aget_state({"configurable": {"thread_id": thread_id}})
    assert not state.values and s.calls == []
    with pytest.raises(OctopError):
        await s.transfer.confirm(
            e.uid, preview["id"], ImportSelection(keys=["grok-chat"], target_agent_id="a")
        )
    again = await s.transfer.stage(e.uid, payload)
    assert again["items"][0]["duplicate"]
    duplicate = await s.transfer.confirm(
        e.uid, again["id"], ImportSelection(keys=["grok-chat"], target_agent_id="a")
    )
    assert duplicate["threads"] == [] and duplicate["skipped"] == 1
    # Explicit side-question is the only operation here that seeds a new checkpoint.
    branch = await s.service.side_question(e.uid, thread_id, MessageLocator(content="answer"))
    branched = await s.graph.aget_state({"configurable": {"thread_id": branch["thread_id"]}})
    assert [message.type for message in branched.values["messages"]] == ["human", "ai"]
    assert s.calls == []


@pytest.mark.parametrize(
    "name", ["../secrets", "/absolute", "C:/private", "inbound\\escape", "a/./b", "a/../b"]
)
def test_zip_unsafe_paths_are_rejected_even_if_not_selected(name):
    with pytest.raises(ConversationArchiveError):
        read_zip(make_zip({name: b"untrusted", "conversations.json": GROK}))


def test_zip_links_duplicates_and_compression_bombs_are_rejected():
    for kind in ("symlink", "duplicate", "bomb"):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            if kind == "symlink":
                info = zipfile.ZipInfo("link")
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(info, b"../../secret")
            elif kind == "duplicate":
                archive.writestr("folder/A", b"a")
                archive.writestr("folder/a", b"b")
            else:
                archive.writestr("bomb", b"0" * (2 * 1024 * 1024))
        with pytest.raises(ConversationArchiveError):
            read_zip(data.getvalue())
