from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from tests.unit.conversations.test_conversations import GROK, make_zip, seed
from tests.unit.tasks.test_task_manager import setup as setup

from octop.api.app import _install_exception_handlers
from octop.api.deps import current_user, get_server
from octop.api.routers.conversations import router
from octop.infra.users.identity import User


@pytest.mark.asyncio
async def test_real_http_preview_confirm_and_openapi_schemas(setup):
    e = setup
    s = await seed(e)
    app = FastAPI()
    app.include_router(router, prefix="/api", tags=["Conversations"])
    _install_exception_handlers(app)
    app.dependency_overrides[current_user] = lambda: User(e.uid, "owner", "admin", None)
    app.dependency_overrides[get_server] = lambda: SimpleNamespace(
        conversation_service=s.service, conversation_transfer=s.transfer
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        preview = await client.post(
            "/api/conversation-imports/preview",
            content=make_zip({"conversations.json": GROK}),
            headers={"Content-Type": "application/zip"},
        )
        assert preview.status_code == 200
        identifier = preview.json()["id"]
        result = await client.post(
            f"/api/conversation-imports/{identifier}/confirm",
            json={"keys": ["grok-chat"], "target_agent_id": "a"},
        )
        assert result.status_code == 200 and len(result.json()["threads"]) == 1
        archived = await client.get("/api/conversations", params={"archived": "true"})
        assert (
            archived.status_code == 200
            and archived.json()["conversations"][0]["origin"]["source"] == "grok-history"
        )
        reaction = await client.post(
            f"/api/conversations/{s.thread_id}/reactions",
            json={"message": {"message_id": "answer-1"}, "emoji": "👍", "active": True},
        )
        assert (
            reaction.status_code == 200
            and reaction.json()["reactions"][0]["message_key"] == "answer-1"
        )
        schema = (await client.get("/openapi.json")).json()
        assert schema["paths"]["/api/conversation-imports/{preview_id}/confirm"]["post"][
            "requestBody"
        ]["content"]["application/json"]["schema"]["$ref"].endswith("ImportSelection")
        assert "QuotedMessage" in schema["components"]["schemas"]
        bad = await client.post(
            "/api/conversation-imports/preview", content=make_zip({"../secret": b"bad"})
        )
        assert bad.status_code == 400
