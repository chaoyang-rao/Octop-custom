"""Resolve chat project metadata from the authoritative thread repository."""

from __future__ import annotations

from typing import Any

PROJECT_CONFIG_KEYS = ("octop_project_path", "octop_project_name")


def thread_project_config(
    thread_repo: Any, *, agent_id: str, thread_id: str
) -> dict[str, str]:
    if not thread_id:
        return {}
    row = thread_repo.get(thread_id)
    if row is None or row.agent_id != agent_id:
        return {}
    path = getattr(row, "project_path", None)
    if not isinstance(path, str) or not path.strip():
        return {}
    name = getattr(row, "project_name", None)
    return {
        "octop_project_path": path.strip(),
        "octop_project_name": name.strip() if isinstance(name, str) else "",
    }
