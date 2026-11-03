"""Persist an out-of-turn assistant message without invoking a model.

The caller must hold the principal agent's history-backfill reservation. A
stable message id makes a checkpoint/archive write recoverable after a crash.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from langchain_core.messages import BaseMessage, message_to_dict, messages_from_dict

from octop.infra.db.repos.thread_messages import ThreadMessageRepo
from octop.infra.history.projection import message_inputs
from octop.infra.history.service import HistoryArchive


class ExternalHistoryBusy(RuntimeError):
    """The origin must finish its existing turn before delivery is retried."""


def _message_id(value: Any) -> str:
    if isinstance(value, dict):
        data = value.get("data", value)
        return str(data.get("id") or "") if isinstance(data, dict) else ""
    return str(getattr(value, "id", "") or "")


async def append_external_message(
    *,
    archive: HistoryArchive | None,
    harness: Any,
    agent_id: str,
    thread_id: str,
    message: BaseMessage,
    projection: ThreadMessageRepo,
    before_write: Callable[[], Awaitable[None]],
) -> None:
    await append_external_messages(
        archive=archive,
        harness=harness,
        agent_id=agent_id,
        thread_id=thread_id,
        messages=[message],
        projection=projection,
        before_write=before_write,
    )


async def append_external_messages(
    *,
    archive: HistoryArchive | None,
    harness: Any,
    agent_id: str,
    thread_id: str,
    messages: Sequence[BaseMessage],
    projection: ThreadMessageRepo,
    before_write: Callable[[], Awaitable[None]],
) -> None:
    """Append one complete message batch, keeping tool calls and replies together."""
    if not messages:
        return
    if any(not item.id for item in messages) or len({item.id for item in messages}) != len(
        messages
    ):
        raise ValueError("External messages require distinct stable ids")
    state = await harness.graph.aget_state({"configurable": {"thread_id": thread_id}})
    if getattr(state, "next", ()) or any(
        getattr(task, "interrupts", ()) for task in (getattr(state, "tasks", ()) or ())
    ):
        raise ExternalHistoryBusy("The origin checkpoint has unfinished work")
    current = list((getattr(state, "values", None) or {}).get("messages") or [])
    existing = {_message_id(item): item for item in current}
    for message in messages:
        item = existing.get(str(message.id))
        if item is not None:
            actual = item.get("type") if isinstance(item, dict) else item.type
            if actual != message.type:
                raise ValueError("External history message id belongs to another role")
    segments = await asyncio.to_thread(archive.store.segments, thread_id) if archive else []
    if segments and segments[0]["agent_id"] != agent_id:
        raise ValueError("History belongs to another agent")

    # A later model turn may have compacted this message out of its checkpoint.
    # The archive remains authoritative, so do not append it a second time.
    stored_messages: dict[str, BaseMessage] = {}
    if archive is not None and segments:
        documents = await asyncio.to_thread(archive.store.documents, thread_id, "message")
        requested = {item.id: item for item in messages}
        finished = set()
        for document in documents:
            identifier = _message_id(document["value"])
            if identifier not in requested:
                continue
            if document["value"].get("type") != requested[identifier].type:
                raise ValueError("External history message id belongs to another role")
            stored_messages[identifier] = messages_from_dict([document["value"]])[0]
            if document["status"] in {"active", "interrupted"}:
                finished.add(document["turn_id"])
        if len(stored_messages) == len(messages):
            await before_write()
            await asyncio.to_thread(
                projection.append_if_ready,
                thread_id,
                message_inputs([stored_messages[str(item.id)] for item in messages]),
            )
            for turn_id in finished:
                await asyncio.to_thread(archive.finish, turn_id, "completed")
            return

    anchor = None
    if archive is not None and archive.enabled and not segments:
        status = await asyncio.to_thread(projection.projection_status, thread_id)
        if status != "ready":
            config = getattr(state, "config", None)
            if config and config.get("configurable", {}).get("checkpoint_id"):
                anchor = {"checkpoint_config": config}
            elif current:
                raise ValueError("Cannot pin the origin's existing history")

    await before_write()
    turn = (
        await asyncio.to_thread(archive.begin, agent_id, thread_id, anchor=anchor)
        if archive is not None
        else None
    )
    try:
        missing = [
            item for item in messages if item.id not in existing and item.id not in stored_messages
        ]
        if missing:
            appended = await harness.aappend_messages(thread_id, missing)
            existing.update({_message_id(item): item for item in appended})
        canonical = []
        for message in messages:
            item = stored_messages.get(str(message.id)) or existing.get(str(message.id)) or message
            if isinstance(item, dict):
                item = messages_from_dict([item])[0]
            if item.type != message.type:
                raise ValueError("External history message id belongs to another role")
            canonical.append(item)
        if archive is not None and turn is not None and turn["format"] == "v2":
            await asyncio.to_thread(
                archive.save_messages,
                turn,
                [message_to_dict(item) for item in canonical if item.id not in stored_messages],
            )
        await asyncio.to_thread(projection.append_if_ready, thread_id, message_inputs(canonical))
        if archive is not None and turn is not None:
            await asyncio.to_thread(archive.finish, turn["id"], "completed")
    except BaseException:
        if archive is not None and turn is not None:
            await asyncio.to_thread(archive.finish, turn["id"], "interrupted")
        raise
