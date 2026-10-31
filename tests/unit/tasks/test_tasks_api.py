"""Thin authenticated task adapters and scoped webhook authentication."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from tests.unit.tasks.test_task_manager import setup as setup

from octop.api.deps import current_user, get_server
from octop.api.routers.tasks import hook_router, router
from octop.infra.users.identity import User


@pytest.mark.asyncio
async def test_task_api_and_typed_openapi(setup):
    e = setup
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.include_router(hook_router, prefix="/api")
    app.dependency_overrides[get_server] = lambda: SimpleNamespace(task_manager=e.manager)
    app.dependency_overrides[current_user] = lambda: User(e.uid, "owner", "admin", "Owner")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/tasks", json={"agent_id": "a", "title": "task", "prompt": "instructions"}
        )
        assert response.status_code == 201
        task = response.json()
        assert task["state"] == "queued"
        assert (await client.get("/api/tasks")).json()[0]["id"] == task["id"]
        assert (await client.get("/api/tasks/" + task["id"])).json()["prompt"] == "instructions"
        assert (
            await client.post("/api/tasks/" + task["id"] + "/actions", json={"action": "pause"})
        ).json()["state"] == "paused"
        assert (await client.put("/api/tasks/queue-controls/a", json={"paused": True})).json() == {
            "paused": True
        }
        assert (await client.get("/api/tasks/queue-controls")).json() == {"a": True}
        schema = (await client.get("/openapi.json")).json()
        assert schema["paths"]["/api/tasks"]["post"]["responses"]["201"]["content"][
            "application/json"
        ]["schema"]["$ref"].endswith("/TaskView")


@pytest.mark.asyncio
async def test_hook_bounds_request_before_json_decode(setup, monkeypatch):
    e = setup
    app = FastAPI()
    app.include_router(hook_router, prefix="/api")
    app.dependency_overrides[get_server] = lambda: SimpleNamespace(task_manager=e.manager)
    trigger = AsyncMock(return_value="run1")
    monkeypatch.setattr(e.manager, "trigger_webhook", trigger)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        accepted = await client.post(
            "/api/task-hooks/flow",
            json={"x": "data"},
            headers={"Authorization": "Bearer scoped-token", "Idempotency-Key": "one"},
        )
        assert accepted.status_code == 202
        trigger.assert_awaited_once_with(
            "flow", "scoped-token", {"x": "data"}, idempotency_key="one"
        )
        # Install the normal typed-error handler so this thin app has the production envelope contract.
        from octop.api.app import _install_exception_handlers

        _install_exception_handlers(app)
    # A fresh application avoids Starlette's already-built middleware stack.
    app2 = FastAPI()
    app2.include_router(hook_router, prefix="/api")
    app2.dependency_overrides[get_server] = app.dependency_overrides[get_server]
    _install_exception_handlers(app2)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app2), base_url="http://test"
    ) as client:
        too_large = await client.post(
            "/api/task-hooks/flow",
            content=b"x" * 32769,
            headers={"Authorization": "Bearer scoped-token"},
        )
        assert too_large.status_code == 413
        invalid = await client.post("/api/task-hooks/flow", content="[]")
        assert invalid.status_code == 400
    assert trigger.await_count == 1
