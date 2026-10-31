"""Immutable skill snapshots in application storage, shared by all package editors."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

from octop.infra.skills.skill_packages import normalize_skill_files, validate_skill_slug
from octop.infra.utils.ulid import new_ulid

_LOCKS: dict[str, threading.RLock] = {}
_LOCK_GUARD = threading.Lock()


def library_lock(root: Path, package_id: str, slug: str) -> threading.RLock:
    key = str(root.resolve()) + ":" + package_id + ":" + slug
    with _LOCK_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


def files_digest(files: list[tuple[str, bytes]]) -> str:
    digest = hashlib.sha256()
    for name, data in sorted(files):
        encoded = name.encode()
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


class RevisionArchive:
    def __init__(self, root: Path) -> None:
        self.root = root / ".skill-library"

    def _folder(self, namespace: str, slug: str) -> Path:
        # Hash namespace avoids interpreting public ids / host paths as directories.
        return (
            self.root / hashlib.sha256(namespace.encode()).hexdigest() / validate_skill_slug(slug)
        )

    def put(
        self,
        namespace: str,
        slug: str,
        files: list[tuple[str, bytes]],
        *,
        source: str = "snapshot",
        actor: str = "",
    ) -> str:
        normalized = list(normalize_skill_files(files)) if files else []
        revision = files_digest(normalized)
        folder = self._folder(namespace, slug)
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / (revision + ".json")
        record = {
            "revision": revision,
            "created_at": int(time.time()),
            "source": source[:200],
            "actor": actor[:100],
            "files": [[name, base64.b64encode(data).decode()] for name, data in normalized],
        }
        with library_lock(self.root, namespace, slug):
            if not target.exists():
                temporary = folder / (new_ulid() + ".tmp")
                try:
                    with temporary.open("x", encoding="utf-8") as stream:
                        json.dump(record, stream, ensure_ascii=False)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temporary, target)
                finally:
                    temporary.unlink(missing_ok=True)
        return revision

    def get(self, namespace: str, slug: str, revision: str) -> list[tuple[str, bytes]]:
        if not re.fullmatch(r"[a-f0-9]{64}", revision):
            raise ValueError("invalid revision")
        record = json.loads(
            (self._folder(namespace, slug) / (revision + ".json")).read_text(encoding="utf-8")
        )
        files = [(name, base64.b64decode(data, validate=True)) for name, data in record["files"]]
        normalized = list(normalize_skill_files(files)) if files else []
        if files_digest(normalized) != revision:
            raise ValueError("corrupt revision")
        return normalized

    def history(self, namespace: str, slug: str) -> list[dict[str, Any]]:
        folder = self._folder(namespace, slug)
        if not folder.exists():
            return []
        result = []
        for path in folder.glob("*.json"):
            record = json.loads(path.read_text(encoding="utf-8"))
            result.append(
                {key: record[key] for key in ("revision", "created_at", "source", "actor")}
            )
        return sorted(result, key=lambda row: (row["created_at"], row["revision"]), reverse=True)


def archive_package_write(
    root: Path, package_id: str, slug: str, files: list[tuple[str, bytes]]
) -> str:
    return RevisionArchive(root).put("package:" + package_id, slug, files, source="package-editor")


def new_plan_id() -> str:
    return new_ulid()
