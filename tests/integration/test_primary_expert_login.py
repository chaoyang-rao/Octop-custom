"""Authenticated dashboard primary initialization uses the caller's account."""

from types import SimpleNamespace
from unittest.mock import AsyncMock


async def test_primary_initialization_is_authenticated_and_documents_result(
    env_with_provider, monkeypatch
):
    client, server, auth = env_with_provider
    registry = server.app_runtime.agent_registry
    ensure = AsyncMock(return_value=SimpleNamespace(agent_id="OWN_MAIN", name="小通"))
    monkeypatch.setattr(registry, "ensure_primary_expert", ensure)
    me = (await client.get("/api/auth/me", headers=auth)).json()
    response = await client.post("/api/agents/primary/ensure", headers=auth)
    assert response.status_code == 200, response.text
    assert response.json() == {"agent_id": "OWN_MAIN", "name": "小通"}
    ensure.assert_awaited_once_with(me["id"], locale="zh")

    ensure.reset_mock()
    denied = await client.post("/api/agents/primary/ensure")
    assert denied.status_code == 401
    ensure.assert_not_awaited()
    schema = client._octop_app.openapi()
    operation = schema["paths"]["/api/agents/primary/ensure"]["post"]
    assert operation["summary"]
    result_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert result_schema["$ref"].endswith("/PrimaryExpertResult")
