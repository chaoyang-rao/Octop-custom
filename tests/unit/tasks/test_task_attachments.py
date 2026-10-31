"""Only owned uploaded inbound references become standard API/native multimodal content."""

from __future__ import annotations

import base64
import json

import pytest
from deepagents.backends.filesystem import FilesystemBackend
from langchain_core.messages import HumanMessage
from octop_harness.backends.workspace import BackendWorkspace
from tests.unit.tasks.test_task_manager import settled
from tests.unit.tasks.test_task_manager import setup as setup

from octop.infra.agents.native_cli.media import native_attachment_content
from octop.infra.agents.native_cli.model import NativeACPChatModel
from octop.infra.errors import OctopError
from octop.infra.gateway.media.ingress import AgentBackedMediaBackend
from octop.infra.gateway.process.harness_request import build_content_from_message
from octop.infra.tasks.attachments import issue_upload_receipt
from octop.infra.tasks.models import TaskAttachment, TaskCreate

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j9eQAAAAASUVORK5CYII="
)


async def uploads(e, tmp_path):
    workspace = BackendWorkspace(FilesystemBackend(root_dir=tmp_path, virtual_mode=True), tmp_path)
    await workspace.aupload_bytes("inbound/photo.png", PNG)
    await workspace.aupload_bytes("inbound/note.txt", b"attachment proof")
    e.agents.workspace_for_agent = lambda aid: workspace if aid == "a" else None
    e.receipts = {}
    for path, data, mime in [
        ("inbound/photo.png", PNG, "image/png"),
        ("inbound/note.txt", b"attachment proof", "text/plain"),
    ]:
        e.receipts[path] = await issue_upload_receipt(
            e.repos,
            user_id=e.uid,
            agent_id="a",
            workspace_path=path,
            filename=path.split("/")[-1],
            mime_type=mime,
            data=data,
        )
    return workspace


@pytest.mark.asyncio
async def test_uploaded_picture_and_document_flow_to_api_and_native_content(setup, tmp_path):
    e = setup
    workspace = await uploads(e, tmp_path)
    await e.channels.start()
    try:
        task = await e.manager.enqueue(
            e.uid,
            TaskCreate(
                agent_id="a",
                title="media",
                prompt="read uploaded files",
                attachments=[
                    TaskAttachment(
                        workspace_path="inbound/photo.png",
                        filename="photo.png",
                        mime_type="image/png",
                        size=len(PNG),
                        upload_receipt=e.receipts["inbound/photo.png"],
                    ),
                    TaskAttachment(
                        workspace_path="inbound/note.txt",
                        filename="note.txt",
                        mime_type="text/plain",
                        size=16,
                        upload_receipt=e.receipts["inbound/note.txt"],
                    ),
                ],
            ),
        )
        saved = json.loads(e.repos.task_repo.get(task.id).options_json)
        assert len(saved["attachments"]) == 2 and len(saved["attachments"][0]["sha256"]) == 64
        await e.manager.process_once()
        await settled(e.manager)
        assert e.repos.task_repo.get(task.id).state == "completed"
        message = e.processor.received[-1]
        assert len(message.content) == 3
        blocks = await build_content_from_message(
            message, media_backend=AgentBackedMediaBackend(workspace), locale="en"
        )
        assert isinstance(blocks, list) and any(
            block.get("type") == "image_url" for block in blocks
        )
        native_blocks = await native_attachment_content(
            message, blocks, AgentBackedMediaBackend(workspace)
        )
        projected = NativeACPChatModel._prompt(
            [HumanMessage(content=native_blocks)],
            {"image": True, "audio": True, "embedded_context": True},
        )
        assert any(block.type == "image" and block.data for block in projected)
        assert "inbound/note.txt" in json.dumps(blocks)
    finally:
        await e.manager.stop()
        await e.channels.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/tmp/private.png",
        "https://host.example/photo.png",
        "inbound/../token",
        "inbound/nested/../../token",
        "inbound/%2e%2e/token",
        "inbound\\token",
        "outbound/photo.png",
    ],
)
async def test_host_remote_and_traversal_references_are_rejected(setup, tmp_path, path):
    e = setup
    await uploads(e, tmp_path)
    with pytest.raises(OctopError) as error:
        await e.manager.enqueue(
            e.uid,
            TaskCreate(
                agent_id="a",
                title="bad",
                prompt="bad",
                attachments=[TaskAttachment(workspace_path=path)],
            ),
        )
    assert error.value.details["task_reason"] == "attachment_invalid"
    assert e.repos.task_repo.list(e.uid) == []


@pytest.mark.asyncio
async def test_queued_attachment_replacement_is_rejected_before_model_work(setup, tmp_path):
    e = setup
    workspace = await uploads(e, tmp_path)
    await e.channels.start()
    try:
        task = await e.manager.enqueue(
            e.uid,
            TaskCreate(
                agent_id="a",
                title="changed",
                prompt="changed",
                attachments=[
                    TaskAttachment(
                        workspace_path="inbound/note.txt",
                        mime_type="text/plain",
                        upload_receipt=e.receipts["inbound/note.txt"],
                    )
                ],
            ),
        )
        await workspace.aupload_bytes("inbound/note.txt", b"a different file")
        await e.manager.process_once()
        await settled(e.manager)
        assert e.repos.task_repo.get(task.id).state == "failed"
        assert e.processor.received == []
    finally:
        await e.manager.stop()
        await e.channels.stop()


@pytest.mark.asyncio
async def test_stale_widget_attempt_cannot_cancel_retried_task(setup):
    e = setup
    task = await e.manager.enqueue(e.uid, TaskCreate(agent_id="a", title="widget", prompt="widget"))
    assert e.repos.task_repo.claim(task.id)
    e.repos.task_repo.transition(
        task.id, expected={"running"}, state="interrupted", action="interrupted"
    )
    await e.manager.action(e.uid, task.id, "retry")
    assert e.repos.task_repo.claim(task.id)
    with pytest.raises(OctopError) as stale:
        await e.manager.action(e.uid, task.id, "cancel", expected_attempt=1)
    assert stale.value.status == 409 and e.repos.task_repo.get(task.id).state == "running"
    await e.manager.action(e.uid, task.id, "cancel", expected_attempt=2)
    assert e.repos.task_repo.get(task.id).state == "cancelled"


@pytest.mark.asyncio
async def test_upload_receipt_is_required_and_scoped_before_workspace_read(setup, tmp_path):
    from unittest.mock import AsyncMock

    e = setup
    workspace = await uploads(e, tmp_path)
    workspace.adownload_bytes = AsyncMock(side_effect=AssertionError("unauthorized content read"))
    for agent_id, token in [
        ("a", None),
        ("a", "fabricated-token"),
        ("b", e.receipts["inbound/note.txt"]),
    ]:
        with pytest.raises(OctopError) as error:
            await e.manager.enqueue(
                e.uid,
                TaskCreate(
                    agent_id=agent_id,
                    title="scope",
                    prompt="scope",
                    attachments=[
                        TaskAttachment(workspace_path="inbound/note.txt", upload_receipt=token)
                    ],
                ),
            )
        assert error.value.details["task_reason"] == "attachment_receipt"
    assert workspace.adownload_bytes.await_count == 0
