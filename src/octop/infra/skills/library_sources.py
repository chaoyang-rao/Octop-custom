"""Explicitly selected provider skill folders; no implicit host-home discovery."""

from __future__ import annotations

import asyncio
import stat
from pathlib import Path, PurePosixPath
from typing import Any

from octop.infra.errors import ErrorCode, OctopError
from octop.infra.skills.skill_packages import (
    MAX_SKILL_BYTES,
    MAX_SKILL_FILES,
    normalize_skill_files,
    read_skill_directory,
    validate_skill_slug,
)
from octop.infra.users.identity import User
from octop.infra.utils.frontmatter import parse_frontmatter

PROVIDER_ROOTS = (
    ".agents/skills",
    ".claude/skills",
    ".codex/skills",
    ".gemini/skills",
    ".opencode/skills",
    ".pi/agent/skills",
)


def _field(item: Any, key: str, default: Any = None) -> Any:
    return item.get(key, default) if isinstance(item, dict) else getattr(item, key, default)


def selected_root(value: str) -> str:
    path = PurePosixPath(value)
    if not value or "\\" in value or "\x00" in value or ".." in path.parts:
        raise OctopError(ErrorCode.FORBIDDEN, "skill_library.invalid_source")
    return value.rstrip("/")


def _private(name: str) -> bool:
    return (
        name in {".git", "auth.json", "tokens.json", "credentials.json", ".env"}
        or (name.startswith(".env.") and not name.endswith((".example", ".sample", ".template")))
        or name.endswith((".p8", ".p12", ".key"))
    )


def host_root(value: str, user: User, explicit: bool) -> Path:
    if not user.is_admin or not explicit:
        raise OctopError(ErrorCode.FORBIDDEN, "skill_library.host_admin_only")
    if not value or any(ord(char) < 32 for char in value) or "\x00" in value:
        raise OctopError(ErrorCode.FORBIDDEN, "skill_library.invalid_source")
    root = Path(value).expanduser()
    if ".." in root.parts:
        raise OctopError(ErrorCode.FORBIDDEN, "skill_library.invalid_source")
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise OctopError(ErrorCode.FORBIDDEN, "skill_library.invalid_source")
    resolved = root.resolve()
    if not any(resolved.as_posix().endswith("/" + suffix) for suffix in PROVIDER_ROOTS):
        raise OctopError(ErrorCode.FORBIDDEN, "skill_library.invalid_source")
    return resolved


def _host_files(root: Path, slug: str) -> list[tuple[str, bytes]]:
    folder = root / validate_skill_slug(slug)
    if folder.is_symlink() or not folder.is_dir():
        raise OctopError(ErrorCode.FORBIDDEN, "skill_library.invalid_source")
    # List before reading any contents. Conventional auth stores are never imported.
    pending = [folder]
    count = 0
    while pending:
        current = pending.pop()
        for item in current.iterdir():
            count += 1
            mode = item.lstat().st_mode
            if count > MAX_SKILL_FILES or _private(item.name) or stat.S_ISLNK(mode):
                raise OctopError(ErrorCode.FORBIDDEN, "skill_library.private_source")
            if stat.S_ISDIR(mode):
                pending.append(item)
            elif not stat.S_ISREG(mode):
                raise OctopError(ErrorCode.FORBIDDEN, "skill_library.invalid_source")
    return read_skill_directory(folder)


async def workspace_files(workspace: Any, root: str, slug: str) -> list[tuple[str, bytes]]:
    root = selected_root(root)
    path = PurePosixPath(root)
    if path.is_absolute() or not any(
        root == suffix or root.endswith("/" + suffix) for suffix in PROVIDER_ROOTS
    ):
        raise OctopError(ErrorCode.FORBIDDEN, "skill_library.invalid_source")
    prefix = root + "/" + validate_skill_slug(slug)
    pending = [(prefix, "")]
    files: list[tuple[str, bytes]] = []
    total = 0
    visited = 0
    while pending:
        visited += 1
        if visited > MAX_SKILL_FILES:
            raise OctopError(ErrorCode.FORBIDDEN, "skill_library.source_too_large")
        current, relative = pending.pop()
        result = await workspace.als(current)
        if result is None:
            raise OctopError(ErrorCode.NOT_FOUND, "skill_library.source_missing")
        for item in getattr(result, "entries", []) or []:
            name = str(_field(item, "path", "")).replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
            if (
                not name
                or name in {".", ".."}
                or _private(name)
                or _field(item, "is_symlink", False)
            ):
                raise OctopError(ErrorCode.FORBIDDEN, "skill_library.private_source")
            target = current + "/" + name
            rel = relative + name
            if _field(item, "is_dir", False):
                pending.append((target, rel + "/"))
            else:
                content = await workspace.adownload_bytes(target)
                if content is None:
                    raise OctopError(ErrorCode.NOT_FOUND, "skill_library.source_missing")
                files.append((rel, content))
                total += len(content)
            if len(files) + len(pending) > MAX_SKILL_FILES or total > MAX_SKILL_BYTES:
                raise OctopError(ErrorCode.FORBIDDEN, "skill_library.source_too_large")
    return list(normalize_skill_files(files))


async def discover(
    *, kind: str, root: str, user: User, explicit: bool = False, workspace: Any = None
) -> list[dict[str, str]]:
    entries: list[str] = []
    if kind == "host":
        folder = host_root(root, user, explicit)
        entries = await asyncio.to_thread(
            lambda: [p.name for p in folder.iterdir() if p.is_dir() and not p.is_symlink()][:201]
        )
    else:
        selected_root(root)
        if PurePosixPath(root).is_absolute() or not any(
            root == suffix or root.endswith("/" + suffix) for suffix in PROVIDER_ROOTS
        ):
            raise OctopError(ErrorCode.FORBIDDEN, "skill_library.invalid_source")
        result = await workspace.als(root)
        for item in getattr(result, "entries", []) or []:
            if _field(item, "is_dir", False) and not _field(item, "is_symlink", False):
                entries.append(
                    str(_field(item, "path", "")).replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
                )
    if len(entries) > 200:
        raise OctopError(ErrorCode.FORBIDDEN, "skill_library.source_too_large")
    result_rows = []
    for slug in sorted(entries):
        try:
            validate_skill_slug(slug)
            if kind == "host":
                manifest_path = folder / slug / "SKILL.md"
                if (
                    manifest_path.is_symlink()
                    or not manifest_path.is_file()
                    or manifest_path.stat().st_size > 128 * 1024
                ):
                    continue
                manifest = await asyncio.to_thread(manifest_path.read_text, encoding="utf-8")
            else:
                manifest = await workspace.aread_text(root.rstrip("/") + "/" + slug + "/SKILL.md")
            if not manifest or len(manifest) > 128 * 1024:
                continue
            metadata, _ = parse_frontmatter(manifest)
            if not metadata.get("removed"):
                result_rows.append(
                    {
                        "slug": slug,
                        "name": str(metadata.get("name") or slug)[:200],
                        "description": str(metadata.get("description") or "")[:500],
                    }
                )
        except (OSError, UnicodeError, ValueError):
            continue
    return result_rows


async def read_selected(
    *, kind: str, root: str, slug: str, user: User, explicit: bool = False, workspace: Any = None
) -> list[tuple[str, bytes]]:
    if kind == "host":
        folder = await asyncio.to_thread(host_root, root, user, explicit)
        return await asyncio.to_thread(_host_files, folder, slug)
    return await workspace_files(workspace, root, slug)
