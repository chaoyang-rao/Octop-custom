"""Isolated node synchronization: personal data, task boundaries, and actor grants."""

import asyncio
from functools import partial
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from octop.config import OctopConfig
from octop.infra.agents.manager import AgentManager
from octop.infra.connectors import enterprise_mcp_sync as sync_module
from octop.infra.connectors.accounts.actor import authenticated_vault_actor
from octop.infra.connectors.enterprise_catalog import build_snapshot, entry_fingerprint
from octop.infra.connectors.enterprise_mcp_sync import EnterpriseMcpSync
from octop.infra.connectors.mcp_tool_cache import wrap_tools_for_shared_use
from octop.infra.connectors.service import ConnectorService
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import build_shared_services
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.users.identity import Role, User
from octop.infra.utils.paths import PathLayout


class FakeRegistry:
    def __init__(self):
        self.busy = set()
        self.held = set()
        self.reloads = []
        self.invalidations = []
        self.fail_next = False

    def try_begin_runtime_update(self, agent_id):
        if agent_id in self.busy or agent_id in self.held:
            return False
        self.held.add(agent_id)
        return True

    def end_runtime_update(self, agent_id):
        self.held.remove(agent_id)

    def invalidate_mcp_tool_cache(self, user_id, *, server_names=None):
        self.invalidations.append(
            (user_id, frozenset(server_names) if server_names is not None else None)
        )

    async def reload_connectors(self, agent_id, *, connector_user_id):
        self.reloads.append((agent_id, connector_user_id))
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("synthetic runtime failure")


def definition(entry_id="quality", **changes):
    return {
        "entry_id": entry_id,
        "display_name": entry_id,
        "description": "Company tools",
        "url": "https://quality.example/mcp",
        "auth_kind": "bearer",
        "enabled": True,
        "allowed_subjects": [],
        **changes,
    }


def snapshot(entries=None, revision=1):
    return build_snapshot(
        revision=revision,
        published_at=revision,
        entries=entries if entries is not None else [definition()],
    ).model_dump(mode="json")


@pytest.fixture
def node(tmp_path, monkeypatch):
    monkeypatch.setenv("OCTOP_HOME", str(tmp_path))
    paths = PathLayout(tmp_path)
    paths.ensure_root()
    pool = SqlitePool(paths.db)
    run_migrations(pool)
    config = OctopConfig(enterprise_authority_url="https://company.example")
    services = build_shared_services(db=pool, paths=paths, config=config)
    users = []
    for name in ("alice", "bob"):
        user_id = services.user_repo.create(
            username=name, role=Role.USER, permissions=["connector_enabled"]
        )
        users.append(User(user_id, name, Role.USER, name, permissions=["connector_enabled"]))
        services.agent_repo.create(agent_id=name + "-expert", user_id=user_id, name=name)
    services.agent_repo.create(agent_id="shared-expert", user_id=None, name="Shared")
    registry = FakeRegistry()
    users_by_id = {user.id: user for user in users}
    server = SimpleNamespace(
        services=services,
        config=config,
        paths=paths,
        app_runtime=SimpleNamespace(agent_registry=registry),
        user_manager=SimpleNamespace(get_by_id=users_by_id.get),
    )
    remote = {user.id: snapshot() for user in users}

    async def fetch(user):
        return "member-" + str(user.id), remote[user.id]

    client = SimpleNamespace(fetch_mcp_catalog=AsyncMock(side_effect=fetch))
    monkeypatch.setattr(sync_module, "client_for", lambda _: client)
    probe = AsyncMock(return_value={"ok": True, "tools": []})
    monkeypatch.setattr(sync_module, "probe_custom_mcp_server", probe)
    sync = EnterpriseMcpSync(server)
    server._enterprise_mcp_sync = sync
    connector = ConnectorService(
        repo=services.connector_repo,
        secret_repo=services.secret_repo,
        settings_repo=services.settings_repo,
        config=config,
    )
    yield SimpleNamespace(
        server=server,
        services=services,
        registry=registry,
        users=users,
        alice=users[0],
        bob=users[1],
        remote=remote,
        client=client,
        probe=probe,
        sync=sync,
        store=sync.store,
        connector=connector,
    )
    pool.close()


async def authorize(node, user=None, token="alice-private-token", entry=None):
    user = user or node.alice
    parsed = definition() if entry is None else entry
    return await node.sync.save_credentials(
        user, parsed["entry_id"], {"token": token}, entry_fingerprint(parsed)
    )


async def test_personal_mcp_ciphertext_survives_company_sync_and_authorization(node):
    node.connector.put_custom_servers(
        node.alice.id,
        {
            "personal-local": {
                "transport": "stdio",
                "command": "synthetic-personal-command",
                "env": {"API_KEY": "personal-secret"},
            }
        },
    )
    before = node.services.connector_repo.get_by_user_kind(
        node.alice.id, "custom-mcp"
    ).credential_blob
    await authorize(node)
    after = node.services.connector_repo.get_by_user_kind(
        node.alice.id, "custom-mcp"
    ).credential_blob
    assert before == after
    assert (
        node.connector.get_custom_servers(node.alice.id)["personal-local"]["env"]["API_KEY"]
        == "personal-secret"
    )
    assert "personal-local" in node.connector.custom_harness_configs(node.alice.id)
    company_name = node.store.server_name("quality", user_id=node.alice.id)
    assert company_name in node.connector.custom_harness_configs(node.alice.id)


async def test_member_credentials_and_names_are_separate_and_encrypted(node):
    await authorize(node, node.alice, "alice-private-token")
    await authorize(node, node.bob, "bob-private-token")
    names = [node.store.server_name("quality", user_id=user.id) for user in node.users]
    assert names[0] != names[1]
    for user, token in [(node.alice, "alice-private-token"), (node.bob, "bob-private-token")]:
        state = node.store.state(user.id)
        reference = state["desired_auth"]["quality"]
        blob = node.services.secret_repo.get(reference["key"])
        assert token.encode() not in blob
        assert token not in node.services.settings_repo.get(node.store._key(user.id))
        assert node.store.harness_configs(user.id)[
            node.store.server_name("quality", user_id=user.id)
        ]["headers"] == {"Authorization": "Bearer " + token}
    assert (
        node.store.state(node.alice.id)["desired_auth"]
        != node.store.state(node.bob.id)["desired_auth"]
    )


async def test_cached_shared_expert_tools_cannot_borrow_another_actor(node):
    await authorize(node)
    name = node.store.server_name("quality", user_id=node.alice.id)
    fingerprint = node.store.runtime_binding(node.alice.id, "quality")
    with pytest.raises(OctopError):
        await node.sync.check_call(node.alice.id, name, fingerprint)
    for actor in (None, node.bob.id):
        with authenticated_vault_actor(actor), pytest.raises(OctopError) as failure:
            await node.sync.check_call(node.alice.id, name, fingerprint)
        assert failure.value.code == ErrorCode.ENTERPRISE_ACCESS_DENIED
    with authenticated_vault_actor(node.alice.id):
        await node.sync.check_call(node.alice.id, name, fingerprint)


async def test_busy_expert_defers_change_and_releases_partial_reservations(node):
    node.remote[node.alice.id] = snapshot([definition(auth_kind="none")])
    node.registry.busy.add("shared-expert")
    status = await node.sync.sync(node.alice)
    assert status["pending_apply"] is True
    assert node.store.state(node.alice.id)["applied"]["revision"] == 0
    assert node.registry.reloads == []
    assert node.registry.held == set()
    node.registry.busy.clear()
    assert await node.sync._apply(node.alice.id) is True
    assert node.sync.status(node.alice)["pending_apply"] is False
    assert {agent_id for agent_id, _ in node.registry.reloads} == {"alice-expert", "shared-expert"}
    assert all(user_id == node.alice.id for _, user_id in node.registry.reloads)
    assert node.registry.held == set()


async def test_same_revision_visibility_checksum_changes_and_rollback_is_rejected(node):
    await node.sync.sync(node.alice)
    previous = node.store.state(node.alice.id)["desired"]["checksum"]
    node.remote[node.alice.id] = snapshot([], revision=1)
    await node.sync.sync(node.alice)
    assert node.store.state(node.alice.id)["desired"]["checksum"] != previous
    assert node.sync.status(node.alice)["entries"] == []
    node.remote[node.alice.id] = snapshot(revision=0)
    with pytest.raises(OctopError) as failure:
        await node.sync.sync(node.alice)
    assert failure.value.code == ErrorCode.ENTERPRISE_MCP_CATALOG_INVALID
    assert node.store.state(node.alice.id)["desired"]["entries"] == []


async def test_invalid_snapshot_does_not_replace_the_active_catalogue(node):
    await node.sync.sync(node.alice)
    before = node.store.state(node.alice.id)["applied"]
    node.remote[node.alice.id] = {**snapshot(revision=2), "checksum": "0" * 64}
    with pytest.raises(OctopError):
        await node.sync.sync(node.alice)
    assert node.store.state(node.alice.id)["applied"] == before


async def test_url_change_needs_new_authorization_and_old_token_never_reaches_new_url(node):
    await authorize(node)
    node.probe.reset_mock()
    changed = definition(url="https://new-quality.example/mcp")
    node.remote[node.alice.id] = snapshot([changed], revision=2)
    await node.sync.sync(node.alice)
    assert node.sync.status(node.alice)["entries"][0]["needs_reauthorization"] is True
    assert node.store.harness_configs(node.alice.id) == {}
    with pytest.raises(OctopError) as failure:
        await authorize(node)
    assert failure.value.code == ErrorCode.ENTERPRISE_MCP_CATALOG_CONFLICT
    node.probe.assert_not_awaited()


async def test_directory_change_during_probe_conflicts_and_does_not_store_credentials(node):
    async def update_during_probe(spec):
        node.remote[node.alice.id] = snapshot(
            [definition(url="https://changed.example/mcp")], revision=2
        )
        return {"ok": True, "tools": []}

    node.probe.side_effect = update_during_probe
    with pytest.raises(OctopError) as failure:
        await authorize(node)
    assert failure.value.code == ErrorCode.ENTERPRISE_MCP_CATALOG_CONFLICT
    assert node.store.state(node.alice.id)["desired_auth"] == {}
    attempted = node.probe.call_args.args[0]
    assert attempted["url"] == definition()["url"]
    assert attempted["headers"] == {"Authorization": "Bearer alice-private-token"}


async def test_wrong_credentials_are_not_persisted_or_reported_as_session_401(node):
    node.probe.return_value = {
        "ok": False,
        "error_type": "auth",
        "error": "private-token-do-not-echo",
    }
    with pytest.raises(OctopError) as failure:
        await authorize(node, token="private-token-do-not-echo")
    assert failure.value.code == ErrorCode.CONNECTOR_INVALID_CREDENTIALS
    assert failure.value.status != 401
    assert "private-token-do-not-echo" not in str(failure.value)
    assert node.store.state(node.alice.id)["desired_auth"] == {}


@pytest.mark.parametrize("change", ["local-revoke", "disabled", "hidden", "device-revoked"])
async def test_existing_cached_tool_cannot_bypass_revocation_or_visibility(node, change):
    await authorize(node)
    node.registry.busy.add("shared-expert")
    if change == "local-revoke":
        await node.sync.revoke_credentials(node.alice, "quality")
    elif change == "disabled":
        node.remote[node.alice.id] = snapshot([definition(enabled=False)], revision=2)
    elif change == "hidden":
        node.remote[node.alice.id] = snapshot([], revision=1)
    else:
        node.client.fetch_mcp_catalog.side_effect = OctopError.localized(
            ErrorCode.ENTERPRISE_ACCESS_DENIED
        )
    name = node.store.server_name("quality", user_id=node.alice.id)
    with authenticated_vault_actor(node.alice.id), pytest.raises(OctopError):
        await node.sync.check_call(
            node.alice.id, name, node.store.runtime_binding(node.alice.id, "quality")
        )


async def test_reload_failure_restores_applied_pointer_and_old_authorization(node):
    await authorize(node, token="old-token")
    before = node.store.state(node.alice.id)
    old_key = before["applied_auth"]["quality"]["key"]
    node.registry.fail_next = True
    with pytest.raises(OctopError) as failure:
        await authorize(node, token="new-token")
    assert failure.value.code == ErrorCode.ENTERPRISE_MCP_SYNC_FAILED
    after = node.store.state(node.alice.id)
    assert after["applied"] == before["applied"]
    assert after["applied_auth"] == before["applied_auth"]
    assert after["applied_auth_revision"] == before["applied_auth_revision"]
    assert node.store.pending(node.alice.id) is True
    assert node.services.secret_repo.get(old_key) is not None
    assert next(iter(node.store.harness_configs(node.alice.id).values()))["headers"] == {
        "Authorization": "Bearer old-token"
    }
    assert node.registry.held == set()
    await node.sync._apply(node.alice.id)
    assert node.store.pending(node.alice.id) is False
    assert next(iter(node.store.harness_configs(node.alice.id).values()))["headers"] == {
        "Authorization": "Bearer new-token"
    }
    assert node.services.secret_repo.get(old_key) is None


async def test_anonymous_entry_local_disconnect_stays_blocked_until_explicit_reconnect(node):
    public_entry = definition(auth_kind="none")
    node.remote[node.alice.id] = snapshot([public_entry])
    await node.sync.sync(node.alice)
    name = node.store.server_name("quality", user_id=node.alice.id)
    fingerprint = entry_fingerprint(public_entry)
    old_binding = node.store.runtime_binding(node.alice.id, "quality")
    with authenticated_vault_actor(node.alice.id):
        await node.sync.check_call(node.alice.id, name, old_binding)
    await node.sync.revoke_credentials(node.alice, "quality")
    assert node.store.harness_configs(node.alice.id) == {}
    with authenticated_vault_actor(node.alice.id), pytest.raises(OctopError):
        await node.sync.check_call(node.alice.id, name, old_binding)
    await node.sync.sync(node.alice)
    with authenticated_vault_actor(node.alice.id), pytest.raises(OctopError):
        await node.sync.check_call(node.alice.id, name, old_binding)
    await node.sync.save_credentials(node.alice, "quality", {}, fingerprint)
    new_binding = node.store.runtime_binding(node.alice.id, "quality")
    assert new_binding != old_binding
    with authenticated_vault_actor(node.alice.id), pytest.raises(OctopError):
        await node.sync.check_call(node.alice.id, name, old_binding)
    with authenticated_vault_actor(node.alice.id):
        await node.sync.check_call(node.alice.id, name, new_binding)


@pytest.mark.parametrize("visible", ["disabled", "removed"])
async def test_credentials_can_be_deleted_after_directory_disable_or_removal(node, visible):
    await authorize(node)
    reference = node.store.state(node.alice.id)["desired_auth"]["quality"]["key"]
    node.remote[node.alice.id] = snapshot(
        [definition(enabled=False)] if visible == "disabled" else [], revision=2
    )
    await node.sync.sync(node.alice)
    await node.sync.revoke_credentials(node.alice, "quality")
    assert node.store.state(node.alice.id)["desired_auth"].get("quality") is None
    assert node.services.secret_repo.get(reference) is None


async def test_real_cached_tool_wrapper_checks_actor_before_async_and_sync_calls(node):
    from langchain_core.tools import StructuredTool

    await authorize(node)
    executed = AsyncMock(return_value="safe result")

    async def read_test_data() -> str:
        return await executed()

    raw = StructuredTool.from_function(
        coroutine=read_test_data, name="read_company_data", description="Synthetic reader"
    )
    before = partial(
        node.sync.check_call,
        node.alice.id,
        node.store.server_name("quality", user_id=node.alice.id),
        node.store.runtime_binding(node.alice.id, "quality"),
    )
    tool = wrap_tools_for_shared_use([raw], asyncio.Lock(), before_call=before)[0]
    with authenticated_vault_actor(node.alice.id):
        assert await tool.ainvoke({}) == "safe result"
        assert await asyncio.to_thread(tool.invoke, {}) == "safe result"
    assert executed.await_count == 2
    with authenticated_vault_actor(node.bob.id), pytest.raises(OctopError):
        await tool.ainvoke({})
    with authenticated_vault_actor(node.alice.id), pytest.raises(OctopError):
        tool.invoke({})
    assert executed.await_count == 2


@pytest.mark.parametrize("revoke_first", [False, True])
async def test_same_token_reauthorization_invalidates_old_cached_capability(node, revoke_first):
    await authorize(node, token="same-member-token")
    name = node.store.server_name("quality", user_id=node.alice.id)
    old_binding = node.store.runtime_binding(node.alice.id, "quality")
    old_configs = node.store.harness_configs(node.alice.id)
    if revoke_first:
        await node.sync.revoke_credentials(node.alice, "quality")
    reload_count = len(node.registry.reloads)
    await authorize(node, token="same-member-token")
    assert node.store.harness_configs(node.alice.id) == old_configs
    assert len(node.registry.reloads) > reload_count
    binding = node.store.runtime_binding(node.alice.id, "quality")
    assert binding != old_binding
    with authenticated_vault_actor(node.alice.id), pytest.raises(OctopError):
        await node.sync.check_call(node.alice.id, name, old_binding)
    with authenticated_vault_actor(node.alice.id):
        await node.sync.check_call(node.alice.id, name, binding)


async def test_rebinding_local_account_to_new_subject_cannot_reuse_old_tools(node):
    await authorize(node)
    old_name = node.store.server_name("quality", user_id=node.alice.id)
    old_binding = node.store.runtime_binding(node.alice.id, "quality")
    node.client.fetch_mcp_catalog.side_effect = lambda user: (
        "different-company-subject",
        snapshot(),
    )
    await node.sync.sync(node.alice)
    new_name = node.store.server_name("quality", user_id=node.alice.id)
    assert new_name != old_name
    assert len(new_name) <= 64
    assert node.store.harness_configs(node.alice.id) == {}
    with authenticated_vault_actor(node.alice.id), pytest.raises(OctopError):
        await node.sync.check_call(node.alice.id, old_name, old_binding)


async def test_busy_anonymous_reconnect_does_not_revive_the_old_tool_binding(node):
    public_entry = definition(auth_kind="none")
    node.remote[node.alice.id] = snapshot([public_entry])
    await node.sync.sync(node.alice)
    name = node.store.server_name("quality", user_id=node.alice.id)
    old_binding = node.store.runtime_binding(node.alice.id, "quality")
    await node.sync.revoke_credentials(node.alice, "quality")
    node.registry.busy.add("shared-expert")
    status = await node.sync.save_credentials(
        node.alice, "quality", {}, entry_fingerprint(public_entry)
    )
    assert status["pending_apply"] is True
    with authenticated_vault_actor(node.alice.id), pytest.raises(OctopError):
        await node.sync.check_call(node.alice.id, name, old_binding)
    node.registry.busy.clear()
    await node.sync._apply(node.alice.id)
    new_binding = node.store.runtime_binding(node.alice.id, "quality")
    assert new_binding != old_binding
    with authenticated_vault_actor(node.alice.id), pytest.raises(OctopError):
        await node.sync.check_call(node.alice.id, name, old_binding)
    with authenticated_vault_actor(node.alice.id):
        await node.sync.check_call(node.alice.id, name, new_binding)


async def test_new_catalogue_revision_refreshes_schema_only_for_managed_tool_cache(node):
    node.connector.put_custom_servers(
        node.alice.id,
        {"personal-local": {"transport": "stdio", "command": "synthetic-personal-command"}},
    )
    await authorize(node)
    name = node.store.server_name("quality", user_id=node.alice.id)
    old_configs = node.store.harness_configs(node.alice.id)
    node.registry.reloads.clear()
    node.registry.invalidations.clear()
    node.remote[node.alice.id] = snapshot(revision=2)
    await node.sync.sync(node.alice)
    assert node.store.harness_configs(node.alice.id) == old_configs
    assert node.registry.reloads
    assert node.registry.invalidations
    assert all(
        user_id == node.alice.id and names == frozenset({name})
        for user_id, names in node.registry.invalidations
    )
    assert "personal-local" in node.connector.get_custom_servers(node.alice.id)


def fast_worker_clock(monkeypatch):
    clock = SimpleNamespace(now=1000)

    async def tick(_delay):
        clock.now += 31
        await asyncio.sleep(0)

    monkeypatch.setattr(sync_module, "time", SimpleNamespace(monotonic=lambda: clock.now))
    monkeypatch.setattr(sync_module, "asyncio", SimpleNamespace(**{**vars(asyncio), "sleep": tick}))


async def test_worker_isolates_member_failure_and_retries_next_round(node, monkeypatch, caplog):
    fast_worker_clock(monkeypatch)
    for user in node.users:
        node.services.secret_repo.set(f"enterprise.identity.{user.id}", b"synthetic identity")
    calls = []
    recovered = asyncio.Event()

    async def fetch(user):
        calls.append(user.id)
        if user.id == node.alice.id:
            if calls.count(user.id) == 1:
                raise RuntimeError("synthetic-sensitive-error-detail")
            recovered.set()
        return "member-" + str(user.id), node.remote[user.id]

    node.client.fetch_mcp_catalog.side_effect = fetch
    node.sync.start()
    try:
        await asyncio.wait_for(recovered.wait(), 5)
    finally:
        await node.sync.stop()

    assert calls.index(node.bob.id) < len(calls) - 1
    assert calls.count(node.alice.id) >= 2
    assert "RuntimeError" in caplog.text
    assert "synthetic-sensitive-error-detail" not in caplog.text
    assert not node.registry.held
    assert all(not lock.locked() for lock in node.sync._locks.values())


async def test_worker_retries_transient_user_scan_failure(node, monkeypatch, caplog):
    fast_worker_clock(monkeypatch)
    node.services.secret_repo.set(f"enterprise.identity.{node.alice.id}", b"synthetic identity")
    original_list = node.services.user_repo.list
    attempts = 0
    fetched = asyncio.Event()

    def scan():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("synthetic-sensitive-database-detail")
        return original_list()

    async def fetch(user):
        fetched.set()
        return "member-" + str(user.id), node.remote[user.id]

    monkeypatch.setattr(node.services.user_repo, "list", scan)
    node.client.fetch_mcp_catalog.side_effect = fetch
    node.sync.start()
    try:
        await asyncio.wait_for(fetched.wait(), 5)
    finally:
        await node.sync.stop()

    assert attempts >= 2
    assert "RuntimeError" in caplog.text
    assert "synthetic-sensitive-database-detail" not in caplog.text


async def test_worker_restarts_finished_task_and_shutdown_cancels_inflight_sync(node):
    node.services.secret_repo.set(f"enterprise.identity.{node.alice.id}", b"synthetic identity")
    completed = asyncio.create_task(asyncio.sleep(0))
    await completed
    node.sync._task = completed
    started = asyncio.Event()
    never = asyncio.Event()

    async def fetch(_user):
        started.set()
        await never.wait()

    node.client.fetch_mcp_catalog.side_effect = fetch
    node.sync.start()
    active = node.sync._task
    assert active is not completed
    await asyncio.wait_for(started.wait(), 5)
    await asyncio.wait_for(node.sync.stop(), 5)

    assert active.cancelled()
    assert node.sync._task is None
    assert not node.registry.held
    assert all(not lock.locked() for lock in node.sync._locks.values())


def loader_manager(node):
    manager = object.__new__(AgentManager)
    manager._mcp_tool_cache = {}
    manager._mcp_tool_cache_locks = {}
    manager._mcp_tool_cache_guard = asyncio.Lock()
    manager._paths = node.server.paths
    manager._connector_svc = node.connector
    manager.set_enterprise_mcp_authorizer(node.sync.check_call)
    return manager


@pytest.mark.parametrize("change", ["revoke", "disable", "rotate", "subject"])
async def test_inflight_sdk_load_cannot_lose_or_retag_its_managed_guard(node, monkeypatch, change):
    await authorize(node, token="same-member-token")
    name = node.store.server_name("quality", user_id=node.alice.id)
    original_spec = node.store.harness_configs(node.alice.id)[name]
    old_binding = node.store.runtime_binding(node.alice.id, "quality")
    started, release = asyncio.Event(), asyncio.Event()
    executed = AsyncMock(return_value="safe result")

    async def load(_configs):
        started.set()
        await release.wait()
        return [
            SimpleNamespace(
                name=name + "_read",
                description="Read company data",
                args_schema=None,
                metadata=None,
                ainvoke=executed,
            )
        ]

    sdk = AsyncMock(side_effect=load)
    monkeypatch.setattr("octop_harness.mcp.aload_mcp_tools", sdk)
    manager = loader_manager(node)
    loading = asyncio.create_task(
        manager._get_or_load_mcp_tools(node.alice.id, name, original_spec)
    )
    try:
        await asyncio.wait_for(started.wait(), 5)
        if change == "revoke":
            await node.sync.revoke_credentials(node.alice, "quality")
        elif change == "disable":
            node.remote[node.alice.id] = snapshot([definition(enabled=False)], revision=2)
            await node.sync.sync(node.alice)
        elif change == "rotate":
            await authorize(node, token="same-member-token")
            assert node.store.harness_configs(node.alice.id)[name] == original_spec
            assert node.store.runtime_binding(node.alice.id, "quality") != old_binding
        else:
            node.client.fetch_mcp_catalog.side_effect = lambda _user: (
                "different-company-subject",
                snapshot(),
            )
            await node.sync.sync(node.alice)
    finally:
        release.set()
        tools = await asyncio.wait_for(loading, 5)

    with authenticated_vault_actor(node.alice.id), pytest.raises(OctopError):
        await tools[0].ainvoke({})
    executed.assert_not_awaited()

    if change == "rotate":
        fresh = await manager._get_or_load_mcp_tools(node.alice.id, name, original_spec)
        assert fresh is not tools
        assert sdk.await_count == 2
        with authenticated_vault_actor(node.alice.id):
            assert await fresh[0].ainvoke({}) == "safe result"
    else:
        with pytest.raises(OctopError) as denied:
            await manager._get_or_load_mcp_tools(node.alice.id, name, original_spec)
        assert denied.value.code is ErrorCode.ENTERPRISE_ACCESS_DENIED
        assert sdk.await_count == 1


async def test_binding_matches_exact_spec_from_one_state_snapshot(node, monkeypatch):
    await authorize(node)
    name = node.store.server_name("quality", user_id=node.alice.id)
    spec = node.store.harness_configs(node.alice.id)[name]
    binding = node.store.runtime_binding(node.alice.id, "quality")
    original_state = node.store.state
    reads = []

    def read_once(user_id):
        reads.append(user_id)
        assert len(reads) == 1
        return original_state(user_id)

    monkeypatch.setattr(node.store, "state", read_once)
    assert node.store.binding_for_spec(node.alice.id, name, spec) == binding
    assert reads == [node.alice.id]
    monkeypatch.setattr(node.store, "state", original_state)
    for changed in (
        {**spec, "url": "https://another.example/mcp"},
        {**spec, "headers": {"Authorization": "Bearer another-token"}},
        {**spec, "command": "unexpected-command"},
    ):
        assert node.store.binding_for_spec(node.alice.id, name, changed) == ""


@pytest.mark.parametrize("name", ["personal", "corp_0123456789abcdef"])
async def test_current_personal_definition_keeps_unguarded_personal_loading(
    node, monkeypatch, name
):
    node.connector.put_custom_servers(
        node.alice.id,
        {name: {"transport": "streamable_http", "url": "https://personal.example/mcp"}},
    )
    spec = node.connector.custom_harness_configs(node.alice.id)[name]
    assert node.connector.enterprise_mcp_fingerprint(node.alice.id, name, spec) is None
    executed = AsyncMock(return_value="personal result")
    monkeypatch.setattr(
        "octop_harness.mcp.aload_mcp_tools",
        AsyncMock(
            return_value=[
                SimpleNamespace(
                    name=name + "_read",
                    description="Read personal data",
                    args_schema=None,
                    metadata=None,
                    ainvoke=executed,
                )
            ]
        ),
    )
    manager = loader_manager(node)
    manager.set_enterprise_mcp_authorizer(AsyncMock(side_effect=AssertionError("personal guard")))
    tools = await manager._get_or_load_mcp_tools(node.alice.id, name, spec)
    assert await tools[0].ainvoke({}) == "personal result"
    executed.assert_awaited_once()
