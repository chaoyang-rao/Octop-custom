"""Real isolated metadata stores, company identities, and protocol-only runtime fakes."""

import asyncio
import json
import secrets
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from octop.config import OctopConfig
from octop.infra.auth.enterprise import record_company_identity
from octop.infra.auth.sso.crypto import encrypt_secret
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import build_shared_services
from octop.infra.enterprise_resources import node as node_module
from octop.infra.enterprise_resources.catalog import ResourceCatalog
from octop.infra.enterprise_resources.node import ResourceSync
from octop.infra.users.identity import Role, User
from octop.infra.users.manager import UserManager
from octop.infra.utils.paths import PathLayout


class Workspace:
    def __init__(self):
        self.files = {"USER.md": b"personal preferences", "memory/private.md": b"private memory"}

    async def adownload_bytes(self, path):
        return self.files.get(path)

    async def aupload_bytes(self, path, content):
        self.files[path] = content

    async def adelete(self, path):
        self.files.pop(path, None)


class Registry:
    def __init__(self, services):
        self.services = services
        self.workspaces = {}
        self.busy = set()
        self.held = set()
        self.reloads = []
        self.fail_next = False

    async def create(self, spec, *, workspace_initializer):
        self.services.agent_repo.create(
            agent_id=spec.agent_id,
            user_id=spec.user_id,
            name=spec.name,
            description=spec.description,
            config_json=json.dumps(spec.config),
            skill_package_ids=json.dumps(spec.skill_package_ids),
            mcp_servers=json.dumps(spec.mcp_servers),
        )
        workspace = self.workspaces.setdefault(spec.agent_id, Workspace())
        await workspace_initializer(None, workspace)

    def workspace_for_agent(self, agent_id):
        return self.workspaces[agent_id]

    def try_begin_runtime_update(self, agent_id):
        if agent_id in self.busy or agent_id in self.held:
            return False
        self.held.add(agent_id)
        return True

    def end_runtime_update(self, agent_id):
        self.held.remove(agent_id)

    async def reload_resource_content(self, agent_id):
        assert agent_id in self.held
        self.reloads.append(agent_id)
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("synthetic reload failure")


@pytest.fixture
def company(tmp_path, monkeypatch):
    monkeypatch.setenv("OCTOP_HOME", str(tmp_path))
    pools = []

    def server_at(name, config):
        paths = PathLayout(tmp_path / name)
        paths.ensure_root()
        pool = SqlitePool(paths.db)
        pools.append(pool)
        run_migrations(pool)
        services = build_shared_services(db=pool, paths=paths, config=config)
        services.secret_repo.get_or_create("jwt", lambda: secrets.token_bytes(32))
        return SimpleNamespace(
            services=services,
            config=config,
            paths=paths,
            user_manager=UserManager(services),
            app_runtime=None,
        )

    center = server_at("center", OctopConfig(enterprise_center_enabled=True))
    provider = center.services.sso_repo.upsert_by_kind(
        "feishu",
        enabled=True,
        display_name="Company",
        issuer="",
        client_id="company-app",
        client_secret_enc=encrypt_secret(center.services.secret_repo, "synthetic"),
        scopes="",
        dashboard_origin=None,
    )
    center.services.settings_repo.set("enterprise.tenant_key", "company-tenant")

    async def employee(name, admin=False):
        user = await center.user_manager.resolve_or_create_sso_user(
            provider_id=provider.id, subject=name, claims={"name": name}
        )
        record_company_identity(
            center.services, user.id, provider.client_id, name, "company-tenant"
        )
        if admin:
            await center.user_manager.set_role(user.username, Role.ADMIN)
            user = replace(user, role=Role.ADMIN)
        return user

    publisher, alice, bob = [
        asyncio.run(employee(n, n == "publisher")) for n in ("publisher", "alice", "bob")
    ]
    catalog = ResourceCatalog(center)
    nodes = []
    for name, remote_user in (("alice", alice), ("bob", bob)):
        server = server_at(name, OctopConfig(enterprise_authority_url="https://company.example"))
        uid = server.services.user_repo.create(
            username=name, role=Role.USER, permissions=["experts", "skills", "connector_enabled"]
        )
        user = User(
            uid, name, Role.USER, name, permissions=["experts", "skills", "connector_enabled"]
        )
        registry = Registry(server.services)
        server.app_runtime = SimpleNamespace(agent_registry=registry)
        sync = ResourceSync(server)
        server._enterprise_resources = sync
        nodes.append(
            SimpleNamespace(
                server=server, sync=sync, user=user, remote_user=remote_user, registry=registry
            )
        )

    clients = {}
    for node in nodes:

        async def fetch(_user, remote_user=node.remote_user):
            return catalog.center.require_employee(remote_user), catalog.member(
                remote_user
            ).model_dump(mode="json")

        async def bundle(_user, content_digest, remote_user=node.remote_user):
            return catalog.bundle(remote_user, content_digest).model_dump(mode="json")

        clients[id(node.server)] = SimpleNamespace(
            fetch_resource_catalog=AsyncMock(side_effect=fetch),
            fetch_resource_bundle=AsyncMock(side_effect=bundle),
            authorize=AsyncMock(),
        )
    monkeypatch.setattr(node_module, "client_for", lambda server: clients[id(server)])
    yield SimpleNamespace(
        center=center,
        catalog=catalog,
        admin=publisher,
        alice=alice,
        bob=bob,
        nodes=nodes,
        clients=clients,
    )
    for pool in pools:
        pool.close()
