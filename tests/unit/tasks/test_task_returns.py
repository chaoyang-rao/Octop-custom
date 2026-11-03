"""Return delivery persists actual history without waking models or interrupting a turn."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, message_to_dict
from octop_gateway.manager import ChannelManager
from octop_gateway.media import FileSystemMediaBackend

from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import RepoBundle
from octop.infra.gateway.steer import SteerCoordinator
from octop.infra.gateway.threads import ThreadRegistry
from octop.infra.gateway.ws.ws_channel import WS_CHANNEL_ID, WebSocketChannel
from octop.infra.gateway.ws.ws_hub import WebSocketHub
from octop.infra.history.projection import message_inputs
from octop.infra.history.reader import read_page
from octop.infra.history.service import HistoryArchive
from octop.infra.history.store import HistoryStore
from octop.infra.tasks.returns import TaskReturnService


class Harness:
    def __init__(self, thread_id: str) -> None:
        self.messages = {
            thread_id: [
                HumanMessage("old question", id="old-human"),
                AIMessage("old reply", id="old-ai"),
            ]
        }
        self.snapshots = {}
        self.version = 0
        self.next = ()
        self.fail_after_append = False
        self.on_read = None
        self.calls = []
        self.graph = SimpleNamespace(aget_state=self.state)

    def _snapshot(self, thread_id):
        checkpoint = f"checkpoint-{self.version}"
        self.snapshots[(thread_id, checkpoint)] = deepcopy(self.messages.get(thread_id, []))
        return checkpoint

    async def state(self, config):
        cfg = config["configurable"]
        thread = cfg["thread_id"]
        checkpoint = cfg.get("checkpoint_id") or self._snapshot(thread)
        if self.on_read is not None and not cfg.get("checkpoint_id"):
            callback, self.on_read = self.on_read, None
            callback()
        return SimpleNamespace(
            values={"messages": deepcopy(self.snapshots[(thread, checkpoint)])},
            config={"configurable": {"thread_id": thread, "checkpoint_id": checkpoint}},
            next=self.next,
            tasks=(),
        )

    async def aappend_messages(self, thread_id, messages):
        self.calls.append((thread_id, messages))
        current = self.messages.setdefault(thread_id, [])
        for message in messages:
            index = next((i for i, item in enumerate(current) if item.id == message.id), None)
            if index is None:
                current.append(message)
            else:
                current[index] = message
        self.version += 1
        if self.fail_after_append:
            self.fail_after_append = False
            raise OSError("simulated process failure after the checkpoint committed")
        return messages


class Agents:
    def __init__(self, harness, archive):
        self.harness = harness
        self.history_archive = archive
        self.reserved = set()
        self.busy = False
        self.principal = {}
        self.claims = []
        self.lookups = []

    def principal_agent_id(self, agent_id):
        return self.principal.get(agent_id, agent_id)

    def try_begin_history_backfill(self, agent_id):
        self.claims.append(agent_id)
        if self.busy or agent_id in self.reserved:
            return False
        self.reserved.add(agent_id)
        return True

    def end_history_backfill(self, agent_id):
        self.reserved.remove(agent_id)

    def get_agent(self, agent_id):
        self.lookups.append(agent_id)
        return self.harness


@pytest.fixture
async def env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OCTOP_HOME", str(tmp_path))
    db = SqlitePool(tmp_path / "control.sqlite")
    run_migrations(db)
    repos = RepoBundle.from_pool(db)
    user_id = repos.user_repo.create(
        username="owner", password_hash="test", role="admin", locale="zh"
    )
    other = repos.user_repo.create(username="foreign", password_hash="test", role="admin")
    for aid, owner in [
        ("host", user_id),
        ("worker", user_id),
        ("room", user_id),
        ("foreign", other),
    ]:
        repos.agent_repo.create(agent_id=aid, user_id=owner, name=f"expert-{aid}")
    registry = ThreadRegistry(session_repo=repos.session_repo, thread_repo=repos.thread_repo)
    origin = await registry.get_or_create(
        agent_id="host", user_id=user_id, channel_type="dashboard", channel_subject_id="origin"
    )
    execution = await registry.get_or_create(
        agent_id="worker", user_id=user_id, channel_type="dashboard", channel_subject_id="execution"
    )
    harness = Harness(origin)
    # Registry-created empty threads are marked ready. This fixture now seeds
    # a legacy checkpoint, so its still-unbackfilled projection must be pending.
    repos.thread_message_repo.mark_projection(origin, "pending")
    store = HistoryStore(tmp_path / "history.sqlite", identity="test-control-plane")
    archive = HistoryArchive(store, repos.thread_message_repo, repos.trajectory_event_repo)
    agents = Agents(harness, archive)
    agents.get_row = repos.agent_repo.get
    active = set()
    paused = set()
    channels = ChannelManager(
        channels={
            WS_CHANNEL_ID: WebSocketChannel(
                SimpleNamespace(), hub=WebSocketHub(), steer=SteerCoordinator()
            )
        },
        media_backend=FileSystemMediaBackend(str(tmp_path)),
    )
    gateway = SimpleNamespace(
        channel_manager=channels,
        dashboard_channel_id=WS_CHANNEL_ID,
        thread_registry=registry,
        ws_hub=SimpleNamespace(is_turn_active=lambda thread: thread in active),
        steer=SimpleNamespace(is_hitl_paused=lambda thread: thread in paused),
        notify_dashboard_push=AsyncMock(),
    )
    service = TaskReturnService(repos, gateway, agents)
    repos.task_repo.enqueue(
        [
            {
                "task_id": "task",
                "agent_id": "worker",
                "user_id": user_id,
                "thread_id": execution,
                "title": "分析报告",
                "prompt": "produce a result",
                "dispatch": {"origin_agent_id": "host", "origin_thread_id": origin},
            }
        ]
    )
    assert repos.task_repo.claim("task")
    repos.task_repo.transition(
        "task",
        expected={"running"},
        state="completed",
        action="completed",
        fields={"result": "verified result"},
    )
    yield SimpleNamespace(
        db=db,
        repos=repos,
        uid=user_id,
        other=other,
        registry=registry,
        origin=origin,
        execution=execution,
        harness=harness,
        archive=archive,
        store=store,
        agents=agents,
        gateway=gateway,
        service=service,
        active=active,
        paused=paused,
        channels=channels,
    )
    store.close()
    db.close()


async def deliver(env):
    return await env.service.deliver(env.repos.task_repo.get("task"))


async def history(env):
    return (
        await read_page(
            env.archive,
            env.agents,
            "host",
            env.origin,
            limit=100,
            messages=env.repos.thread_message_repo,
        )
    )["messages"]


@pytest.mark.parametrize("v2", [False, True])
@pytest.mark.parametrize("ready", [False, True])
async def test_return_preserves_legacy_prefix_and_is_replay_safe(env, v2, ready):
    env.archive.enabled = v2
    if ready:
        env.repos.thread_message_repo.replace_all(
            env.origin, message_inputs(env.harness.messages[env.origin])
        )
    assert await deliver(env)
    assert await deliver(env)
    records = await history(env)
    assert [wire["data"]["id"] for wire in records[:2]] == ["old-human", "old-ai"]
    assert len(records) == 3
    returned = records[-1]["data"]
    assert returned["additional_kwargs"]["speaker_agent_id"] == "worker"
    assert returned["additional_kwargs"]["octop_task_return"]["data_only"] is True
    assert "verified result" in returned["content"]
    assert f"/chat/worker/{env.execution}" in returned["content"]
    assert "/task-queue" in returned["content"]
    assert len(env.harness.calls) == 1
    assert env.gateway.notify_dashboard_push.await_count == 1
    assert not env.repos.task_dispatch_repo.pending_returns()
    assert not env.agents.reserved


async def test_existing_v2_turns_remain_unchanged(env):
    env.archive.enabled = True
    state = await env.harness.state({"configurable": {"thread_id": env.origin}})
    old_turn = env.archive.begin("host", env.origin, anchor={"checkpoint_config": state.config})
    previous = [
        HumanMessage("previous v2", id="v2-human"),
        AIMessage("previous answer", id="v2-ai"),
    ]
    env.archive.save_messages(old_turn, [message_to_dict(message) for message in previous])
    env.archive.finish(old_turn["id"], "completed")
    env.harness.messages[env.origin] = previous
    env.harness.version += 1
    old_documents = env.store.documents(env.origin, "message", turn_id=old_turn["id"])
    assert await deliver(env)
    assert env.store.documents(env.origin, "message", turn_id=old_turn["id"]) == old_documents
    assert [wire["data"]["id"] for wire in await history(env)][:4] == [
        "old-human",
        "old-ai",
        "v2-human",
        "v2-ai",
    ]
    assert len(await history(env)) == 5


async def test_checkpoint_commit_then_crash_retries_without_duplicate_or_history_loss(env):
    env.archive.enabled = True
    env.harness.fail_after_append = True
    assert not await deliver(env)
    assert not env.agents.reserved
    assert env.repos.task_dispatch_repo.pending_returns()
    assert await deliver(env)
    assert len(env.harness.calls) == 1
    assert len(await history(env)) == 3
    assert not env.repos.task_dispatch_repo.pending_returns()


async def test_archive_deduplicates_after_a_later_turn_replaces_the_checkpoint(env, monkeypatch):
    env.archive.enabled = True
    acknowledge = env.repos.task_dispatch_repo.mark_returned
    monkeypatch.setattr(env.repos.task_dispatch_repo, "mark_returned", lambda *_a, **_kw: False)
    assert not await deliver(env)
    later = [
        HumanMessage("later question", id="later-human"),
        AIMessage("later reply", id="later-ai"),
    ]
    turn = env.archive.begin("host", env.origin)
    env.archive.save_messages(turn, [message_to_dict(message) for message in later])
    env.archive.finish(turn["id"], "completed")
    env.harness.messages[env.origin] = later
    env.harness.version += 1
    monkeypatch.setattr(env.repos.task_dispatch_repo, "mark_returned", acknowledge)
    assert await deliver(env)
    assert len(env.harness.calls) == 1
    assert [message.id for message in env.harness.messages[env.origin]] == [
        "later-human",
        "later-ai",
    ]
    wires = await history(env)
    assert len(wires) == 5
    assert sum(wire["data"]["id"].startswith("task-return:") for wire in wires) == 1


async def test_archive_commit_then_projection_failure_finishes_the_same_return_on_retry(
    env, monkeypatch
):
    env.archive.enabled = True
    projection = env.repos.thread_message_repo
    projection.replace_all(env.origin, message_inputs(env.harness.messages[env.origin]))
    append = projection.append_if_ready

    def unavailable(*_args):
        raise OSError("simulated projection outage")

    monkeypatch.setattr(projection, "append_if_ready", unavailable)
    assert not await deliver(env)
    assert env.store.documents(env.origin, "message")[0]["status"] == "interrupted"
    monkeypatch.setattr(projection, "append_if_ready", append)
    assert await deliver(env)
    assert len(env.harness.calls) == 1
    assert env.store.documents(env.origin, "message")[0]["status"] == "completed"
    assert len(await history(env)) == 3


@pytest.mark.parametrize("busy", ["websocket", "approval", "principal", "checkpoint"])
async def test_busy_source_defers_without_history_or_stream_frames(env, busy):
    if busy == "websocket":
        env.active.add(env.origin)
    elif busy == "approval":
        env.paused.add(env.origin)
    elif busy == "principal":
        env.agents.busy = True
    else:
        env.harness.next = ("tools",)
    assert not await deliver(env)
    assert not env.harness.calls
    assert env.gateway.notify_dashboard_push.await_count == 0
    assert env.repos.task_dispatch_repo.pending_returns()
    assert not env.agents.reserved
    env.active.clear()
    env.paused.clear()
    env.agents.busy = False
    env.harness.next = ()
    assert await deliver(env)


@pytest.mark.parametrize(
    "revocation", ["permission", "disabled", "deleted", "foreign", "principal", "worker_principal"]
)
async def test_revoked_or_deleted_source_is_dropped_without_disclosure(env, revocation):
    with env.db.connect() as conn:
        if revocation == "permission":
            conn.execute("UPDATE users SET role='user',permissions='[]' WHERE id=?", (env.uid,))
        elif revocation == "disabled":
            conn.execute("UPDATE users SET disabled=1 WHERE id=?", (env.uid,))
        elif revocation == "deleted":
            conn.execute("DELETE FROM threads WHERE thread_id=?", (env.origin,))
        elif revocation == "foreign":
            conn.execute("UPDATE threads SET user_id=? WHERE thread_id=?", (env.other, env.origin))
        elif revocation == "worker_principal":
            env.agents.principal["worker"] = "foreign"
        else:
            env.agents.principal["host"] = "foreign"
    assert await deliver(env)
    assert not env.harness.calls
    assert env.gateway.notify_dashboard_push.await_count == 0
    assert env.repos.task_dispatch_repo.get("task")["returned_event_id"] > 0


async def test_permission_is_rechecked_after_slow_checkpoint_read(env):
    def revoke():
        with env.db.connect() as conn:
            conn.execute("UPDATE users SET disabled=1 WHERE id=?", (env.uid,))

    env.harness.on_read = revoke
    assert await deliver(env)
    assert not env.harness.calls and not env.agents.reserved
    assert env.gateway.notify_dashboard_push.await_count == 0


async def test_team_origin_reserves_the_real_primary_and_preserves_speaker(env):
    room = await env.registry.get_or_create(
        agent_id="room", user_id=env.uid, channel_type="dashboard", channel_subject_id="team"
    )
    env.harness.messages[room] = []
    env.agents.principal["room"] = "host"
    with env.db.connect() as conn:
        conn.execute(
            "UPDATE task_dispatch_context SET origin_agent_id='room',origin_thread_id=? WHERE task_id='task'",
            (room,),
        )
    assert await deliver(env)
    assert env.agents.claims == ["host"]
    assert env.agents.lookups == ["host"]
    assert env.harness.messages[room][0].additional_kwargs["speaker_agent_id"] == "worker"
    assert env.gateway.notify_dashboard_push.await_args.args[1] == "room"


@pytest.mark.parametrize("origin_is_team", [False, True])
@pytest.mark.parametrize("has_primary", [False, True])
async def test_team_executor_returns_as_its_real_primary_to_a_dm_or_room(
    env, origin_is_team, has_primary
):
    with env.db.connect() as conn:
        conn.execute("UPDATE agents SET name='小通' WHERE agent_id='host'")
        conn.execute("UPDATE agents SET kind='team' WHERE agent_id='room'")
    if has_primary:
        env.agents.principal["room"] = "host"
    execution = await env.registry.get_or_create(
        agent_id="room",
        user_id=env.uid,
        channel_type="dashboard",
        channel_subject_id="team-execution",
    )
    origin_agent, origin_thread = "host", env.origin
    if origin_is_team:
        origin_agent = "room"
        origin_thread = await env.registry.get_or_create(
            agent_id="room",
            user_id=env.uid,
            channel_type="dashboard",
            channel_subject_id="team-origin",
        )
        env.harness.messages[origin_thread] = []
    repo = env.repos.task_repo
    repo.enqueue(
        [
            {
                "task_id": "team-task",
                "agent_id": "room",
                "user_id": env.uid,
                "thread_id": execution,
                "title": "团队修复",
                "prompt": "coordinate the team",
                "dispatch": {"origin_agent_id": origin_agent, "origin_thread_id": origin_thread},
            }
        ]
    )
    assert repo.claim("team-task")
    repo.transition(
        "team-task",
        expected={"running"},
        state="completed",
        action="completed",
        fields={"result": "member A full reply\nmember B full reply"},
    )
    assert await env.service.deliver(repo.get("team-task"))
    if not has_primary:
        assert not env.harness.calls
        assert env.gateway.notify_dashboard_push.await_count == 0
        return
    message = env.harness.messages[origin_thread][-1]
    assert message.additional_kwargs["speaker_agent_id"] == "host"
    assert message.additional_kwargs["octop_task_return"]["executor_agent_id"] == "room"
    assert message.content.startswith("小通")
    assert "member A full reply" not in message.content
    assert f"/chat/room/{execution}" in message.content
    assert env.gateway.notify_dashboard_push.await_args.args[1] == origin_agent


async def test_second_approval_and_completion_each_have_one_return(env):
    repo = env.repos.task_repo
    repo.transition("task", expected={"completed"}, state="waiting", action="waiting")
    assert await deliver(env)
    repo.transition("task", expected={"waiting"}, state="running", action="resumed")
    repo.transition("task", expected={"running"}, state="waiting", action="waiting")
    assert await deliver(env)
    repo.transition("task", expected={"waiting"}, state="completed", action="completed")
    assert await deliver(env)
    assert await deliver(env)
    ids = [message.id for message in env.harness.messages[env.origin][2:]]
    assert len(ids) == len(set(ids)) == 3
    assert env.gateway.notify_dashboard_push.await_count == 3


async def test_archive_restore_does_not_repeat_a_return(env):
    repo = env.repos.task_repo
    repo.transition(
        "task", expected={"completed"}, state="completed", action="archive", fields={"archived": 1}
    )
    assert await deliver(env)
    assert not env.harness.calls
    repo.transition(
        "task", expected={"completed"}, state="completed", action="restore", fields={"archived": 0}
    )
    assert await deliver(env)
    for action, archived in [("archive", 1), ("restore", 0)]:
        repo.transition(
            "task",
            expected={"completed"},
            state="completed",
            action=action,
            fields={"archived": archived},
        )
        assert await deliver(env)
    assert len(env.harness.calls) == 1


async def test_origin_conversation_remains_archived_after_delivery(env):
    with env.db.connect() as conn:
        conn.execute("UPDATE threads SET archived=1 WHERE thread_id=?", (env.origin,))
    assert await deliver(env)
    assert env.repos.thread_repo.get(env.origin).archived is True
    assert len(await history(env)) == 3


async def test_queued_cancelled_task_returns_without_an_execution_conversation(env):
    repo = env.repos.task_repo
    repo.enqueue(
        [
            {
                "task_id": "never-started",
                "agent_id": "worker",
                "user_id": env.uid,
                "title": "cancelled request",
                "prompt": "never execute",
                "dispatch": {"origin_agent_id": "host", "origin_thread_id": env.origin},
            }
        ]
    )
    repo.transition("never-started", expected={"queued"}, state="cancelled", action="cancel")
    assert await env.service.deliver(repo.get("never-started"))
    message = env.harness.messages[env.origin][-1]
    assert message.id.startswith("task-return:never-started:")
    assert "/task-queue" in message.content and "/chat/" not in message.content
    assert env.repos.task_dispatch_repo.get("never-started")["returned_state"] == "cancelled"


async def test_source_transport_admission_timeout_does_not_deliver_late(env):
    acquired, release = asyncio.Event(), asyncio.Event()

    async def incoming_before_active_flag():
        acquired.set()
        await release.wait()

    incoming = asyncio.create_task(
        env.channels.run_in_session(
            WS_CHANNEL_ID, f"thread:{env.origin}", incoming_before_active_flag
        )
    )
    await acquired.wait()
    try:
        # Reproduce the small interval before WebSocketChannel marks a turn active.
        assert not await deliver(env)
        assert not env.harness.calls and not env.agents.claims
    finally:
        release.set()
        await incoming
    await asyncio.sleep(0)
    assert not env.harness.calls
    assert env.repos.task_dispatch_repo.pending_returns()


async def test_started_history_write_is_not_cancelled_and_new_input_waits(env):
    env.archive.enabled = True
    write_started, write_release, incoming_started = (
        asyncio.Event(),
        asyncio.Event(),
        asyncio.Event(),
    )
    original_append = env.harness.aappend_messages

    async def slow_append(thread_id, messages):
        write_started.set()
        await write_release.wait()
        return await original_append(thread_id, messages)

    env.harness.aappend_messages = slow_append
    returning = asyncio.create_task(deliver(env))
    await write_started.wait()

    async def new_user_input():
        incoming_started.set()
        assert env.store.turn(env.origin, unfinished=True) is None
        turn = env.archive.begin("host", env.origin)
        env.archive.finish(turn["id"], "completed")

    incoming = asyncio.create_task(
        env.channels.run_in_session(WS_CHANNEL_ID, f"thread:{env.origin}", new_user_input)
    )
    await asyncio.sleep(0.15)
    assert not returning.done() and not incoming_started.is_set()
    write_release.set()
    assert await returning
    await incoming
    assert incoming_started.is_set()
    assert len(env.harness.calls) == 1 and len(await history(env)) == 3


async def test_an_unbound_but_owned_origin_defers_without_consuming_its_return(env, monkeypatch):
    original = env.registry.sessions_for_thread
    monkeypatch.setattr(env.registry, "sessions_for_thread", lambda _thread: [])
    assert not await deliver(env)
    assert env.repos.task_dispatch_repo.get("task")["returned_event_id"] == 0
    assert not env.harness.calls
    monkeypatch.setattr(env.registry, "sessions_for_thread", original)
    assert await deliver(env)


@pytest.mark.parametrize("state", ["completed", "failed", "waiting"])
async def test_quiet_success_refreshes_without_toast_but_attention_still_notifies(env, state):
    with env.db.connect() as conn:
        conn.execute(
            "UPDATE agent_tasks SET options_json=? WHERE task_id='task'", ('{"quiet":true}',)
        )
    if state != "completed":
        env.repos.task_repo.transition("task", expected={"completed"}, state=state, action=state)
    assert await deliver(env)
    assert env.gateway.notify_dashboard_push.await_args.kwargs == {
        "notify": state != "completed",
        "toast": state != "completed",
    }


async def test_output_limit_keeps_owned_links_and_only_a_valid_pr(env):
    repo = env.repos.task_repo
    repo.transition(
        "task",
        expected={"completed"},
        state="completed",
        action="result",
        fields={"result": "数据" * 10000},
    )
    env.repos.task_dispatch_repo.update_coding(
        "task", {"pr_url": "https://github.com/owner/repo/pull/12"}
    )
    assert await deliver(env)
    text = env.harness.messages[env.origin][-1].content
    assert len(text) <= 6000
    assert "https://github.com/owner/repo/pull/12" in text
    assert f"/chat/worker/{env.execution}" in text and "/task-queue" in text
    for value in [
        "https://foreign.example/owner/repo/pull/12",
        "https://github.com@foreign.example/owner/repo/pull/12",
        "https://[broken",
    ]:
        context = env.repos.task_dispatch_repo.get("task")
        context["coding_run"] = {"pr_url": value}
        formatted, _, _speaker = env.service._text(repo.get("task"), context, "zh")
        assert value not in formatted
