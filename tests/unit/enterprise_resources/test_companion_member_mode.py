from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from octop.api.deps import current_user, get_server
from octop.api.routers import companion as api_module
from octop.infra.enterprise_resources import companion as module
from octop.infra.errors import ErrorCode, OctopError


async def test_member_enabled_pet_can_use_owned_experts_without_a_separate_expert_opening_step(
    company, monkeypatch
):
    node = company.nodes[0]
    status = {"configured": True, "companion": True, "mcp_ids": []}
    client = SimpleNamespace(
        authorize=AsyncMock(return_value=node.user), cached_member_access=lambda uid: status
    )
    monkeypatch.setattr(module, "client_for", lambda server: client)
    resources = SimpleNamespace(
        status=lambda user: {
            "resources": [
                {"kind": "expert", "target_id": "managed-disabled", "enabled": False},
                {"kind": "expert", "target_id": "managed-enabled", "enabled": True},
            ]
        }
    )
    monkeypatch.setattr(module, "resources_for", lambda server: resources)
    for agent_id in ["local-owned", "managed-enabled", "managed-disabled"]:
        node.server.services.agent_repo.create(
            agent_id=agent_id, user_id=node.user.id, name=agent_id
        )
    allowed = await module.allowed_companion_agents(node.server, node.user)
    assert {"local-owned", "managed-enabled"} <= allowed and "managed-disabled" not in allowed
    assert any(call.kwargs.get("force") is True for call in client.authorize.await_args_list)
    status["companion"] = False
    with pytest.raises(OctopError) as failure:
        await module.allowed_companion_agents(node.server, node.user)
    assert failure.value.code == ErrorCode.COMPANION_ACCESS_DENIED
    assert node.server.services.agent_repo.get("local-owned") is not None


@pytest.mark.parametrize(
    "peer,host,headers",
    [
        ("8.8.8.8", "127.0.0.1", {}),
        ("127.0.0.1", "public.example", {}),
        ("127.0.0.1", "127.0.0.1", {"X-Forwarded-For": "8.8.8.8"}),
    ],
)
async def test_remote_or_proxied_requests_cannot_execute_local_pet_install_or_launch(
    company, monkeypatch, peer, host, headers
):
    node = company.nodes[0]
    launch = AsyncMock(return_value={"opened": True})
    monkeypatch.setattr(api_module, "launcher_for", lambda server: SimpleNamespace(launch=launch))
    app = FastAPI()
    app.include_router(api_module.router, prefix="/api")
    app.dependency_overrides[get_server] = lambda: node.server
    app.dependency_overrides[current_user] = lambda: node.user

    @app.exception_handler(OctopError)
    async def error(request, exc):
        return JSONResponse(exc.to_envelope(), status_code=exc.status)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=(peer, 12345)), base_url="http://" + host
    ) as client:
        result = await client.post(
            "/api/companion/launch", json={"action": "open"}, headers=headers
        )
        assert result.status_code == 403
    launch.assert_not_called()
