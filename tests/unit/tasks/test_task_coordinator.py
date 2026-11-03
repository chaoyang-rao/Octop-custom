"""Coordinator integration with durable evidence and fake, explicitly scoped model turns."""

from __future__ import annotations

import asyncio
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
from octop.infra.tasks.admission import finish_task
from octop.infra.tasks.coordinator import MAX_REVIEWS, TaskCoordinator
from octop.infra.tasks.coordinator_turn import CoordinatorTurnBusy
from octop.infra.tasks.manager import TaskManager
from octop.infra.tasks.models import TaskCreate
from octop.infra.tasks.scope import CoordinatorContext, coordinator_scope


def host_context(scope, **changes):
    return CoordinatorContext(
        scope_id=scope["scope_id"],
        user_id=scope["user_id"],
        origin_agent_id=scope["origin_agent_id"],
        origin_thread_id=scope["origin_thread_id"],
        parent_task_id=scope.get("parent_task_id"),
        parent_attempt=scope.get("parent_attempt"),
        allow_publish=bool(scope.get("allow_publish")),
        active_signature=changes.get("active_signature", scope.get("active_signature", "")),
    )


class Processor:
    def __init__(self):
        self.hook = None
        self.hitl_coordinator = SimpleNamespace(expire_pending_for_thread=Mock())
        self.teams = SimpleNamespace(cancel_member_hitl=Mock())

    async def __call__(self, _message):
        if False:
            yield None

    async def iter_turn_chunks(self, message):
        if self.hook is not None:
            await self.hook(message)
        yield {"type": "token", "content": "delegated work"}
        yield {"type": "done"}


class Invocation:
    def __init__(self, env):
        self.env = env
        self.calls = []
        self.model_calls = 0
        self.actions = []
        self.busy_once = False

    async def __call__(self, _agents, _gateway, scope, prompt, *, user_input):
        self.calls.append({"scope": scope, "prompt": prompt, "user_input": user_input})
        if self.busy_once:
            self.busy_once = False
            raise CoordinatorTurnBusy("source admission raced")
        self.model_calls += 1
        action = self.actions.pop(0) if self.actions else "ready"
        with coordinator_scope(host_context(scope)):
            if callable(action):
                await action(scope)
            else:
                await self.env.manager.decide_coordination(
                    self.env.uid,
                    scope["scope_id"],
                    decision=action,
                    summary="reviewed evidence",
                    question="请选择范围" if action == "needs_user" else "",
                )
        return {"failed": False, "paused": False, "output": "reviewed evidence"}


@pytest.fixture
async def env(tmp_path, monkeypatch):
    monkeypatch.setenv("OCTOP_HOME", str(tmp_path))
    db = SqlitePool(tmp_path / "coordinator.sqlite")
    run_migrations(db)
    repos = RepoBundle.from_pool(db)
    uid = repos.user_repo.create(username="owner", password_hash="test", role="admin")
    foreign = repos.user_repo.create(username="foreign", password_hash="test", role="admin")
    for aid, owner in [("main", uid), ("worker", uid), ("next", uid), ("foreign", foreign)]:
        repos.agent_repo.create(agent_id=aid, user_id=owner, name=aid)
    registry = ThreadRegistry(session_repo=repos.session_repo, thread_repo=repos.thread_repo)
    origin = await registry.get_or_create(
        agent_id="main", user_id=uid, channel_type="dashboard", channel_subject_id="origin"
    )
    processor, hub, steer = Processor(), WebSocketHub(), SteerCoordinator()
    channel = WebSocketChannel(processor, hub=hub, steer=steer)
    channels = ChannelManager(
        channels={WS_CHANNEL_ID: channel}, media_backend=FileSystemMediaBackend(str(tmp_path))
    )
    gateway = SimpleNamespace(
        dashboard_channel_id=WS_CHANNEL_ID,
        channel_manager=channels,
        ws_hub=hub,
        steer=steer,
        processor=processor,
        thread_registry=registry,
        notify_dashboard_push=AsyncMock(),
    )
    busy = set()
    agents = SimpleNamespace(
        principal_agent_id=lambda aid: aid,
        is_agent_active=lambda aid: aid in busy,
        start=AsyncMock(),
        cancel_stream=Mock(),
        get_row=repos.agent_repo.get,
        validate_mcp_servers=lambda _uid, value: value,
        validate_knowledge_base_ids=lambda _uid, value: value,
        list_skill_summaries=AsyncMock(return_value=[]),
        providers=SimpleNamespace(is_model_ref_usable=lambda _model: True),
    )
    agents.get_agent = lambda _aid: SimpleNamespace(
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
    result = SimpleNamespace(
        db=db,
        repos=repos,
        uid=uid,
        foreign=foreign,
        origin=origin,
        manager=manager,
        agents=agents,
        gateway=gateway,
        channels=channels,
        channel=channel,
        processor=processor,
        busy=busy,
        tmp_path=tmp_path,
    )
    result.invoke = Invocation(result)
    result.coordinator = TaskCoordinator(manager, invoke_turn=result.invoke)
    manager._coordinator = result.coordinator
    channel.set_task_admission(manager.admit_turn)
    try:
        yield result
    finally:
        await manager.stop()
        await channels.stop()
        db.close()


def new_scope(env, scope_id="scope", **changes):
    return env.repos.task_coordination_repo.ensure(
        {
            "scope_id": scope_id,
            "user_id": env.uid,
            "origin_agent_id": "main",
            "origin_thread_id": env.origin,
            "source_message_id": f"user-{scope_id}",
            "goal_text": "交付同一用户目标",
            "initial_user_turn": True,
            **changes,
        }
    )


def add_member(env, scope_id="scope", task_id="member", agent_id="worker", *, coding=None):
    scope = env.repos.task_coordination_repo.get(scope_id)
    env.repos.task_repo.enqueue(
        [
            {
                "task_id": task_id,
                "user_id": env.uid,
                "agent_id": agent_id,
                "title": f"task {task_id}",
                "prompt": "perform the requested work",
                "dispatch": {
                    "origin_agent_id": "main",
                    "origin_thread_id": env.origin,
                    "scope_id": scope_id,
                    "parent_task_id": scope.get("parent_task_id"),
                    "parent_attempt": scope.get("parent_attempt"),
                    "coding_spec": coding,
                },
            }
        ]
    )
    return task_id


def complete_member(env, task_id="member", *, returned=True, state="completed"):
    repo = env.repos.task_repo
    row = repo.get(task_id)
    if row.state == "queued":
        assert repo.claim(task_id)
        row = repo.get(task_id)
    assert repo.transition(
        task_id,
        expected={row.state},
        state=state,
        action=state,
        fields={"result": "verified member result"},
    )
    row = repo.get(task_id)
    if returned:
        assert env.repos.task_dispatch_repo.mark_returned(task_id, row.attempt, state=state)


async def schedule(env):
    await env.coordinator.schedule()
    jobs = list(env.coordinator.jobs.values())
    if jobs:
        await asyncio.wait_for(asyncio.gather(*jobs), timeout=5)


async def test_scope_reviews_once_after_all_member_returns_land(env):
    new_scope(env)
    add_member(env)
    add_member(env, task_id="second", agent_id="next")
    complete_member(env, returned=False)
    complete_member(env, "second")
    await schedule(env)
    assert env.invoke.model_calls == 0
    row = env.repos.task_repo.get("member")
    assert env.repos.task_dispatch_repo.mark_returned("member", row.attempt, state="completed")
    await schedule(env)
    await schedule(env)
    await schedule(env)
    assert env.invoke.model_calls == 1
    assert "original_user_goal" in env.invoke.calls[0]["prompt"]
    assert env.repos.task_coordination_repo.get("scope")["decision"] == "ready"


async def test_a_new_child_waits_then_triggers_a_new_review(env):
    new_scope(env)
    add_member(env)
    complete_member(env)

    async def delegate_more(scope):
        await env.manager.enqueue(
            env.uid,
            TaskCreate(
                agent_id="next",
                title="follow-up",
                prompt="verify the remaining requirement",
                origin_thread_id=env.origin,
            ),
            coordination={"scope_id": scope["scope_id"]},
        )
        await env.manager.decide_coordination(
            env.uid,
            scope["scope_id"],
            decision="continue",
            summary="one remaining requirement",
            question="",
        )

    env.invoke.actions = [delegate_more, "ready"]
    await schedule(env)
    await schedule(env)
    assert env.invoke.model_calls == 1
    members = env.repos.task_coordination_repo.members("scope")
    child = next(member for member in members if member["task_id"] != "member")
    assert child["state"] == "queued"
    complete_member(env, child["task_id"])
    await schedule(env)
    await schedule(env)
    assert env.invoke.model_calls == 2


async def test_needs_user_blocks_auto_loop_and_resume_input_is_consumed_once(env):
    new_scope(env)
    add_member(env)
    complete_member(env)
    env.invoke.actions = ["needs_user", "ready", "ready"]
    await schedule(env)
    await schedule(env)
    assert env.invoke.model_calls == 1
    assert env.repos.task_coordination_repo.get("scope")["state"] == "needs_user"
    await env.manager.continue_coordination(env.uid, "member", prompt="真实用户补充")
    await schedule(env)
    add_member(env, task_id="later", agent_id="next")
    complete_member(env, "later")
    await schedule(env)
    assert [call["user_input"] for call in env.invoke.calls] == ["", "真实用户补充", ""]
    scope = env.repos.task_coordination_repo.get("scope")
    assert scope["resume_seq"] == scope["handled_resume_seq"] == 1


async def test_review_budget_stops_before_a_ninth_model_turn(env):
    new_scope(env)
    add_member(env)
    complete_member(env)
    for turn in range(MAX_REVIEWS):
        if turn:
            complete_member(env)
        await schedule(env)
    complete_member(env)
    await schedule(env)
    assert env.invoke.model_calls == MAX_REVIEWS
    scope = env.repos.task_coordination_repo.get("scope")
    assert scope["state"] == "needs_user" and scope["question"]
    await schedule(env)
    assert env.invoke.model_calls == MAX_REVIEWS


async def test_busy_admission_refunds_the_claim_without_consuming_a_signature(env):
    new_scope(env)
    add_member(env)
    complete_member(env)
    env.invoke.busy_once = True
    await schedule(env)
    scope = env.repos.task_coordination_repo.get("scope")
    assert scope["state"] == "pending" and scope["review_turns"] == 0
    assert not scope["last_signature"] and not scope["active_signature"]
    await schedule(env)
    assert env.invoke.model_calls == 1


@pytest.mark.parametrize(
    "denial", ["permission", "disabled", "source_owner", "principal", "active", "hitl"]
)
async def test_source_authority_and_activity_gate_model_calls(env, denial):
    new_scope(env)
    add_member(env)
    complete_member(env)
    with env.db.connect() as conn:
        if denial == "permission":
            conn.execute("UPDATE users SET role='user',permissions='[]' WHERE id=?", (env.uid,))
        elif denial == "disabled":
            conn.execute("UPDATE users SET disabled=1 WHERE id=?", (env.uid,))
        elif denial == "source_owner":
            conn.execute(
                "UPDATE threads SET user_id=? WHERE thread_id=?", (env.foreign, env.origin)
            )
        elif denial == "principal":
            env.agents.principal_agent_id = lambda _aid: "foreign"
        elif denial == "active":
            env.gateway.ws_hub.mark_turn_active(env.origin)
        else:
            env.gateway.steer.begin_turn(env.origin)
            env.gateway.steer.set_phase(env.origin, "hitl_paused")
    await schedule(env)
    assert env.invoke.model_calls == 0
    assert env.repos.task_coordination_repo.get("scope")["review_turns"] == 0


async def test_decide_requires_the_current_host_signature_and_no_pending_members(env):
    new_scope(env)
    add_member(env)
    scopes = env.repos.task_coordination_repo
    assert scopes.claim("scope", "old")
    old = scopes.get("scope")
    assert scopes.defer("scope", "old")
    assert scopes.claim("scope", "new")
    with coordinator_scope(host_context(old)):
        with pytest.raises(OctopError) as stale:
            await env.manager.decide_coordination(
                env.uid, "scope", decision="continue", summary="stale", question=""
            )
        assert stale.value.status == 403
    with coordinator_scope(host_context(scopes.get("scope"))):
        with pytest.raises(OctopError) as pending:
            await env.manager.decide_coordination(
                env.uid, "scope", decision="ready", summary="premature", question=""
            )
        assert pending.value.details["task_reason"] == "coordination_running"
    assert scopes.get("scope")["decision"] == ""


async def test_false_publish_scope_rejects_new_and_retried_publish_work(env):
    new_scope(env)
    add_member(env)
    complete_member(env)
    scopes = env.repos.task_coordination_repo
    assert scopes.claim("scope", "review")
    project = env.tmp_path / "project"
    project.mkdir()
    env.repos.thread_repo.upsert_project(
        agent_id="main",
        user_id=env.uid,
        project_path=str(project.resolve()),
        project_name="project",
    )
    coding = {"project_path": str(project), "test_commands": ["python -V"], "publish_pr": True}
    with coordinator_scope(host_context(scopes.get("scope"))):
        with pytest.raises(OctopError) as created:
            await env.manager.enqueue(
                env.uid,
                TaskCreate(
                    agent_id="next",
                    title="publish",
                    prompt="unapproved publication",
                    origin_thread_id=env.origin,
                    coding=coding,
                ),
                coordination={"scope_id": "scope"},
            )
        assert created.value.details["task_reason"] == "coordination_publish"
        add_member(env, task_id="old-publisher", agent_id="next", coding=coding)
        complete_member(env, "old-publisher", state="failed")
        with pytest.raises(OctopError) as retried:
            await env.manager.validate_scoped_action(env.uid, "scope", "old-publisher", "retry")
        assert retried.value.details["task_reason"] == "coordination_publish"


async def test_cancelled_child_cannot_be_automatically_retried(env):
    new_scope(env)
    add_member(env)
    complete_member(env, state="cancelled")
    scopes = env.repos.task_coordination_repo
    assert scopes.claim("scope", "review")
    with coordinator_scope(host_context(scopes.get("scope"))):
        with pytest.raises(OctopError) as stopped:
            await env.manager.validate_scoped_action(env.uid, "scope", "member", "retry")
        assert stopped.value.details["task_reason"] == "coordination_cancelled"


async def test_parent_cannot_finish_before_its_scoped_review_verdict(env):
    env.repos.task_repo.enqueue(
        [
            {
                "task_id": "parent",
                "user_id": env.uid,
                "agent_id": "main",
                "thread_id": env.origin,
                "title": "root goal",
                "prompt": "coordinate the requested outcome",
            }
        ]
    )
    assert env.repos.task_repo.claim("parent")
    parent = env.repos.task_repo.get("parent")
    new_scope(env, parent_task_id="parent", parent_attempt=parent.attempt)
    add_member(env)
    complete_member(env)
    assert await env.coordinator.parent_pending(parent)
    assert not await env.coordinator.parent_review_ready(parent)
    finishing = asyncio.create_task(
        finish_task(env.manager, parent, state="completed", fields={"result": "child returned"})
    )
    try:
        await asyncio.sleep(0.05)
        assert env.repos.task_repo.get("parent").state != "completed"
        await schedule(env)
        assert await env.coordinator.parent_review_ready(parent)
        assert not await env.coordinator.parent_pending(parent)
        await asyncio.wait_for(finishing, timeout=5)
        assert env.repos.task_repo.get("parent").state == "completed"
    finally:
        if not finishing.done():
            finishing.cancel()
            await asyncio.gather(finishing, return_exceptions=True)
