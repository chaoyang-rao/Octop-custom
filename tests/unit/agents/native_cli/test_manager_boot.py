"""Native experts and their hosted teams boot without API credentials."""

from __future__ import annotations

import json

import pytest

from octop.config import OctopConfig
from octop.infra.agents.manager import AgentManager
from octop.infra.agents.native_cli.factory import NativeRoutingFactory
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import build_shared_services
from octop.infra.utils.paths import PathLayout


@pytest.mark.asyncio
async def test_real_harness_boots_native_expert_and_team_without_api_key(tmp_path, monkeypatch):
    monkeypatch.setenv("OCTOP_HOME", str(tmp_path))
    paths = PathLayout(tmp_path)
    pool = SqlitePool(paths.db)
    run_migrations(pool)
    services = build_shared_services(db=pool, paths=paths, config=OctopConfig())
    owner = services.user_repo.create(username="owner", role="admin")
    config = {
        "native_cli": {"enabled": True, "runner": "fake"},
        "memory": {"memory_enabled": False},
    }
    services.agent_repo.create(
        agent_id="primary", user_id=owner, name="小通", config_json=json.dumps(config)
    )
    services.agent_repo.create(
        agent_id="room",
        user_id=owner,
        name="Room",
        kind="team",
        config_json=json.dumps(
            {"memory": {"memory_enabled": False}, "team": {"member_ids": ["primary"]}}
        ),
    )
    manager = AgentManager(repos=services.repos, paths=paths, config=services.config)
    try:
        await manager.boot()
        assert not manager.providers.has_usable_providers()
        assert isinstance(manager.harness_manager.shared_factory, NativeRoutingFactory)
        primary = manager.get_agent("primary")
        assert primary.config.default_model == "native_cli_primary/session"
        assert primary.config.providers[0].api_key == ""
        assert primary.config.providers[0].base_url == "native-cli://local"
        assert manager.get_row("primary").last_state == "running"
        assert manager.get_row("room").last_state == "running"
        assert manager.native_execution_ref("room") == "native_cli_primary/session"
        # Bootstrap compiles but starts no CLI process or model prompt.
        assert manager.native_cli.sessions == {}
    finally:
        await manager.shutdown()
