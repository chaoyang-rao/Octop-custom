"""Small, quoted delegation packets; original records remain the source of truth."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from octop.infra.db.repos.tasks import TaskRow

BRIEF_CHARS = 8000
REPORT_CHARS = 2400
DEPENDENCY_CHARS = 16000
_OMITTED = "\n… [excerpt; read the source before acting on omitted requirements] …\n"


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


def excerpt(text: str, limit: int) -> str:
    """An explicit head/tail excerpt, never presented as a semantic summary."""
    if len(text) <= limit:
        return text
    if limit <= len(_OMITTED):
        return "…" if limit else ""
    available = limit - len(_OMITTED)
    head = available // 2
    return text[:head] + _OMITTED + text[-(available - head) :]


def _object(text: str) -> dict[str, Any]:
    raw = text.strip()
    if raw.startswith("```json\n") and raw.endswith("```"):
        raw = raw[8:-3]
    try:
        value = json.loads(raw)
    except (ValueError, RecursionError):
        return {}
    return value if isinstance(value, dict) else {}


def _fit(data: dict[str, Any], limit: int) -> dict[str, Any]:
    """Budget serialized characters, including escaping, not just source text."""
    while len(dumps(data)) > limit:
        slots: list[tuple[Any, Any, str]] = []
        for field, item in data.items():
            if field == "kind":
                continue
            if isinstance(item, list):
                slots.extend(
                    (item, index, value)
                    for index, value in enumerate(item)
                    if isinstance(value, str) and len(value) > 1
                )
            elif isinstance(item, str) and len(item) > 1:
                slots.append((data, field, item))
        if not slots:
            lists = [key for key, value in data.items() if isinstance(value, list)]
            if not lists:
                break
            key = max(lists, key=lambda name: len(data[name]))
            if data[key]:
                data[key].pop()
            else:
                del data[key]
            continue
        container, key, value = max(slots, key=lambda slot: len(slot[2]))
        container[key] = excerpt(value, max(1, len(value) // 2))
    return data


def brief(text: str, *, source: dict[str, Any]) -> str:
    raw = _object(text)
    list_keys = ("constraints", "acceptance", "materials")
    structured = (
        isinstance(raw.get("goal"), str)
        and not set(raw) - {"goal", *list_keys}
        and all(
            isinstance(raw.get(key, []), list)
            and all(isinstance(item, str) for item in raw.get(key, []))
            for key in list_keys
        )
    )
    fields: dict[str, Any] = {"kind": "task_brief" if structured else "task_excerpt"}
    fields["goal"] = raw["goal"] if structured else text
    for key in list_keys:
        value = raw.get(key)
        fields[key] = [str(item) for item in value[:8]] if isinstance(value, list) else []
    original = dumps(fields)
    packet = _fit(fields, BRIEF_CHARS)
    omitted = structured and any(len(raw.get(key, [])) > 8 for key in list_keys)
    return dumps(
        {"brief": packet, "source": source, "source_required": omitted or original != dumps(packet)}
    )


def report(text: str, *, limit: int = REPORT_CHARS) -> dict[str, Any]:
    raw = _object(text)
    summary = raw.get("summary")
    if isinstance(summary, str):
        data: dict[str, Any] = {"kind": "report", "summary": summary}
        for key in ("evidence", "artifacts", "remaining"):
            value = raw.get(key)
            data[key] = [str(item) for item in value[:4]] if isinstance(value, list) else []
    else:
        data = {"kind": "excerpt", "summary": text.strip() or "(empty)"}
    data["source_required"] = len(dumps(data)) + 25 > limit or any(
        isinstance(raw.get(key), list) and len(raw[key]) > 4
        for key in ("evidence", "artifacts", "remaining")
    )
    return _fit(data, limit)


def dependency_packet(rows: Sequence[TaskRow]) -> str:
    entries: list[dict[str, Any]] = [
        {
            "step": row.step_key,
            "task_id": row.task_id,
            "agent_id": row.agent_id,
            "thread_id": row.thread_id,
            "result": {},
        }
        for row in rows
    ]
    packet = {"dependency_results": entries}
    if len(dumps(packet)) > DEPENDENCY_CHARS // 2:
        # task_id is sufficient for owner-scoped expert_tasks.read; redundant
        # labels must not crowd out the actual findings in a large workflow.
        for entry in entries:
            entry.pop("step")
            entry.pop("thread_id")
    # Reserve all references first, then share the remaining budget fairly.
    quota = min(REPORT_CHARS, (DEPENDENCY_CHARS - len(dumps(packet))) // max(1, len(rows)))
    for entry, row in zip(entries, rows, strict=True):
        entry["result"] = report(row.result, limit=max(64, quota))
    return dumps(packet)
