"""Durable task acceptance through the real gateway lock, WS channel and isolated DB."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from octop_gateway.manager import ChannelManager
from octop_gateway.media import FileSystemMediaBackend

from octop.config import OctopConfig
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import RepoBundle
from octop.infra.errors import OctopError
from octop.infra.gateway.steer import SteerCoordinator
from octop.infra.gateway.threads import ThreadRegistry
from octop.infra.gateway.ws.ws_channel import WS_CHANNEL_ID, WebSocketChannel
from octop.infra.gateway.ws.ws_hub import WebSocketHub
from octop.infra.tasks.manager import TaskManager
from octop.infra.tasks.models import TaskCreate, WorkflowDefinition


class Processor:
    def __init__(self):
        self.received = []
        self.gate = None
        self.pause = False
        self.fail = False
        self.hitl_coordinator = SimpleNamespace(expire_pending_for_thread=Mock())
        self.teams = SimpleNamespace(cancel_member_hitl=Mock())

    async def __call__(self, message):
        if False:
            yield None

    async def iter_turn_chunks(self, message):
        self.received.append(message)
        if self.gate:
            await self.gate.wait()
        if self.fail:
            yield {"type": "error", "message": "simulated failure"}
        elif self.pause:
            self.pause = False
            yield {"type": "token", "content": "before approval "}
            yield {"type": "hitl_required", "request": {}}
        else:
            yield {"type": "token", "content": "verified output"}
        yield {"type": "done"}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("OCTOP_HOME", str(tmp_path))
    db = SqlitePool(tmp_path / "tasks.sqlite")
    run_migrations(db)
    repos = RepoBundle.from_pool(db)
    uid = repos.user_repo.create(username="owner", password_hash="test", role="admin")
    other = repos.user_repo.create(username="other", password_hash="test", role="admin")
    for aid, owner in [("a", uid), ("b", uid), ("foreign", other)]:
        repos.agent_repo.create(agent_id=aid, user_id=owner, name=aid)
    processor = Processor()
    hub = WebSocketHub()
    steer = SteerCoordinator()
    channel = WebSocketChannel(processor, hub=hub, steer=steer)
    channels = ChannelManager(
        channels={WS_CHANNEL_ID: channel}, media_backend=FileSystemMediaBackend(str(tmp_path))
    )
    gateway = SimpleNamespace(
        dashboard_channel_id=WS_CHANNEL_ID,
        channel_manager=channels,
        ws_hub=hub,
        processor=processor,
        steer=steer,
        notify_dashboard_push=AsyncMock(),
        thread_registry=ThreadRegistry(
            session_repo=repos.session_repo, thread_repo=repos.thread_repo
        ),
    )
    agents = SimpleNamespace(
        start=AsyncMock(),
        cancel_stream=Mock(),
        is_agent_active=lambda _: False,
        validate_mcp_servers=lambda uid, values: values,
        validate_knowledge_base_ids=lambda uid, values: values,
        list_skill_summaries=AsyncMock(return_value=[]),
        providers=SimpleNamespace(is_model_ref_usable=lambda model: True),
    )
    agents.get_row = repos.agent_repo.get
    agents.get_agent = lambda _: SimpleNamespace(
        graph=SimpleNamespace(
            aget_state=AsyncMock(
                return_value=SimpleNamespace(values={"messages": []}, next=(), tasks=())
            )
        )
    )
    manager = TaskManager(
        repos=repos,
        gateway=gateway,
        agent_manager=agents,
        config=OctopConfig(default_timezone="Asia/Shanghai"),
    )
    channel.set_task_admission(manager.admit_turn)
    yield SimpleNamespace(
        db=db,
        repos=repos,
        uid=uid,
        other=other,
        processor=processor,
        hub=hub,
        steer=steer,
        channels=channels,
        gateway=gateway,
        agents=agents,
        manager=manager,
    )
    db.close()


async def settled(manager):
    running = list(manager._running.values())
    if running:
        # Generous timeout: the fake ACP subprocess handshake is slow when the
        # full suite runs on a loaded machine.
        await asyncio.wait_for(asyncio.gather(*running, return_exceptions=True), timeout=15)


async def enqueue(env, title="task", agent="a", thread=None):
    return await env.manager.enqueue(
        env.uid, TaskCreate(agent_id=agent, title=title, prompt=title, thread_id=thread)
    )


@pytest.mark.asyncio
async def test_fifo_pause_and_real_ws_pipeline(setup):
    e = setup
    await e.channels.start()
    try:
        default_thread = await e.gateway.thread_registry.get_or_create(
            agent_id="a", user_id=e.uid, channel_type="dashboard", channel_subject_id=str(e.uid)
        )
        first = await enqueue(e, "first")
        second = await enqueue(e, "second")
        e.processor.gate = asyncio.Event()
        await e.manager.process_once()
        for _ in range(100):
            if e.processor.received:
                break
            await asyncio.sleep(0.005)
        assert len(e.processor.received) == 1
        await e.manager.process_once()
        assert len(e.processor.received) == 1
        await e.manager.pause_queue(e.uid, "a", True)
        e.processor.gate.set()
        await settled(e.manager)
        assert e.repos.task_repo.get(first.id).state == "completed"
        await e.manager.process_once()
        assert e.repos.task_repo.get(second.id).state == "queued"
        await e.manager.pause_queue(e.uid, "a", False)
        await e.manager.process_once()
        await settled(e.manager)
        assert [message.text for message in e.processor.received] == ["first", "second"]
        saved = e.repos.task_repo.get(second.id)
        assert saved.result == "verified output" and saved.thread_id
        assert e.gateway.thread_registry.get_thread(saved.thread_id).user_id == e.uid
        assert e.processor.received[-1].metadata["ws_connection_id"].startswith("task:")
        assert e.hub.connection_count == 0
        default_key = e.gateway.thread_registry.dashboard_key(agent_id="a", user_id=e.uid)
        assert e.gateway.thread_registry.get_bound_thread_id(default_key) == default_thread
        assert e.gateway.notify_dashboard_push.await_count == 2
    finally:
        await e.manager.stop()
        await e.channels.stop()


@pytest.mark.asyncio
async def test_paused_head_and_lifecycle_actions(setup):
    e = setup
    first = await enqueue(e)
    second = await enqueue(e, "second")
    await e.manager.action(e.uid, first.id, "pause")
    assert e.repos.task_repo.queue_heads()[0].state == "paused"
    assert not e.repos.task_repo.claim(second.id)
    await e.manager.action(e.uid, first.id, "resume")
    await e.manager.action(e.uid, first.id, "cancel")
    assert e.repos.task_repo.get(first.id).state == "cancelled"
    await e.manager.action(e.uid, first.id, "archive")
    assert [task.id for task in e.repos.task_repo.list(e.uid, archived=True)] == [first.id]
    await e.manager.action(e.uid, first.id, "restore")
    await e.manager.action(e.uid, first.id, "retry")
    assert e.repos.task_repo.get(first.id).state == "queued"
    assert [event["action"] for event in e.repos.task_repo.events(first.id)] == [
        "created",
        "pause",
        "resume",
        "cancel",
        "archive",
        "restore",
        "retry",
    ]
    with pytest.raises(OctopError):
        await e.manager.action(e.uid, first.id, "archive")


def test_claim_is_atomic_and_recovery_does_not_replay(setup):
    e = setup
    e.repos.task_repo.enqueue(
        [
            {
                "task_id": "first",
                "user_id": e.uid,
                "agent_id": "a",
                "title": "one",
                "prompt": "one",
            },
            {
                "task_id": "second",
                "user_id": e.uid,
                "agent_id": "a",
                "title": "two",
                "prompt": "two",
            },
        ]
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        claimed = list(executor.map(e.repos.task_repo.claim, ["first", "first"]))
    assert claimed.count(True) == 1
    assert not e.repos.task_repo.claim("second")
    assert e.repos.task_repo.recover() == ["first"]
    assert e.repos.task_repo.get("first").state == "interrupted"
    assert e.repos.task_repo.get("second").state == "queued"
    assert e.repos.task_repo.recover() == []
    assert e.repos.task_repo.get("first").attempt == 1


@pytest.mark.asyncio
async def test_cross_owner_agent_task_thread_and_workflow_rejected(setup):
    e = setup
    first = await enqueue(e)
    for operation in [
        e.manager.enqueue(e.uid, TaskCreate(agent_id="foreign", title="x", prompt="x")),
        e.manager.detail(e.other, first.id),
        e.manager.action(e.other, first.id, "cancel"),
        e.manager.action(e.uid, first.id, "reassign", agent_id="foreign"),
    ]:
        with pytest.raises(OctopError) as error:
            await operation
        assert error.value.status == 404
    thread = e.gateway.thread_registry.create_thread(
        agent_id="foreign", user_id=e.other, channel_type="dashboard", session_key="foreign"
    )
    with pytest.raises(OctopError):
        await e.manager.enqueue(
            e.uid, TaskCreate(agent_id="a", title="x", prompt="x", thread_id=thread)
        )
    workflow = await e.manager.create_workflow(e.uid, name="owned", definition=definition())
    with pytest.raises(OctopError):
        await e.manager.run_workflow(e.other, workflow.workflow_id)
    assert e.repos.task_repo.get(first.id).agent_id == "a"


def definition():
    return WorkflowDefinition.model_validate(
        {
            "steps": [
                {
                    "key": "second",
                    "title": "second",
                    "agent_id": "b",
                    "prompt": "next",
                    "depends_on": ["first"],
                },
                {
                    "key": "first",
                    "title": "first",
                    "agent_id": "a",
                    "prompt": "start",
                    "depends_on": [],
                },
            ]
        }
    )


@pytest.mark.asyncio
async def test_workflow_atomic_dedup_and_dependency_handoff(setup):
    e = setup
    await e.channels.start()
    try:
        flow = await e.manager.create_workflow(e.uid, name="flow", definition=definition())
        run = await e.manager.run_workflow(
            e.uid, flow.workflow_id, payload={"input": "safe data"}, idempotency_key="same-request"
        )
        same = await e.manager.run_workflow(
            e.uid, flow.workflow_id, payload={}, idempotency_key="same-request"
        )
        assert same == run
        assert len(e.repos.task_repo.run_tasks(run, e.uid)) == 2
        await e.manager.process_once()
        await settled(e.manager)
        assert len(e.processor.received) == 1
        await e.manager.process_once()
        await settled(e.manager)
        assert len(e.processor.received) == 2
        assert "verified output" in e.processor.received[-1].text
        assert "dependency_results" in e.processor.received[-1].text
        assert (await e.manager.runs(e.uid))[0]["state"] == "completed"
        assert "safe data" in e.processor.received[0].text
    finally:
        await e.manager.stop()
        await e.channels.stop()


@pytest.mark.asyncio
async def test_failure_blocks_dependency_without_executing_it(setup):
    e = setup
    await e.channels.start()
    try:
        flow = await e.manager.create_workflow(e.uid, name="flow", definition=definition())
        run = await e.manager.run_workflow(e.uid, flow.workflow_id)
        e.processor.fail = True
        await e.manager.process_once()
        await settled(e.manager)
        await e.manager.process_once()
        assert len(e.processor.received) == 1
        tasks = e.repos.task_repo.run_tasks(run, e.uid)
        assert [task.state for task in tasks] == ["failed", "failed"]
        assert tasks[1].error_code == "dependency_failed"
    finally:
        await e.manager.stop()
        await e.channels.stop()


@pytest.mark.asyncio
async def test_approval_wait_blocks_then_hands_off_resumed_output(setup):
    e = setup
    await e.channels.start()
    try:
        flow = await e.manager.create_workflow(e.uid, name="flow", definition=definition())
        run = await e.manager.run_workflow(e.uid, flow.workflow_id)
        e.processor.pause = True
        await e.manager.process_once()
        await settled(e.manager)
        first = e.repos.task_repo.run_tasks(run, e.uid)[0]
        assert first.state == "waiting"
        await e.manager.process_once()
        assert len(e.processor.received) == 1
        await e.manager.complete_waiting_turn(
            agent_id="a",
            user_id=e.uid,
            thread_id=first.thread_id,
            failed=False,
            paused=True,
            output="next pause ",
        )
        assert e.repos.task_repo.get(first.id).state == "waiting"
        await e.manager.complete_waiting_turn(
            agent_id="a",
            user_id=e.uid,
            thread_id=first.thread_id,
            failed=False,
            paused=False,
            output="approved final",
        )
        await e.manager.process_once()
        await settled(e.manager)
        assert "approved final" in e.processor.received[-1].text
        assert e.repos.task_repo.get(first.id).result == "before approval next pause approved final"
    finally:
        await e.manager.stop()
        await e.channels.stop()


@pytest.mark.asyncio
async def test_webhook_scope_revocation_limits_and_payload_bounds(setup):
    e = setup
    flow = await e.manager.create_workflow(e.uid, name="flow", definition=definition())
    with pytest.raises(OctopError):
        await e.manager.trigger_webhook(flow.workflow_id, "bad", {})
    token = await e.manager.rotate_webhook(e.uid, flow.workflow_id, enabled=True)
    assert token and token not in e.repos.task_repo.workflow(flow.workflow_id).webhook_hash
    await e.manager.trigger_webhook(flow.workflow_id, token, {}, idempotency_key="once")
    await e.manager.trigger_webhook(flow.workflow_id, token, {}, idempotency_key="once")
    assert len(await e.manager.runs(e.uid)) == 1
    await e.manager.rotate_webhook(e.uid, flow.workflow_id, enabled=False)
    with pytest.raises(OctopError):
        await e.manager.trigger_webhook(flow.workflow_id, token, {})
    with pytest.raises(OctopError) as error:
        await e.manager.run_workflow(e.uid, flow.workflow_id, payload={"x": "x" * 33000})
    assert error.value.status == 413


@pytest.mark.asyncio
async def test_cancel_running_never_becomes_completed(setup):
    e = setup
    await e.channels.start()
    try:
        task = await enqueue(e)
        e.processor.gate = asyncio.Event()
        await e.manager.process_once()
        for _ in range(100):
            if e.processor.received:
                break
            await asyncio.sleep(0.005)
        await e.manager.action(e.uid, task.id, "cancel")
        await settled(e.manager)
        assert e.repos.task_repo.get(task.id).state == "cancelled"
        assert e.agents.cancel_stream.called
        assert e.hub.connection_count == 0
    finally:
        await e.manager.stop()
        await e.channels.stop()


@pytest.mark.parametrize(
    "steps",
    [
        [{"key": "a", "title": "a", "agent_id": "a", "prompt": "a", "depends_on": ["a"]}],
        [{"key": "a", "title": "a", "agent_id": "a", "prompt": "a", "depends_on": ["missing"]}],
        [
            {"key": "a", "title": "a", "agent_id": "a", "prompt": "a"},
            {"key": "a", "title": "a", "agent_id": "a", "prompt": "a"},
        ],
    ],
)
def test_invalid_graphs_rejected_before_creating_tasks(steps):
    with pytest.raises(ValueError):
        WorkflowDefinition.model_validate({"steps": steps})


@pytest.mark.asyncio
async def test_workflow_definition_edits_and_removal_preserve_existing_run(setup):
    e = setup
    flow = await e.manager.create_workflow(e.uid, name="original", definition=definition())
    token = await e.manager.rotate_webhook(e.uid, flow.workflow_id, enabled=True)
    run = await e.manager.run_workflow(e.uid, flow.workflow_id)
    changed = definition().model_dump()
    changed["steps"][0]["prompt"] = "changed after run creation"
    await e.manager.update_workflow(
        e.uid,
        flow.workflow_id,
        name="changed",
        definition=WorkflowDefinition.model_validate(changed),
        enabled=False,
    )
    rows = e.repos.task_repo.run_tasks(run, e.uid)
    assert all(row.prompt != "changed after run creation" for row in rows)
    assert e.repos.task_repo.run_definition(run)["steps"][0]["prompt"] == "next"
    await e.manager.delete_workflow(e.uid, flow.workflow_id)
    assert len(e.repos.task_repo.run_tasks(run, e.uid)) == 2
    assert (await e.manager.runs(e.uid))[0]["name"] == "original"
    assert (await e.manager.runs(e.uid))[0]["workflow_id"] is None
    with pytest.raises(OctopError):
        await e.manager.trigger_webhook(flow.workflow_id, token, {})


def test_skipped_task_watermark_repair_preserves_rows_and_project_binding(setup, tmp_path):
    e = setup
    e.repos.task_repo.enqueue(
        [
            {
                "task_id": "kept",
                "user_id": e.uid,
                "agent_id": "a",
                "title": "saved",
                "prompt": "keep this task",
            }
        ]
    )
    thread = e.gateway.thread_registry.create_thread(
        agent_id="a", user_id=e.uid, channel_type="dashboard", session_key="existing"
    )
    project = str(tmp_path / "project")
    with e.db.connect() as conn:
        conn.execute(
            "UPDATE threads SET project_path=?,project_name=? WHERE thread_id=?",
            (project, "project", thread),
        )
        for column in ["next_run_at", "last_run_at", "schedule_paused"]:
            conn.execute(f"ALTER TABLE task_workflows DROP COLUMN {column}")
        conn.execute("ALTER TABLE task_runs DROP COLUMN definition_json")
    run_migrations(e.db)
    run_migrations(e.db)
    assert e.repos.task_repo.get("kept").prompt == "keep this task"
    with e.db.connect() as conn:
        assert (
            conn.execute(
                "SELECT project_path FROM threads WHERE thread_id=?", (thread,)
            ).fetchone()[0]
            == project
        )
        assert {"next_run_at", "last_run_at", "schedule_paused"} <= {
            row["name"] for row in conn.execute("PRAGMA table_info(task_workflows)")
        }
        assert "definition_json" in {
            row["name"] for row in conn.execute("PRAGMA table_info(task_runs)")
        }


@pytest.mark.asyncio
async def test_runtime_permission_and_expert_owner_are_rechecked_before_execution(setup):
    e = setup
    task = await enqueue(e)
    with e.db.connect() as conn:
        conn.execute("UPDATE agents SET user_id=? WHERE agent_id=?", (e.other, "a"))
    await e.manager.process_once()
    assert e.repos.task_repo.get(task.id).state == "failed"
    assert e.repos.task_repo.get(task.id).error_code == "permission_removed"
    e.agents.start.assert_not_awaited()
    with e.db.connect() as conn:
        conn.execute("UPDATE users SET role='user',permissions='[\"tasks\"]' WHERE id=?", (e.uid,))
    # Standard permission semantics, without a hard-coded role allowlist.
    allowed = await e.manager.enqueue(
        e.uid, TaskCreate(agent_id="b", title="allowed", prompt="allowed")
    )
    assert allowed.state == "queued"
    with e.db.connect() as conn:
        conn.execute("UPDATE users SET permissions='[]' WHERE id=?", (e.uid,))
    await e.manager.process_once()
    assert e.repos.task_repo.get(allowed.id).state == "failed"
    e.agents.start.assert_not_awaited()


@pytest.mark.asyncio
async def test_approval_waits_for_exact_continuation_before_dag_handoff(setup):
    e = setup
    await e.channels.start()
    try:
        flow = await e.manager.create_workflow(e.uid, name="flow", definition=definition())
        run = await e.manager.run_workflow(e.uid, flow.workflow_id)
        e.processor.pause = True
        await e.manager.process_once()
        await settled(e.manager)
        first = e.repos.task_repo.run_tasks(run, e.uid)[0]
        continuation = asyncio.get_running_loop().create_future()
        await e.manager.complete_waiting_turn(
            agent_id="a",
            user_id=e.uid,
            thread_id=first.thread_id,
            failed=False,
            paused=False,
            output="SSE output ",
            continuation=continuation,
        )
        assert e.repos.task_repo.get(first.id).state == "running"
        await e.manager.process_once()
        assert len(e.processor.received) == 1
        # Socket idle flags and an unrelated thread event cannot open the barrier.
        e.hub.mark_turn_idle(first.thread_id)
        await e.hub.push_to_thread("unrelated", {"type": "turn.ended"})
        await e.manager.process_once()
        assert len(e.processor.received) == 1
        continuation.set_result(
            {"failed": False, "paused": False, "output": "exact WS continuation"}
        )
        await settled(e.manager)
        assert e.repos.task_repo.get(first.id).state == "completed"
        await e.manager.process_once()
        await settled(e.manager)
        assert "SSE output exact WS continuation" in e.processor.received[-1].text
    finally:
        await e.manager.stop()
        await e.channels.stop()


@pytest.mark.asyncio
async def test_already_finished_and_repaused_continuations_keep_ordered_output(setup):
    e = setup
    await e.channels.start()
    try:
        task = await enqueue(e)
        e.processor.pause = True
        await e.manager.process_once()
        await settled(e.manager)
        row = e.repos.task_repo.get(task.id)
        completion = asyncio.get_running_loop().create_future()
        completion.set_result({"failed": False, "paused": True, "output": "WS new approval "})
        await e.manager.complete_waiting_turn(
            agent_id="a",
            user_id=e.uid,
            thread_id=row.thread_id,
            failed=False,
            paused=False,
            output="SSE first ",
            continuation=completion,
        )
        await settled(e.manager)
        assert e.repos.task_repo.get(task.id).state == "waiting"
        await e.manager.complete_waiting_turn(
            agent_id="a",
            user_id=e.uid,
            thread_id=row.thread_id,
            failed=False,
            paused=False,
            output="SSE final",
        )
        assert (
            e.repos.task_repo.get(task.id).result
            == "before approval SSE first WS new approval SSE final"
        )
        assert e.repos.task_repo.get(task.id).state == "completed"
    finally:
        await e.manager.stop()
        await e.channels.stop()


@pytest.mark.asyncio
async def test_real_parked_steer_queue_future_is_the_completion_barrier(setup):
    from octop.infra.gateway.ws.ws_channel import resume_parked_steers

    e = setup
    await e.channels.start()
    try:
        flow = await e.manager.create_workflow(e.uid, name="flow", definition=definition())
        run = await e.manager.run_workflow(e.uid, flow.workflow_id)
        e.processor.gate = asyncio.Event()
        e.processor.pause = True
        await e.manager.process_once()
        for _ in range(100):
            if e.processor.received:
                break
            await asyncio.sleep(0.005)
        first = e.repos.task_repo.run_tasks(run, e.uid)[0]
        turn = e.steer.get_state(first.thread_id)
        admitted = e.steer.admit(
            first.thread_id,
            text="parked steer",
            client_pending_id="pending",
            expected_turn_id=turn.turn_id,
        )
        assert admitted is not None and admitted.__class__.__name__ == "SteerAdmitOk"
        e.processor.gate.set()
        await settled(e.manager)
        assert e.repos.task_repo.get(first.id).state == "waiting"
        e.processor.gate = asyncio.Event()
        completion = await resume_parked_steers(
            SimpleNamespace(app_runtime=SimpleNamespace(gateway=e.gateway)),
            agent_id="a",
            thread_id=first.thread_id,
            session_key=e.gateway.thread_registry.get_thread(first.thread_id).session_key,
            channel_type="dashboard",
            user_id=e.uid,
        )
        assert isinstance(completion, asyncio.Future)
        await e.manager.complete_waiting_turn(
            agent_id="a",
            user_id=e.uid,
            thread_id=first.thread_id,
            failed=False,
            paused=False,
            output="SSE resumed ",
            continuation=completion,
        )
        for _ in range(100):
            if len(e.processor.received) == 2:
                break
            await asyncio.sleep(0.005)
        await e.manager.process_once()
        assert len(e.processor.received) == 2
        assert e.repos.task_repo.get(first.id).state == "running"
        assert e.repos.task_repo.run_tasks(run, e.uid)[1].state == "queued"
        e.processor.gate.set()
        await settled(e.manager)
        assert e.repos.task_repo.get(first.id).state == "completed"
        await e.manager.process_once()
        await settled(e.manager)
        assert len(e.processor.received) == 3
        assert "before approval SSE resumed verified output" in e.processor.received[-1].text
    finally:
        await e.manager.stop()
        await e.channels.stop()


@pytest.mark.asyncio
async def test_resume_race_and_http_disconnect_keep_finalization_owned(setup, monkeypatch):
    import threading

    e = setup
    await e.channels.start()
    blocked = threading.Event()
    release = threading.Event()
    original = e.repos.task_repo.transition

    def transition(task_id, **kwargs):
        if kwargs.get("action") == "waiting":
            blocked.set()
            assert release.wait(3)
        return original(task_id, **kwargs)

    monkeypatch.setattr(e.repos.task_repo, "transition", transition)
    try:
        task = await enqueue(e)
        e.processor.pause = True
        await e.manager.process_once()
        for _ in range(200):
            if blocked.is_set():
                break
            await asyncio.sleep(0.005)
        assert blocked.is_set()
        row = e.repos.task_repo.get(task.id)
        assert row.state == "running"
        continuation = asyncio.get_running_loop().create_future()
        continuation.set_result({"failed": False, "paused": False, "output": "WS finished"})
        request = asyncio.create_task(
            e.manager.complete_waiting_turn(
                agent_id="a",
                user_id=e.uid,
                thread_id=row.thread_id,
                failed=False,
                paused=False,
                output="SSE output ",
                continuation=continuation,
            )
        )
        for _ in range(100):
            if e.manager._finalizers:
                break
            await asyncio.sleep(0.005)
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request
        assert e.repos.task_repo.get(task.id).state == "running"
        release.set()
        for _ in range(300):
            if e.repos.task_repo.get(task.id).state == "completed":
                break
            await asyncio.sleep(0.005)
        assert e.repos.task_repo.get(task.id).state == "completed"
        assert e.repos.task_repo.get(task.id).result == "before approval SSE output WS finished"
    finally:
        release.set()
        await e.manager.stop()
        await e.channels.stop()


@pytest.mark.asyncio
async def test_quiet_completion_and_failure_have_single_scoped_alert_policy(setup):
    e = setup
    await e.channels.start()
    frames = []

    async def capture(user_id, frame):
        frames.append((user_id, frame))

    e.hub.set_user_frame_observer(capture)
    try:
        quiet = await e.manager.enqueue(
            e.uid, TaskCreate(agent_id="a", title="quiet", prompt="quiet", options={"quiet": True})
        )
        await e.manager.process_once()
        await settled(e.manager)
        completion = [
            frame
            for owner, frame in frames
            if frame.get("task_id") == quiet.id and frame.get("status") == "completed"
        ]
        assert completion and completion[-1]["notify"] is False
        e.gateway.notify_dashboard_push.assert_not_awaited()
        e.processor.fail = True
        failure = await e.manager.enqueue(
            e.uid,
            TaskCreate(agent_id="a", title="failure", prompt="failure", options={"quiet": True}),
        )
        await e.manager.process_once()
        await settled(e.manager)
        alert = [
            frame
            for owner, frame in frames
            if frame.get("task_id") == failure.id and frame.get("status") == "failed"
        ]
        assert len(alert) == 1 and alert[0]["notify"] is True
        assert e.gateway.notify_dashboard_push.call_args.kwargs["notify"] is False
        assert all(owner == e.uid for owner, frame in frames)
    finally:
        await e.manager.stop()
        await e.channels.stop()


@pytest.mark.asyncio
async def test_cancelled_task_cannot_execute_a_not_yet_admitted_continuation(setup):
    from octop_gateway.models import ChannelSubject, InboundMessage, TextContent

    e = setup
    await e.channels.start()
    task = await enqueue(e)
    assert e.repos.task_repo.claim(task.id)
    thread = await e.gateway.thread_registry.get_or_create(
        agent_id="a",
        user_id=e.uid,
        channel_type="dashboard",
        channel_subject_id="cancel-before-admit",
    )
    e.repos.task_repo.transition(
        task.id,
        expected={"running"},
        state="waiting",
        action="waiting",
        fields={"thread_id": thread},
    )
    entered = asyncio.Event()
    release = asyncio.Event()

    async def held():
        entered.set()
        await release.wait()

    lock = asyncio.create_task(e.channels.run_in_session(WS_CHANNEL_ID, f"thread:{thread}", held))
    await entered.wait()
    completion = asyncio.get_running_loop().create_future()
    e.channels.enqueue(
        WS_CHANNEL_ID,
        InboundMessage(
            channel_id=WS_CHANNEL_ID,
            channel_type="dashboard",
            tenant_id="a",
            channel_subject=ChannelSubject(subject_id=str(e.uid)),
            content=[TextContent(text="must not run")],
            metadata={
                "thread_id": thread,
                "session_key": e.gateway.thread_registry.get_thread(thread).session_key,
                "task_id": task.id,
                "ws_connection_id": "internal",
                "_octop_turn_completion": completion,
            },
        ),
    )
    try:
        await e.manager.action(e.uid, task.id, "cancel")
        assert task.id not in e.manager._continuations
        release.set()
        await lock
        outcome = await asyncio.wait_for(completion, timeout=2)
        assert outcome["failed"] is True
        assert e.processor.received == []
        assert e.repos.task_repo.get(task.id).state == "cancelled"
    finally:
        release.set()
        await e.manager.stop()
        await e.channels.stop()
