"""Delegation carries bounded current state while full records stay readable."""

from __future__ import annotations

import json
from dataclasses import replace

from tests.unit.tasks.test_task_manager import definition, settled
from tests.unit.tasks.test_task_manager import setup as setup

from octop.infra.tasks.handoff import DEPENDENCY_CHARS, brief, dependency_packet, dumps, report
from octop.infra.tasks.models import TaskCreate, TaskOptions


def test_structured_brief_keeps_constraints_and_requires_source_for_omissions():
    raw = {
        "goal": "Deliver",
        "constraints": ["Do not publish"],
        "acceptance": ["Tests pass"],
        "materials": ["src/a.py"],
    }
    packet = json.loads(brief(json.dumps(raw), source={"task_id": "one"}))
    assert packet["brief"]["constraints"] == ["Do not publish"]
    assert not packet["source_required"]
    raw["materials"] = ["x" * 5000] * 10
    packet = json.loads(brief(json.dumps(raw), source={"task_id": "one"}))
    assert packet["source_required"]
    assert packet["brief"]["constraints"] == ["Do not publish"]


def test_report_retains_explicit_conclusion_and_artifact_instead_of_process():
    packet = report(
        json.dumps(
            {
                "summary": "Verified conclusion",
                "artifacts": ["outbound/report.md"],
                "process": "x" * 128000,
                "remaining": ["Device check"],
            }
        )
    )
    assert packet["summary"] == "Verified conclusion"
    assert packet["artifacts"] == ["outbound/report.md"]
    assert "process" not in packet
    assert len(dumps(report('"\\\n' * 128000))) <= 2400


async def test_many_dependencies_share_one_budget_with_all_source_references(setup):
    task = await setup.manager.enqueue(
        setup.uid, TaskCreate(agent_id="a", title="sample", prompt="work")
    )
    rows = [
        replace(
            task, task_id=f"source-{i}", thread_id=f"thread-{i}", result="x" * 128000 + f"Final {i}"
        )
        for i in range(32)
    ]
    packet = dependency_packet(rows)
    assert len(packet) <= DEPENDENCY_CHARS
    decoded = json.loads(packet)["dependency_results"]
    assert len(decoded) == 32
    assert all(
        item["task_id"] == f"source-{i}" and f"Final {i}" in item["result"]["summary"]
        for i, item in enumerate(decoded)
    )


async def test_dependency_results_have_an_aggregate_budget_and_keep_final_conclusions(setup):
    e = setup
    await e.channels.start()
    try:
        flow = await e.manager.create_workflow(e.uid, name="flow", definition=definition())
        run = await e.manager.run_workflow(e.uid, flow.workflow_id)
        first = e.repos.task_repo.run_tasks(run, e.uid)[0]
        assert e.repos.task_repo.claim(first.task_id)
        long_result = "process details\n" * 8000 + "FINAL: verified conclusion"
        assert e.repos.task_repo.transition(
            first.task_id,
            expected={"running"},
            state="completed",
            action="completed",
            fields={"result": long_result},
        )
        await e.manager.process_once()
        await settled(e.manager)
        text = e.processor.received[-1].text
        assert len(text) < 20_000
        assert "FINAL: verified conclusion" in text
        assert first.task_id in text
        assert e.repos.task_repo.get(first.task_id).result == long_result
    finally:
        await e.manager.stop()
        await e.channels.stop()


async def test_reassignment_without_output_keeps_checkpoint_reference(setup):
    e = setup
    tid = await e.gateway.thread_registry.get_or_create(
        agent_id="a", user_id=e.uid, channel_type="dashboard", channel_subject_id="original-worker"
    )
    task = await e.manager.enqueue(
        e.uid, TaskCreate(agent_id="a", title="work", prompt="Finish safely", thread_id=tid)
    )
    assert e.repos.task_repo.claim(task.task_id)
    assert e.repos.task_repo.transition(
        task.task_id, expected={"running"}, state="failed", action="failed"
    )
    moved = await e.manager.action(e.uid, task.task_id, "reassign", agent_id="b")
    handoff = TaskOptions.model_validate_json(moved.options_json).handoff
    assert handoff.thread_id == tid and handoff.state == "failed"
    assert json.loads(handoff.report)["source_required"]
    assert e.repos.thread_repo.get(tid) is not None


async def test_reassignment_delivers_previous_state_after_retry_clears_result(setup):
    e = setup
    task = await e.manager.enqueue(
        e.uid, TaskCreate(agent_id="a", title="work", prompt="Finish it")
    )
    assert e.repos.task_repo.claim(task.task_id)
    assert e.repos.task_repo.transition(
        task.task_id,
        expected={"running"},
        state="failed",
        action="failed",
        fields={"result": json.dumps({"summary": "Already checked A", "remaining": ["Check B"]})},
    )
    await e.manager.action(e.uid, task.task_id, "reassign", agent_id="b")
    first_handoff = TaskOptions.model_validate_json(
        e.repos.task_repo.get(task.task_id).options_json
    ).handoff
    await e.manager.action(e.uid, task.task_id, "reassign", agent_id="a")
    moved = await e.manager.action(e.uid, task.task_id, "reassign", agent_id="b")
    assert TaskOptions.model_validate_json(moved.options_json).handoff == first_handoff
    await e.manager.action(e.uid, task.task_id, "retry")
    await e.channels.start()
    try:
        await e.manager.process_once()
        await settled(e.manager)
        text = e.processor.received[-1].text
        assert "Already checked A" in text and "Check B" in text
        assert "handoff" in text and task.task_id in text
    finally:
        await e.manager.stop()
        await e.channels.stop()
