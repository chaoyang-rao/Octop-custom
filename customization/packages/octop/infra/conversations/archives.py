"""Bounded ZIP readers and public user-data formats; never extract or execute."""

from __future__ import annotations

import io
import json
import re
import stat
import unicodedata
import zipfile
import zlib
from dataclasses import dataclass
from lzma import LZMAError
from pathlib import PurePosixPath
from typing import Any, Literal, cast

from octop.infra.conversations.models import PortableConversation, PortableMessage

MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
MAX_ENTRY_BYTES = 32 * 1024 * 1024
MAX_ARCHIVE_FILES = 5000
MAX_MESSAGES = 50000


class ConversationArchiveError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def safe_archive_path(raw: str) -> str:
    name = raw.rstrip("/")
    path = PurePosixPath(name)
    if (
        not name
        or len(name) > 1000
        or len(path.parts) > 64
        or path.is_absolute()
        or str(path) != name
        or any(part in {".", "..", ""} for part in name.split("/"))
        or any(ord(ch) < 32 or ch in "\\:" for ch in name)
        or any(part.rstrip(". ") != part for part in path.parts)
    ):
        raise ConversationArchiveError("unsafe_archive")
    return name


def read_zip(data: bytes) -> dict[str, bytes]:
    if not data or len(data) > MAX_ARCHIVE_BYTES:
        raise ConversationArchiveError("archive_limit")
    result: dict[str, bytes] = {}
    seen: set[str] = set()
    total = 0
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_ARCHIVE_FILES:
                raise ConversationArchiveError("archive_limit")
            for info in entries:
                if info.orig_filename != info.filename:
                    raise ConversationArchiveError("unsafe_archive")
                path = safe_archive_path(info.filename)
                normalized = unicodedata.normalize("NFC", path).casefold()
                if normalized in seen:
                    raise ConversationArchiveError("unsafe_archive")
                seen.add(normalized)
                mode = (info.external_attr >> 16) & 0o170000
                if mode not in {0, stat.S_IFREG, stat.S_IFDIR} or info.flag_bits & 1:
                    raise ConversationArchiveError("unsafe_archive")
                if info.is_dir():
                    continue
                if (
                    info.file_size > MAX_ENTRY_BYTES
                    or info.file_size > max(1, info.compress_size) * 200
                ):
                    raise ConversationArchiveError("archive_limit")
                with archive.open(info) as stream:
                    parts = []
                    size = 0
                    while chunk := stream.read(min(1024 * 1024, MAX_ENTRY_BYTES - size + 1)):
                        size += len(chunk)
                        total += len(chunk)
                        if size > MAX_ENTRY_BYTES or total > MAX_ARCHIVE_BYTES:
                            raise ConversationArchiveError("archive_limit")
                        parts.append(chunk)
                result[path] = b"".join(parts)
            file_keys = {unicodedata.normalize("NFC", path).casefold() for path in result}
            for path in result:
                if any(
                    unicodedata.normalize("NFC", str(parent)).casefold() in file_keys
                    for parent in PurePosixPath(path).parents
                    if str(parent) != "."
                ):
                    raise ConversationArchiveError("unsafe_archive")
    except (
        zipfile.BadZipFile,
        OSError,
        RuntimeError,
        NotImplementedError,
        EOFError,
        zlib.error,
        LZMAError,
    ):
        raise ConversationArchiveError("invalid_archive") from None
    return result


def json_document(data: bytes) -> Any:
    try:
        return json.loads(data.decode("utf-8-sig"))
    except (ValueError, UnicodeError, RecursionError):
        raise ConversationArchiveError("invalid_archive") from None


@dataclass(frozen=True)
class HistoryImport:
    conversations: list[PortableConversation]
    omitted_messages: int
    ignored_files: int


def grok_history(files: dict[str, bytes]) -> HistoryImport:
    """Recognize account-export conversation rows, without interpreting other account data."""
    candidates = [
        name
        for name in files
        if PurePosixPath(name).name in {"prod-grok-backend.json", "conversations.json"}
    ]
    if len(candidates) != 1:
        raise ConversationArchiveError("unsupported_format")
    document = json_document(files[candidates[0]])
    rows: Any = document
    if isinstance(document, dict):
        rows = document.get("conversations")
        if rows is None and isinstance(document.get("data"), dict):
            rows = document["data"].get("conversations")
    if not isinstance(rows, list) or len(rows) > 5000:
        raise ConversationArchiveError("unsupported_format")
    conversations = []
    omitted = 0
    count = 0
    seen: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ConversationArchiveError("unsupported_format")
        meta: dict[str, Any] = (
            row["conversation"] if isinstance(row.get("conversation"), dict) else row
        )
        external = str(meta.get("id") or meta.get("conversationId") or f"conversation-{index}")
        if external in seen or len(external) > 300:
            raise ConversationArchiveError("unsupported_format")
        seen.add(external)
        messages = row.get(
            "responses", row.get("messages", meta.get("responses", meta.get("messages", [])))
        )
        if not isinstance(messages, list):
            raise ConversationArchiveError("unsupported_format")
        normalized = []
        for raw in messages:
            count += 1
            if count > MAX_MESSAGES:
                raise ConversationArchiveError("archive_limit")
            item = raw.get("response", raw) if isinstance(raw, dict) else {}
            if not isinstance(item, dict):
                omitted += 1
                continue
            role = str(item.get("sender") or item.get("role") or "").casefold()
            role = {
                "human": "user",
                "grok": "assistant",
                "bot": "assistant",
                "ai": "assistant",
            }.get(role, role)
            content = item.get("message", item.get("text", item.get("content", "")))
            if isinstance(content, list):
                content = "\n".join(
                    block["text"]
                    for block in content
                    if isinstance(block, dict)
                    and block.get("type") == "text"
                    and isinstance(block.get("text"), str)
                )
            if (
                role not in {"user", "assistant"}
                or not isinstance(content, str)
                or not content.strip()
            ):
                omitted += 1
                continue
            if len(content) > 128000:
                raise ConversationArchiveError("archive_limit")
            # Deliberately discard system, tool_calls, attachments, metadata and permissions.
            normalized.append(
                PortableMessage(
                    role=cast(Literal["user", "assistant"], role),
                    content=content,
                    external_id=str(item.get("id") or item.get("responseId") or "")[:300] or None,
                )
            )
        conversations.append(
            PortableConversation(
                external_id=external,
                title=str(meta.get("title") or meta.get("name") or external)[:300],
                messages=normalized,
            )
        )
    return HistoryImport(conversations, omitted, len(files) - 1)


_DENIED_PARTS = {
    ".octop",
    ".octop-auth",
    ".openbot",
    ".git",
    "node_modules",
    "__pycache__",
    "auth",
    "credentials",
    "sessions",
}
_DENIED_SUFFIXES = {".key", ".pem", ".p12", ".pfx", ".sqlite", ".db", ".zip", ".tar", ".gz", ".7z"}


def portable_workspace_path(path: str) -> bool:
    safe = PurePosixPath(safe_archive_path(path))
    return not (
        any(
            part.casefold() in _DENIED_PARTS
            or part.startswith(".")
            or part.casefold().startswith("id_rsa")
            for part in safe.parts
        )
        or safe.suffix.casefold() in _DENIED_SUFFIXES
        or safe.name.casefold().startswith(("credentials", "token", "secrets", "private-key"))
    )


def redact_config_text(text: str) -> str:
    """Remove recognizable inline credential values from exported configuration text."""
    text = re.sub(
        r"(?i)\b(?:sk-[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9._~+/-]{12,})", "[REDACTED]", text
    )
    return re.sub(
        r"(?im)((?:api[_-]?key|access[_-]?token|password|client[_-]?secret|authorization)\s*[:=]\s*)[^\s,;]+",
        r"\1[REDACTED]",
        text,
    )
