"""Primary identity, room transport and cross-conversation authorization."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from octop.infra.agents.manager import AgentManager
from octop.infra.agents.middleware.team_context import TeamConversationContextMiddleware
from octop.infra.agents.teams.primary import PrimaryRoom, current_primary_room, primary_room_scope
from octop.infra.agents.teams.service import TeamService
from octop.infra.agents.teams.team_manager import wire_host_dispatch
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.repos.thread_messages import ThreadMessageInput
from octop.infra.db.services import RepoBundle
from octop.infra.history.conversations import ConversationHistory, build_conversation_tools


@pytest.fixture
def primary_env(tmp_path):
    db = SqlitePool(tmp_path / "primary.sqlite")
    run_migrations(db)
    repos = RepoBundle.from_pool(db)
    one = repos.user_repo.create(username="one", role="user")
    two = repos.user_repo.create(username="two", role="user")
    for aid, uid, name, kind in [
        ("lead", one, "小通", "expert"),
        ("member", one, "数据分析师", "expert"),
        ("room", one, "规则群", "team"),
        ("lead-two", two, "小通", "expert"),
    ]:
        repos.agent_repo.create(
            agent_id=aid,
            user_id=uid,
            name=name,
            kind=kind,
            template_name="general-assistant" if aid.startswith("lead") else None,
        )

    class Workspace:
        def read_text(self, path):
            return json.dumps({"members": ["member"]})

    teams = TeamService(repos, workspace_for=lambda _: Workspace())
    for tid, aid, uid in [
        ("group", "room", one),
        ("private", "lead", one),
        ("other-private", "member", two),
    ]:
        repos.thread_repo.insert(
            thread_id=tid,
            agent_id=aid,
            user_id=uid,
            channel_type="dashboard",
            session_key=f"{aid}:{uid}:{tid}",
            title=tid,
        )

    repos.agent_repo.set_shared("member", True)

    def append(tid, role, text, speaker=None, *, reasoning="", escaped=False):
        wire = {
            "type": role,
            "data": {
                "content": text,
                "additional_kwargs": {"speaker_agent_id": speaker, "reasoning_content": reasoning},
            },
        }
        repos.thread_message_repo.append_if_ready(
            tid,
            [
                ThreadMessageInput(
                    f"{tid}-{repos.thread_message_repo.head(tid) + 1}",
                    role,
                    json.dumps(wire, ensure_ascii=escaped),
                    1,
                )
            ],
        )

    append("group", "human", "用户的群问题")
    append("group", "ai", "成员的薪酬分析：50%_正常", "member", escaped=True)
    append("group", "ai", "小通的结论", "lead", reasoning="不应导出深度思考")
    append("group", "tool", "工具结果42", "member")
    append("private", "ai", "单独对话的真实记录", "lead")
    append("other-private", "ai", "另一个用户的秘密", "member")
    yield NS(db=db, repos=repos, teams=teams, one=one, two=two)
    db.close()


def test_all_teams_use_their_owned_primary_and_include_it_in_roster(primary_env):
    env = primary_env
    assert env.teams.primary_for_team("room").agent_id == "lead"
    assert env.teams.member_ids("room") == ["lead", "member"]
    assert env.teams.primary_expert_for_user(env.two).agent_id == "lead-two"
    assert env.teams.primary_expert_for_user(999) is None
    assert env.teams.validate_member_ids(NS(id=env.one, is_admin=False), ["member"]) == [
        "lead",
        "member",
    ]


def test_history_read_paginates_both_kinds_without_copying_or_leaking(primary_env):
    env = primary_env
    history = ConversationHistory(env.repos)
    listed = history.list(env.one)["conversations"]
    assert {row["thread_id"] for row in listed} == {"group", "private"}
    first = history.read(env.one, "group", limit=2)
    assert [m["content"] for m in first["messages"]] == ["小通的结论"]
    assert "reasoning_content" not in json.dumps(first)
    older = history.read(env.one, "group", before_seq=first["next_before_seq"], limit=2)
    assert [m["speaker_agent_id"] for m in older["messages"]] == [None, "member"]
    assert "工具结果42" in json.dumps(
        history.read(env.one, "group", limit=2, include_tools=True), ensure_ascii=False
    )
    with pytest.raises(PermissionError):
        history.read(env.one, "other-private")
    assert env.repos.thread_message_repo.head("group") == 4
    assert env.repos.thread_message_repo.head("private") == 1


def test_history_search_handles_chinese_json_escapes_and_literal_wildcards(primary_env):
    history = ConversationHistory(primary_env.repos)
    for query in ["薪酬", "50%_", "%"]:
        matches = history.search(primary_env.one, query)["matches"]
        assert len(matches) == 1
        assert matches[0]["thread_id"] == "group"
    assert history.search(primary_env.one, "秘密")["matches"] == []
    assert history.search(primary_env.one, "不应导出深度思考")["matches"] == []
    assert history.search(primary_env.one, "' OR 1=1 --")["matches"] == []


@pytest.mark.asyncio
async def test_history_tool_uses_current_user_not_agent_owner_or_admin_flag(
    primary_env, monkeypatch
):
    import octop.infra.history.conversations as module

    tool = build_conversation_tools(primary_env.repos)[0]
    cfg = {"user": str(primary_env.two), "agent_id": "member", "user_is_admin": True}
    monkeypatch.setattr(module, "get_config", lambda: {"configurable": cfg})
    result = json.loads(await tool.ainvoke({"action": "list"}))
    assert {x["thread_id"] for x in result["conversations"]} == {"other-private"}
    assert "error" in json.loads(await tool.ainvoke({"action": "read", "thread_id": "group"}))
    cfg.pop("user")
    assert "error" in json.loads(await tool.ainvoke({"action": "list"}))


@pytest.mark.asyncio
async def test_model_context_is_ephemeral_and_includes_all_recent_member_authors(
    primary_env, monkeypatch
):
    import octop.infra.agents.middleware.team_context as module

    env = primary_env
    middleware = TeamConversationContextMiddleware(repos=env.repos, teams=env.teams)
    cfg = {
        "agent_id": "lead",
        "user": str(env.one),
        "thread_id": "group",
        "octop_team_id": "room",
        "octop_team_thread_id": "group",
    }
    monkeypatch.setattr(module, "runtime_config", lambda _: {"configurable": cfg})
    original = [HumanMessage(content="继续讨论")]

    class Request:
        messages = original
        tools = [NS(name="conversation_history")]

        def override(self, **kwargs):
            return NS(messages=kwargs["messages"])

    seen = []

    async def handler(request):
        seen.extend(request.messages)
        return "response"

    assert await middleware.awrap_model_call(Request(), handler) == "response"
    transcript = "\n".join(str(m.content) for m in seen)
    assert "小通" in transcript and "成员的薪酬分析" in transcript
    assert "另一个用户的秘密" not in transcript and "不应导出深度思考" not in transcript
    assert Request.messages == original and len(original) == 1
    assert env.repos.thread_message_repo.head("group") == 4


@pytest.mark.asyncio
async def test_stream_calls_the_same_real_primary_as_private_chat_and_preserves_owner(primary_env):
    env = primary_env
    manager = object.__new__(AgentManager)
    manager._repos, manager._teams = env.repos, env.teams
    active = set()
    calls = []

    @asynccontextmanager
    async def lock(*args):
        yield

    @asynccontextmanager
    async def tracked(aid, tid=""):
        active.add(aid)
        try:
            yield
        finally:
            active.remove(aid)

    original = AIMessage(content="本人回复", id="answer")

    class Harness:
        async def stream(self, aid, req):
            calls.append((aid, req, current_primary_room()))
            if current_primary_room():
                assert active == {"lead", "room"}
            yield {"type": "token", "content": "本人回复"}
            yield {"type": "state_snapshot", "data": {"messages": [original]}}

    manager._harness_manager = Harness()
    manager._thread_execution_lock = lock
    manager._track_invocation = tracked
    manager._apply_pending_bootstrap_graph_refresh = lambda _: None
    manager._prepare_stream_request = lambda _, request: request
    manager._stream_model_label = lambda *_: ""
    frames = [
        x
        async for x in manager.stream(
            "room", {"thread_id": "group", "configurable": {"user": str(env.one)}}
        )
    ]
    assert calls[0][0] == "lead"
    assert calls[0][1]["agent_id"] == "lead"
    assert calls[0][1]["configurable"]["agent_id"] == "lead"
    assert calls[0][1]["configurable"]["team_peers"] == ["member"]
    assert frames[0]["agent_id"] == "room" and frames[0]["speaker_agent_id"] == "lead"
    assert frames[1]["data"]["messages"][0].additional_kwargs["speaker_agent_id"] == "lead"
    assert original.additional_kwargs == {} and active == set() and current_primary_room() is None
    [x async for x in manager.stream("lead", {"thread_id": "private"})]
    assert calls[1][0] == "lead" and calls[1][2] is None


@pytest.mark.asyncio
async def test_primary_dispatch_uses_room_inbox_but_private_dispatch_remains_private():
    submitted, direct = [], []

    async def original(**kwargs):
        direct.append(kwargs)
        return "direct"

    harness = NS(
        enabled=True,
        call_peer=original,
        submit_peer=lambda **kw: submitted.append(kw) or "submitted",
    )
    wire_host_dispatch(harness, is_team=lambda aid: aid == "room")
    scope = PrimaryRoom("room", "lead", "group", 1)
    with primary_room_scope(scope):
        assert (
            await harness.call_peer(
                from_agent_id="lead",
                to_agent_id="member",
                message="任务",
                user_id=1,
                source_thread_id="group",
            )
            == "submitted"
        )
    assert submitted[0]["from_agent_id"] == "room"
    assert (
        await harness.call_peer(
            from_agent_id="lead",
            to_agent_id="member",
            message="私聊",
            user_id=1,
            source_thread_id="private",
        )
        == "direct"
    )
    assert direct[0]["from_agent_id"] == "lead"


def test_revoked_expert_is_not_visible_even_when_the_thread_is_owned(primary_env):
    env = primary_env
    history = ConversationHistory(env.repos)
    assert history.list(env.two)["conversations"]
    env.repos.agent_repo.set_shared("member", False)
    assert history.list(env.two)["conversations"] == []
    assert history.search(env.two, "秘密")["matches"] == []
    with pytest.raises(PermissionError):
        history.read(env.two, "other-private")


@pytest.mark.asyncio
async def test_parallel_primary_dispatch_cannot_cross_room_or_user_scope():
    import asyncio

    submitted = []

    async def original(**kwargs):
        raise AssertionError("group dispatch must use its own inbox")

    harness = NS(
        enabled=True, call_peer=original, submit_peer=lambda **kw: submitted.append(kw) or "ok"
    )
    wire_host_dispatch(harness, is_team=lambda aid: aid.startswith("room"))

    async def run(room):
        with primary_room_scope(room):
            await asyncio.sleep(0)
            await harness.call_peer(
                from_agent_id=room.primary_id,
                to_agent_id="member",
                message=room.thread_id,
                user_id=room.user_id,
                source_thread_id=room.thread_id,
            )
            assert current_primary_room() == room

    await asyncio.gather(
        run(PrimaryRoom("room-a", "lead", "group-a", 1)),
        run(PrimaryRoom("room-b", "lead", "group-b", 2)),
    )
    assert {
        (item["from_agent_id"], item["source_thread_id"], item["user_id"]) for item in submitted
    } == {("room-a", "group-a", 1), ("room-b", "group-b", 2)}
    assert current_primary_room() is None


def test_primary_binding_survives_renaming_without_switching_to_another_expert(primary_env):
    env = primary_env
    env.teams.require_primary(env.one)
    env.repos.agent_repo.update_config("lead", name="通用主专家")
    env.repos.agent_repo.create(
        agent_id="copy", user_id=env.one, name="其他通用助手", template_name="general-assistant"
    )
    assert env.teams.primary_for_team("room").agent_id == "lead"
    assert env.repos.settings_repo.get(f"teams.primary_expert.{env.one}") == "lead"


def test_cancel_routes_only_the_selected_room_to_the_real_primary(primary_env):
    manager = object.__new__(AgentManager)
    manager._teams = primary_env.teams
    cancelled = []
    manager._harness_manager = NS(cancel=lambda aid, tid: cancelled.append((aid, tid)))
    manager.cancel_stream("room", "group")
    manager.cancel_stream("lead", "private")
    assert cancelled == [("lead", "group"), ("lead", "private")]


@pytest.mark.asyncio
async def test_hitl_resume_uses_the_primary_checkpoint_and_keeps_room_identity(primary_env):
    manager = object.__new__(AgentManager)
    manager._repos, manager._teams = primary_env.repos, primary_env.teams
    seen = []

    @asynccontextmanager
    async def noop(*_args):
        yield

    class Harness:
        async def resume_hitl(self, aid, tid, decisions):
            seen.append((aid, tid, decisions, current_primary_room()))
            yield {"type": "token", "content": "已按批准继续"}

    manager._harness_manager = Harness()
    manager._thread_execution_lock = noop
    manager._track_invocation = noop
    manager._apply_pending_bootstrap_graph_refresh = lambda _: None
    manager._stream_model_label = lambda *_: ""
    frames = [frame async for frame in manager.resume_hitl("room", "group", [{"type": "approve"}])]
    assert seen[0][0:3] == ("lead", "group", [{"type": "approve"}])
    assert seen[0][3].user_id == primary_env.one
    assert frames[0]["speaker_agent_id"] == "lead" and frames[0]["agent_id"] == "room"
    assert current_primary_room() is None


@pytest.mark.asyncio
async def test_primary_status_counts_own_group_waiting_without_other_users_work(primary_env):
    from octop.infra.agents.work_status import attach_expert_work_status

    async def acp(_aid, _allowed):
        return {"working_thread_ids": [], "waiting_thread_ids": []}

    server = NS(
        services=primary_env.repos,
        app_runtime=NS(
            agent_registry=NS(
                active_thread_ids=lambda _aid: {"group", "other-private"}, acp_activity_snapshot=acp
            ),
            gateway=NS(
                ws_hub=NS(is_turn_active=lambda tid: tid in {"group", "other-private"}),
                processor=NS(
                    hitl_coordinator=NS(
                        store=NS(
                            pending_thread_ids=lambda *, agent_id, user_id: (
                                {"group"}
                                if agent_id == "room" and user_id == primary_env.one
                                else set()
                            )
                        )
                    )
                ),
            ),
        ),
    )
    rows = await attach_expert_work_status(
        server,
        primary_env.one,
        [
            {"agent_id": "lead", "kind": "expert", "state": "running"},
            {"agent_id": "room", "kind": "team", "state": "running", "primary_agent_id": "lead"},
        ],
    )
    assert rows[0]["work_status"] == "waiting"
    assert rows[0]["working_count"] == 0 and rows[0]["waiting_count"] == 1


@pytest.mark.asyncio
async def test_history_reads_versioned_archive_without_copying_into_projection(
    primary_env, tmp_path
):
    from langchain_core.messages import message_to_dict

    from octop.infra.history.reader import read_page
    from octop.infra.history.service import HistoryArchive
    from octop.infra.history.store import HistoryStore

    env = primary_env
    store = HistoryStore(tmp_path / "archive.sqlite", identity="test")
    archive = HistoryArchive(
        store, env.repos.thread_message_repo, env.repos.trajectory_event_repo, enabled=True
    )
    before = env.repos.thread_message_repo.head("group")
    turn = archive.begin("room", "group")
    archive.save_messages(
        turn,
        [
            message_to_dict(
                AIMessage(
                    content="仅在新存储的群内容",
                    id="v2",
                    additional_kwargs={"speaker_agent_id": "member"},
                )
            )
        ],
    )

    async def reader(agent_id, thread_id, *, limit, cursor=None):
        return await read_page(
            archive, NS(get_agent=lambda _: None), agent_id, thread_id, limit=limit, cursor=cursor
        )

    history = ConversationHistory(env.repos, env.teams, page_reader=reader)
    page = await history.aread(env.one, "group", limit=1)
    assert page["messages"][0]["content"] == "仅在新存储的群内容"
    assert page["messages"][0]["speaker_name"] == "数据分析师"
    assert page["has_more"] and page["next_cursor"]
    older = await history.aread(env.one, "group", limit=10, cursor=page["next_cursor"])
    assert any("小通的结论" in item["content"] for item in older["messages"])
    assert env.repos.thread_message_repo.head("group") == before
    with pytest.raises(PermissionError):
        await history.aread(env.two, "group")
    store.close()


@pytest.mark.asyncio
async def test_pending_legacy_checkpoint_is_read_only_and_cursor_scoped(primary_env):
    from unittest.mock import AsyncMock

    from octop.infra.history.reader import read_page

    env = primary_env
    env.repos.thread_message_repo.mark_projection("private", "pending")
    graph = NS(
        aget_state=AsyncMock(
            return_value=NS(
                values={"messages": [HumanMessage(content="旧问题"), AIMessage(content="旧答案")]},
                config={"configurable": {"checkpoint_id": "pinned"}},
            )
        )
    )
    registry = NS(get_agent=lambda aid: NS(graph=graph))
    first = await read_page(
        None, registry, "lead", "private", limit=1, messages=env.repos.thread_message_repo
    )
    assert first["messages"][0]["data"]["content"] == "旧答案"
    older = await read_page(
        None,
        registry,
        "lead",
        "private",
        limit=1,
        cursor=first["next_cursor"],
        messages=env.repos.thread_message_repo,
    )
    assert older["messages"][0]["data"]["content"] == "旧问题"
    with pytest.raises(ValueError):
        await read_page(
            None,
            registry,
            "room",
            "group",
            limit=1,
            cursor=first["next_cursor"],
            messages=env.repos.thread_message_repo,
        )
    assert env.repos.thread_message_repo.projection_status("private") == "pending"
