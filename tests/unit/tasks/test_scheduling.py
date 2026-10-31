"""Persistent workflow timing, failure control and scoped iCalendar output."""

from __future__ import annotations

import datetime as dt
from unittest.mock import Mock

import pytest
from tests.unit.tasks.test_task_manager import definition, settled
from tests.unit.tasks.test_task_manager import setup as setup

from octop.infra.errors import OctopError
from octop.infra.tasks.models import WorkflowDefinition
from octop.infra.tasks.scheduling import calendar_document, next_occurrence


def scheduled():
    data = definition().model_dump()
    data["schedule"] = "cron:0 9 * * *"
    return WorkflowDefinition.model_validate(data)


def test_trigger_uses_server_timezone_and_calendar_folds_utf8():
    after = int(dt.datetime(2030, 1, 1, tzinfo=dt.UTC).timestamp())
    assert next_occurrence("cron:0 9 * * *", timezone="Asia/Shanghai", after=after) == after + 3600
    text = calendar_document([("flow", "中文" * 80 + "\r\nBEGIN:VEVENT", after)], now=after)
    assert all(len(line.encode("utf-8")) <= 75 for line in text.split("\r\n"))
    assert text.count("\r\nBEGIN:VEVENT\r\n") == 1
    assert "\\nBEGIN:VEVENT" in text
    assert "DTSTART:20300101T000000Z" in text


@pytest.mark.asyncio
async def test_scheduled_enqueue_is_idempotent_across_cursor_retry(setup, monkeypatch):
    e = setup
    flow = await e.manager.create_workflow(e.uid, name="timed", definition=scheduled())
    clock = int(dt.datetime.now(dt.UTC).timestamp())
    due = clock - 60
    e.repos.task_repo.pause_schedule(flow.workflow_id, False, due)
    advance = e.repos.task_repo.advance_schedule
    monkeypatch.setattr(
        e.repos.task_repo,
        "advance_schedule",
        Mock(side_effect=RuntimeError("simulated host interruption")),
    )
    with pytest.raises(RuntimeError):
        await e.manager.process_schedules(now=clock)
    assert len(await e.manager.runs(e.uid)) == 1
    monkeypatch.setattr(e.repos.task_repo, "advance_schedule", advance)
    await e.manager.process_schedules(now=clock)
    assert len(await e.manager.runs(e.uid)) == 1
    assert e.repos.task_repo.workflow(flow.workflow_id).next_run_at > clock
    await e.manager.process_schedules(now=clock)
    assert len(await e.manager.runs(e.uid)) == 1


@pytest.mark.asyncio
async def test_failure_pauses_future_schedule_until_explicit_resume(setup):
    e = setup
    await e.channels.start()
    try:
        flow = await e.manager.create_workflow(e.uid, name="timed", definition=scheduled())
        await e.manager.run_workflow(e.uid, flow.workflow_id)
        e.processor.fail = True
        await e.manager.process_once()
        await settled(e.manager)
        assert e.repos.task_repo.workflow(flow.workflow_id).schedule_paused == 1
        await e.manager.set_schedule_paused(e.uid, flow.workflow_id, False)
        assert e.repos.task_repo.workflow(flow.workflow_id).schedule_paused == 0
    finally:
        await e.manager.stop()
        await e.channels.stop()


@pytest.mark.asyncio
async def test_calendar_link_is_read_only_owned_and_revocable(setup):
    e = setup
    await e.manager.create_workflow(e.uid, name="Owned calendar entry", definition=scheduled())
    token = await e.manager.rotate_calendar(e.uid, enabled=True)
    text = await e.manager.calendar_for_token(token)
    assert "Owned calendar entry" in text
    assert "start" not in text  # Task prompt bodies are never in the feed.
    second = await e.manager.rotate_calendar(e.uid, enabled=True)
    with pytest.raises(OctopError):
        await e.manager.calendar_for_token(token)
    assert "BEGIN:VCALENDAR" in await e.manager.calendar_for_token(second)
    await e.manager.rotate_calendar(e.uid, enabled=False)
    with pytest.raises(OctopError):
        await e.manager.calendar_for_token(second)


@pytest.mark.asyncio
async def test_calendar_and_webhook_are_revoked_when_account_loses_permission(setup):
    e = setup
    flow = await e.manager.create_workflow(e.uid, name="timed", definition=scheduled())
    token = await e.manager.rotate_calendar(e.uid, enabled=True)
    hook = await e.manager.rotate_webhook(e.uid, flow.workflow_id, enabled=True)
    with e.db.connect() as conn:
        conn.execute("UPDATE users SET role='user',permissions='[]' WHERE id=?", (e.uid,))
    with pytest.raises(OctopError):
        await e.manager.calendar_for_token(token)
    with pytest.raises(OctopError):
        await e.manager.trigger_webhook(flow.workflow_id, hook, {})
    assert await e.manager.runs(e.uid) == []
