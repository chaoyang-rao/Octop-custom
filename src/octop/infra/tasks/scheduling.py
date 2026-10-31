"""Workflow scheduling and iCalendar encoding using Octop's existing trigger rules."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from octop.infra.cron.trigger import AgentlyMailTrigger, build_trigger


def next_occurrence(spec: str, *, timezone: str, after: int) -> int | None:
    trigger = build_trigger(spec, timezone=timezone)
    if isinstance(trigger, AgentlyMailTrigger):
        raise ValueError("workflow schedules must use a time trigger")
    now = dt.datetime.fromtimestamp(after, ZoneInfo(timezone))
    upcoming = trigger.get_next_fire_time(None, now)
    if upcoming is None or upcoming.timestamp() < after:
        return None
    return int(upcoming.timestamp())


def _escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "\\n")
        .replace(";", "\\;")
        .replace(",", "\\,")
    )


def _fold(value: str) -> str:
    lines = []
    current = ""
    for char in value:
        if len((current + char).encode("utf-8")) > 75:
            lines.append(current)
            current = " " + char
        else:
            current += char
    lines.append(current)
    return "\r\n".join(lines)


def calendar_document(events: list[tuple[str, str, int]], *, now: int) -> str:
    def utc(value: int) -> str:
        return dt.datetime.fromtimestamp(value, dt.UTC).strftime("%Y%m%dT%H%M%SZ")

    rows = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Octop//Workflow Calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    for workflow_id, name, when in events:
        rows += [
            "BEGIN:VEVENT",
            f"UID:{workflow_id}-{when}@octop",
            f"DTSTAMP:{utc(now)}",
            f"DTSTART:{utc(when)}",
            f"SUMMARY:{_escape(name)}",
            "END:VEVENT",
        ]
    rows.append("END:VCALENDAR")
    return "\r\n".join(_fold(row) for row in rows) + "\r\n"
