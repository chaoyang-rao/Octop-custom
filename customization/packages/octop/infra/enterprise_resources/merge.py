"""Conservative three-way content merge, with explicit conflict decisions."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal


def content_hash(value: bytes | None) -> str | None:
    return hashlib.sha256(value).hexdigest() if value is not None else None


@dataclass(frozen=True)
class MergeConflict:
    path: str
    base: bytes | None
    local: bytes | None
    remote: bytes | None


def merge_files(
    base: dict[str, bytes],
    local: dict[str, bytes],
    remote: dict[str, bytes],
    decisions: dict[str, Literal["local", "remote"]] | None = None,
) -> tuple[dict[str, bytes], list[MergeConflict]]:
    """Keep disjoint local changes. A resource with conflicts is not partially applied."""
    result: dict[str, bytes] = {}
    conflicts: list[MergeConflict] = []
    for path in sorted(set(base) | set(local) | set(remote)):
        original, current, incoming = base.get(path), local.get(path), remote.get(path)
        if current in (original, incoming):
            value = incoming
        elif incoming == original:
            value = current
        elif decisions and path in decisions:
            value = current if decisions[path] == "local" else incoming
        else:
            conflicts.append(MergeConflict(path, original, current, incoming))
            value = current
        if value is not None:
            result[path] = value
    return result, conflicts
