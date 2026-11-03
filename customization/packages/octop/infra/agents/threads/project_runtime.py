"""Resolve chat project metadata from the authoritative thread repository."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from octop.i18n import tr
from octop.infra.utils.host_dirs import assert_safe_host_path, host_path_text
from octop.infra.utils.locale import DEFAULT_LOCALE, Locale

PROJECT_CONFIG_KEYS = ("octop_project_path", "octop_project_name")


def thread_project_config(
    thread_repo: Any,
    *,
    agent_id: str,
    thread_id: str,
    task_repo: Any = None,
    dispatch_repo: Any = None,
) -> dict[str, str]:
    if not thread_id:
        return {}
    row = thread_repo.get(thread_id)
    if row is None or row.agent_id != agent_id:
        return {}
    if task_repo is not None and dispatch_repo is not None:
        task = task_repo.latest_in_thread(agent_id, row.user_id, thread_id)
        context = dispatch_repo.get(task.task_id) if task is not None else None
        run = (context or {}).get("coding_run") or {}
        worktree = run.get("worktree")
        if (
            task is not None
            and task.state in {"running", "waiting"}
            and isinstance(worktree, str)
            and worktree
            and run.get("task_id") == task.task_id
            and run.get("user_id") == row.user_id
        ):
            return {
                "octop_project_path": worktree,
                "octop_project_name": task.title,
            }
    path = getattr(row, "project_path", None)
    if not isinstance(path, str) or not path.strip():
        return {}
    name = getattr(row, "project_name", None)
    return {
        "octop_project_path": path.strip(),
        "octop_project_name": name.strip() if isinstance(name, str) else "",
    }


def normalize_project_path(
    raw: str | None, *, allowed_root: str | None, locale: Locale = DEFAULT_LOCALE
) -> str | None:
    """Resolve an existing host folder within the account's workspace policy."""
    if raw is None or not raw.strip():
        return None
    try:
        candidate = Path(raw.strip()).expanduser()
    except (ValueError, RuntimeError) as exc:
        raise ValueError(tr("projects.errors.invalid_path", locale)) from exc
    if not candidate.is_absolute():
        raise ValueError(tr("projects.errors.absolute_required", locale))
    path = assert_safe_host_path(
        str(candidate), restrict_to_home=False, restrict_to_root=allowed_root
    )
    if not path.is_dir():
        raise ValueError(tr("projects.errors.directory_missing", locale))
    return host_path_text(path)
