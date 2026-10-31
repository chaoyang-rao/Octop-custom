"""Integration tests for dashboard chat attachments in agent workspace."""

from __future__ import annotations

import asyncio
import re
from typing import Any


async def test_upload_and_workspace_download(env_with_agent: Any) -> None:
    client, _srv, auth, aid = env_with_agent
    files = {"file": ("note.txt", b"hello attachment", "text/plain")}
    r = await client.post(f"/api/agents/{aid}/upload", files=files, headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["path"] == body["workspace_path"]
    assert body["access_url"].startswith(f"/api/agents/{aid}/workspace/download")
    assert body["filename"] == "note.txt"
    assert body["media_type"] == "text/plain"
    assert body["workspace_path"].endswith(".txt")
    assert body["workspace_path"].startswith("inbound/")
    assert re.search(r"inbound/\d{10,}_note\.txt$", body["workspace_path"])
    assert "file_id" not in body
    assert "legacy_url" not in body

    r2 = await client.get(body["access_url"], headers=auth)
    assert r2.status_code == 200, r2.text
    assert r2.content == b"hello attachment"


async def test_upload_pdf_workspace_path(env_with_agent: Any) -> None:
    client, _srv, auth, aid = env_with_agent
    files = {"file": ("report.pdf", b"%PDF-1.4", "application/pdf")}
    r = await client.post(f"/api/agents/{aid}/upload", files=files, headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["workspace_path"].endswith(".pdf")
    assert body["filename"] == "report.pdf"

    r2 = await client.get(body["access_url"], headers=auth)
    assert r2.status_code == 200, r2.text
    assert r2.content == b"%PDF-1.4"


async def test_upload_requires_auth(env: Any) -> None:
    client, _srv, _auth = env
    files = {"file": ("note.txt", b"x", "text/plain")}
    r = await client.post("/api/agents/NOPE/upload", files=files)
    assert r.status_code == 401, r.text


async def test_uploaded_file_receipt_runs_owned_background_task(env_with_agent: Any) -> None:
    client, _srv, auth, aid = env_with_agent
    uploaded = await client.post(
        f"/api/agents/{aid}/upload",
        files={"file": ("proof.txt", b"owned upload proof", "text/plain")},
        headers=auth,
    )
    detail = await client.get(f"/api/agents/{aid}", headers=auth)
    assert uploaded.status_code == 200, {
        "upload": uploaded.text,
        "startup": detail.json().get("last_error"),
    }
    payload = uploaded.json()
    assert payload["upload_receipt"]
    created = await client.post(
        "/api/tasks",
        json={
            "agent_id": aid,
            "title": "Uploaded task",
            "prompt": "Read the attached file",
            "attachments": [
                {
                    "workspace_path": payload["workspace_path"],
                    "filename": payload["filename"],
                    "mime_type": payload["media_type"],
                    "upload_receipt": payload["upload_receipt"],
                }
            ],
        },
        headers=auth,
    )
    assert created.status_code == 201, created.text
    task_id = created.json()["task_id"]
    for _ in range(100):
        current = await client.get(f"/api/tasks/{task_id}", headers=auth)
        if current.json()["state"] in {"completed", "failed", "interrupted"}:
            break
        await asyncio.sleep(0.02)
    assert current.json()["state"] == "completed", current.text
    assert current.json()["options"]["attachments"][0]["sha256"]
