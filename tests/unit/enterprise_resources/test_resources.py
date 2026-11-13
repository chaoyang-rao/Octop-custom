"""Version publication, independent copies and conservative update acceptance."""

import base64
import json
from dataclasses import replace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from octop.api.deps import current_user, get_server
from octop.api.routers.enterprise_resources_admin import router
from octop.infra.enterprise_resources.export import export_options, export_resource
from octop.infra.enterprise_resources.models import ResourceDefinition, ResourceFile
from octop.infra.enterprise_resources.node import ResourceSync
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.mobile_access.access import MobileUser, authorize_device_path


def definition(kind="expert", resource_id="quality", files=None, **changes):
    contents = files or (
        {"SOUL.md": b"company v1"}
        if kind == "expert"
        else {"SKILL.md": b"---\nname: quality\ndescription: Test quality\n---\ncompany v1"}
    )
    return ResourceDefinition(
        resource_id=resource_id,
        kind=kind,
        display_name=changes.pop("display_name", resource_id),
        files=[
            ResourceFile(path=p, content_base64=base64.b64encode(v).decode())
            for p, v in contents.items()
        ],
        **changes,
    )


def publish(company, *resources):
    state = company.catalog.admin(company.admin)
    for resource in resources:
        state = company.catalog.save_entry(company.admin, resource, state.etag)
    return company.catalog.publish(company.admin, state.etag)


def local(node, resource_id="quality"):
    return node.sync._state(node.user.id)["resources"][resource_id]


def workspace(node, resource_id="quality"):
    return node.registry.workspaces[local(node, resource_id)["target_id"]]


@pytest.mark.parametrize(
    "path",
    [
        "../SKILL.md",
        "/SKILL.md",
        "a/../../b",
        "C:/a",
        "a\\b",
        ".env",
        "auth/token",
        "memory/data.md",
        "USER.md",
        "a/NUL.txt",
        "a./b",
        "foo/credentials.json",
        "a\x00b",
    ],
)
def test_private_or_nonportable_paths_are_rejected(path):
    with pytest.raises(ValidationError):
        definition("skill", files={"SKILL.md": b"x", path: b"private"})


@pytest.mark.parametrize("path", ["a?.py", "a*.md", "a<.md", "a>.md", "a|.md", 'a".md'])
def test_windows_forbidden_characters_are_rejected(path):
    with pytest.raises(ValidationError):
        definition("skill", files={"SKILL.md": b"x", path: b"x"})


def test_macos_normalization_collision_is_rejected():
    with pytest.raises(ValidationError):
        definition(
            "skill", files={"SKILL.md": b"x", "refs/caf\u00e9.md": b"a", "refs/cafe\u0301.md": b"b"}
        )


def test_case_collisions_expert_private_state_and_extra_config_rejected():
    for kwargs in [
        {"files": {"SOUL.md": b"a", "soul.md": b"b"}},
        {"files": {"USER.md": b"private"}},
        {"files": {"config.json": b"{}"}},
        {"files": {"SOUL.md": b"\xff"}},
        {"runtime_config": {"token": "secret"}},
    ]:
        with pytest.raises(ValidationError):
            definition(**kwargs)
    with pytest.raises(ValidationError):
        definition("skill", files={"SKILL.md": b"x", "a": b"x", "a/b": b"y"})


def test_draft_visibility_history_cas_and_rollback(company):
    state = company.catalog.admin(company.admin)
    draft = company.catalog.save_entry(company.admin, definition(), state.etag)
    assert not company.catalog.member(company.alice).entries
    with pytest.raises(OctopError) as failure:
        company.catalog.publish(company.admin, state.etag)
    assert failure.value.code == ErrorCode.ENTERPRISE_RESOURCE_CONFLICT
    first = company.catalog.publish(company.admin, draft.etag)
    first_hash = first.published.entries[0].digest
    second = publish(company, definition(files={"SOUL.md": b"v2"}))
    restored = company.catalog.rollback(company.admin, 1, second.etag)
    assert restored.published.revision == 3
    assert restored.published.entries[0].digest == first_hash
    assert restored.draft[0].digest == second.draft[0].digest
    assert (
        company.catalog.bundle(company.admin, first_hash).content_files()["SOUL.md"]
        == b"company v1"
    )


def test_visibility_device_scope_and_dependencies(company):
    subject = company.catalog.center.require_employee(company.alice)
    state = publish(company, definition(allowed_subjects=[subject]))
    assert company.catalog.member(company.alice).entries[0].allowed_subjects == []
    assert not company.catalog.member(company.bob).entries
    with pytest.raises(OctopError):
        company.catalog.bundle(company.bob, state.published.entries[0].digest)
    device = MobileUser(
        company.admin.id,
        company.admin.username,
        company.admin.role,
        "Publisher",
        device_scopes=("enterprise",),
    )
    with pytest.raises(OctopError):
        company.catalog.admin(device)
    with pytest.raises(OctopError):
        publish(company, definition(skill_refs=["missing"]))
    # Purpose-limited node credentials may read exact bundle URLs, never publish.
    session = type("Session", (), {"scopes": ["enterprise"], "kind": "device"})()
    authorize_device_path(session, "/api/enterprise/resources/bundles/" + "a" * 64, "GET")
    for method, path in [
        ("POST", "/api/enterprise/resources/admin/publish"),
        ("GET", "/api/enterprise/resources/admin/catalog"),
        ("GET", "/api/enterprise/resources/bundles/../private"),
    ]:
        with pytest.raises(OctopError):
            authorize_device_path(session, path, method)


async def test_two_nodes_get_independent_copies_and_preserve_private_settings(company):
    publish(company, definition("skill", "quality-skill"), definition(skill_refs=["quality-skill"]))
    ids = []
    for node in company.nodes:
        node.server.services.secret_repo.set("personal.auth", b"private-token")
        result = await node.sync.sync(node.user)
        assert {r["status"] for r in result["resources"]} == {"current"}
        target = local(node)["target_id"]
        ids.append(target)
        cfg = {
            "enterprise_resource": json.loads(
                node.server.services.agent_repo.get(target).config_json
            )["enterprise_resource"],
            "cli": {"profile": "personal"},
            "root_dir": "personal-project",
            "avatar": {"shape": "blob", "color": "rose"},
        }
        node.server.services.agent_repo.update_config(
            target, default_model="personal-provider:model", config_json=json.dumps(cfg)
        )
        await node.sync.sync(node.user)
        assert len(node.server.services.agent_repo.list_all()) == 1
    assert ids[0] != ids[1]
    publish(company, definition(files={"SOUL.md": b"v2"}, skill_refs=["quality-skill"]))
    for node in company.nodes:
        await node.sync.sync(node.user)
        row = node.server.services.agent_repo.get(local(node)["target_id"])
        assert row.default_model == "personal-provider:model"
        assert json.loads(row.config_json)["cli"] == {"profile": "personal"}
        assert json.loads(row.config_json)["root_dir"] == "personal-project"
        assert node.server.services.secret_repo.get("personal.auth") == b"private-token"
        assert workspace(node).files["USER.md"] == b"personal preferences"
        assert workspace(node).files["memory/private.md"] == b"private memory"
        assert workspace(node).files["SOUL.md"] == b"v2"


async def test_local_changes_disjoint_merge_conflict_and_keep_local(company):
    node = company.nodes[0]
    publish(company, definition(files={"SOUL.md": b"soul1", "TOOLS.md": b"tools1"}))
    await node.sync.sync(node.user)
    ws = workspace(node)
    ws.files["SOUL.md"] = b"my soul"
    publish(company, definition(files={"SOUL.md": b"soul1", "TOOLS.md": b"tools2"}))
    await node.sync.sync(node.user)
    assert ws.files["SOUL.md"] == b"my soul"
    assert ws.files["TOOLS.md"] == b"tools2"
    publish(company, definition(files={"SOUL.md": b"soul2", "TOOLS.md": b"tools3"}))
    result = await node.sync.sync(node.user)
    assert result["resources"][0]["status"] == "conflict"
    assert ws.files["TOOLS.md"] == b"tools2"  # no partial application
    detail = await node.sync.detail(node.user, "quality")
    assert [c["path"] for c in detail["conflicts"]] == ["SOUL.md"]
    await node.sync.resolve(node.user, "quality", detail["ticket"], {"SOUL.md": "local"})
    assert ws.files["SOUL.md"] == b"my soul"
    assert ws.files["TOOLS.md"] == b"tools3"
    await node.sync.sync(node.user)
    assert local(node)["status"] == "current"


async def test_conflict_stale_ticket_and_remote_resolution(company):
    node = company.nodes[0]
    publish(company, definition())
    await node.sync.sync(node.user)
    ws = workspace(node)
    ws.files["SOUL.md"] = b"local"
    publish(company, definition(files={"SOUL.md": b"remote"}))
    await node.sync.sync(node.user)
    detail = await node.sync.detail(node.user, "quality")
    ws.files["SOUL.md"] = b"local newer"
    with pytest.raises(OctopError):
        await node.sync.resolve(node.user, "quality", detail["ticket"], {"SOUL.md": "remote"})
    assert ws.files["SOUL.md"] == b"local newer"
    detail = await node.sync.detail(node.user, "quality")
    await node.sync.resolve(node.user, "quality", detail["ticket"], {"SOUL.md": "remote"})
    assert ws.files["SOUL.md"] == b"remote"


async def test_busy_expert_and_paused_resource_keep_running_content(company):
    node = company.nodes[0]
    publish(company, definition())
    await node.sync.sync(node.user)
    target = local(node)["target_id"]
    node.registry.busy.add(target)
    publish(company, definition(files={"SOUL.md": b"v2"}))
    await node.sync.sync(node.user)
    assert local(node)["status"] == "pending"
    assert workspace(node).files["SOUL.md"] == b"company v1"
    assert not node.registry.reloads
    node.registry.busy.clear()
    await node.sync.pause(node.user, "quality", True)
    await node.sync.sync(node.user)
    assert workspace(node).files["SOUL.md"] == b"company v1"
    await node.sync.pause(node.user, "quality", False)
    await node.sync.sync(node.user)
    assert workspace(node).files["SOUL.md"] == b"v2"
    assert not node.registry.held


async def test_skill_update_waits_for_every_mounted_expert_and_keeps_added_file(company):
    node = company.nodes[0]
    publish(company, definition("skill", "qa"), definition(skill_refs=["qa"]))
    await node.sync.sync(node.user)
    record = local(node, "qa")
    directory = node.sync.packages.package_skills_dir(record["target_id"]) / record["slug"]
    (directory / "notes.md").write_bytes(b"personal notes")
    target = local(node)["target_id"]
    node.registry.busy.add(target)
    publish(
        company,
        definition(
            "skill", "qa", files={"SKILL.md": b"---\nname: quality\ndescription: QA\n---\nv2"}
        ),
    )
    await node.sync.sync(node.user)
    assert local(node, "qa")["status"] == "pending"
    node.registry.busy.clear()
    await node.sync.sync(node.user)
    assert (directory / "SKILL.md").read_bytes().endswith(b"v2")
    assert (directory / "notes.md").read_bytes() == b"personal notes"
    assert target in node.registry.reloads


async def test_reload_failure_restores_old_files_and_metadata(company):
    node = company.nodes[0]
    publish(company, definition())
    await node.sync.sync(node.user)
    row = node.server.services.agent_repo.get(local(node)["target_id"])
    publish(company, definition(files={"SOUL.md": b"v2"}, description="new description"))
    node.registry.fail_next = True
    result = await node.sync.sync(node.user)
    assert result["resources"][0]["status"] == "error"
    assert workspace(node).files["SOUL.md"] == b"company v1"
    assert node.server.services.agent_repo.get(row.agent_id).description == row.description
    assert local(node)["last_backup"]
    assert local(node)["journal"] is None
    assert not node.registry.held
    await node.sync.sync(node.user)
    assert workspace(node).files["SOUL.md"] == b"v2"


async def test_removed_visibility_stops_updates_but_keeps_local_copy(company):
    node = company.nodes[0]
    publish(company, definition())
    await node.sync.sync(node.user)
    old_target = local(node)["target_id"]
    bob_subject = company.catalog.center.require_employee(company.bob)
    publish(
        company, definition(allowed_subjects=[bob_subject], files={"SOUL.md": b"not for alice"})
    )
    result = await node.sync.sync(node.user)
    assert not result["resources"][0]["enabled"]
    assert result["resources"][0]["target_id"] == old_target
    assert workspace(node).files["SOUL.md"] == b"company v1"


async def test_restart_and_export_never_export_private_user_memory_or_cli(company):
    node = company.nodes[0]
    publish(company, definition())
    await node.sync.sync(node.user)
    old_target = local(node)["target_id"]
    node.sync = ResourceSync(node.server)
    node.server._enterprise_resources = node.sync
    await node.sync.sync(node.user)
    assert local(node)["target_id"] == old_target
    export = await export_resource(node.server, node.user, "expert", old_target)
    assert export.content_files() == {"SOUL.md": b"company v1"}
    assert "config" not in export.model_dump()
    assert export_options(node.server, node.user)[0]["id"] == old_target
    with pytest.raises(OctopError):
        await export_resource(node.server, replace(node.user, id=999), "expert", old_target)


async def test_validation_errors_never_echo_sensitive_input(company):
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_server] = lambda: company.center
    app.dependency_overrides[current_user] = lambda: company.admin

    @app.exception_handler(OctopError)
    async def error(_request, exc):
        return JSONResponse(status_code=exc.status, content=exc.to_envelope())

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        payload = definition().model_dump(mode="json")
        payload["cli_token"] = "synthetic-secret-must-not-echo"
        response = await client.put(
            "/api/enterprise/resources/admin/entry",
            json={"resource": payload, "expected_etag": company.catalog.admin(company.admin).etag},
        )
        assert response.status_code == 400
        assert "synthetic-secret" not in response.text
        assert ErrorCode.ENTERPRISE_RESOURCE_INVALID.value in response.text
        schemas = app.openapi()["components"]["schemas"]
        assert "ResourceDefinition" in schemas


async def test_skill_local_conflict_and_binary_assets(company):
    node = company.nodes[0]
    original = b"---\nname: qa\ndescription: QA\n---\noriginal"
    publish(
        company,
        definition(
            "skill", "qa", files={"SKILL.md": original, "assets/icon.bin": b"\x00\xffbinary"}
        ),
    )
    await node.sync.sync(node.user)
    record = local(node, "qa")
    node.sync.packages.write_skill_manifest(
        record["target_id"], record["slug"], original.decode() + " local"
    )
    remote = original + b" remote"
    publish(
        company,
        definition("skill", "qa", files={"SKILL.md": remote, "assets/icon.bin": b"\x00\xffnew"}),
    )
    result = await node.sync.sync(node.user)
    assert result["resources"][0]["status"] == "conflict"
    detail = await node.sync.detail(node.user, "qa")
    await node.sync.resolve(node.user, "qa", detail["ticket"], {"SKILL.md": "local"})
    files = dict(node.sync.packages.read_skill_files(record["target_id"], record["slug"]))
    assert files["SKILL.md"].endswith(b" local")
    assert files["assets/icon.bin"] == b"\x00\xffnew"


async def test_private_file_added_to_skill_blocks_update_without_archiving_it(company):
    node = company.nodes[0]
    publish(company, definition("skill", "qa"))
    await node.sync.sync(node.user)
    record = local(node, "qa")
    directory = node.sync.packages.package_skills_dir(record["target_id"]) / record["slug"]
    (directory / ".env").write_bytes(b"personal-private")
    publish(company, definition("skill", "qa", files={"SKILL.md": b"v2"}))
    result = await node.sync.sync(node.user)
    assert result["resources"][0]["status"] == "error"
    assert (directory / ".env").read_bytes() == b"personal-private"
    assert (directory / "SKILL.md").read_bytes().endswith(b"company v1")
    assert not local(node, "qa").get("last_backup")
    with pytest.raises(OctopError) as rejected:
        await export_resource(node.server, node.user, "skill", record["target_id"], record["slug"])
    assert rejected.value.code == ErrorCode.ENTERPRISE_RESOURCE_INVALID
    assert "personal-private" not in str(rejected.value)


async def test_partial_write_journal_recovers_after_restart_and_removal(company):
    node = company.nodes[0]
    publish(company, definition(files={"SOUL.md": b"old", "TOOLS.md": b"old tools"}))
    await node.sync.sync(node.user)
    state = node.sync._state(node.user.id)
    record = state["resources"]["quality"]
    profile = node.sync._profile(node.user.id, record)
    from octop.infra.enterprise_resources.node import encode_files

    record["journal"] = {
        "before_files": encode_files({"SOUL.md": b"old", "TOOLS.md": b"old tools"}),
        "after_files": encode_files({"SOUL.md": b"new", "TOOLS.md": b"new tools"}),
        "before_profile": profile,
        "after_profile": profile,
    }
    workspace(node).files["SOUL.md"] = b"new"
    workspace(node).files["TOOLS.md"] = b"later personal edit"
    record["paused"] = True
    node.sync._save(node.user.id, state)
    admin = company.catalog.admin(company.admin)
    draft = company.catalog.remove_entry(company.admin, "quality", admin.etag)
    company.catalog.publish(company.admin, draft.etag)
    node.sync = ResourceSync(node.server)
    node.server._enterprise_resources = node.sync
    await node.sync.sync(node.user)
    assert workspace(node).files["SOUL.md"] == b"old"
    assert workspace(node).files["TOOLS.md"] == b"later personal edit"
    assert local(node)["journal"] is None


async def test_publication_change_invalidates_an_observed_conflict_decision(company):
    node = company.nodes[0]
    publish(company, definition())
    await node.sync.sync(node.user)
    workspace(node).files["SOUL.md"] = b"my edit"
    publish(company, definition(files={"SOUL.md": b"v2"}))
    await node.sync.sync(node.user)
    detail = await node.sync.detail(node.user, "quality")
    publish(company, definition(files={"SOUL.md": b"v3"}))
    with pytest.raises(OctopError):
        await node.sync.resolve(node.user, "quality", detail["ticket"], {"SOUL.md": "remote"})
    assert workspace(node).files["SOUL.md"] == b"my edit"


def test_dependency_visibility_cannot_leave_members_with_an_inaccessible_skill(company):
    subject = company.catalog.center.require_employee(company.alice)
    with pytest.raises(OctopError):
        publish(
            company,
            definition("skill", "qa", allowed_subjects=[subject]),
            definition(skill_refs=["qa"]),
        )


async def test_conditional_profile_update_preserves_concurrent_personal_model_config(
    company, monkeypatch
):
    node = company.nodes[0]
    publish(company, definition())
    await node.sync.sync(node.user)
    repo = node.server.services.agent_repo
    target = local(node)["target_id"]
    original = repo.compare_and_update

    def race(agent_id, expected, changes):
        row = repo.get(agent_id)
        cfg = json.loads(row.config_json)
        cfg["cli"] = {"profile": "edited-during-sync"}
        repo.update_config(agent_id, config_json=json.dumps(cfg))
        return original(agent_id, expected, changes)

    monkeypatch.setattr(repo, "compare_and_update", race)
    publish(company, definition(description="new", files={"SOUL.md": b"v2"}))
    result = await node.sync.sync(node.user)
    assert result["resources"][0]["status"] == "error"
    assert json.loads(repo.get(target).config_json)["cli"]["profile"] == "edited-during-sync"
    assert workspace(node).files["SOUL.md"] == b"company v1"


async def test_real_manager_and_workspace_without_model_requests(company):
    from octop.infra.agents.manager import AgentManager

    node = company.nodes[0]
    manager = AgentManager(
        repos=node.server.services.repos, paths=node.server.paths, config=node.server.config
    )
    node.server.app_runtime.agent_registry = manager
    await manager.boot()
    try:
        publish(company, definition("skill", "qa"), definition(skill_refs=["qa"]))
        state = await node.sync.sync(node.user)
        assert all(item["status"] == "current" for item in state["resources"])
        target = local(node)["target_id"]
        ws = manager.workspace_for_agent(target)
        assert await ws.adownload_bytes("SOUL.md") == b"company v1"
        await ws.aupload_bytes("USER.md", b"private preference")
        publish(company, definition(files={"SOUL.md": b"v2"}, skill_refs=["qa"]))
        await node.sync.sync(node.user)
        assert await ws.adownload_bytes("SOUL.md") == b"v2"
        assert await ws.adownload_bytes("USER.md") == b"private preference"
    finally:
        await manager.shutdown()


async def test_identity_change_restores_interrupted_old_copy_before_creating_new_one(company):
    from unittest.mock import AsyncMock

    from octop.infra.enterprise_resources.node import encode_files

    node = company.nodes[0]
    publish(company, definition())
    await node.sync.sync(node.user)
    state = node.sync._state(node.user.id)
    record = state["resources"]["quality"]
    old_target = record["target_id"]
    profile = node.sync._profile(node.user.id, record)
    record["journal"] = {
        "before_files": encode_files({"SOUL.md": b"company v1"}),
        "after_files": encode_files({"SOUL.md": b"interrupted"}),
        "before_profile": profile,
        "after_profile": profile,
    }
    record["paused"] = True
    node.registry.workspaces[old_target].files["SOUL.md"] = b"interrupted"
    node.sync._save(node.user.id, state)
    client = company.clients[id(node.server)]
    client.fetch_resource_catalog = AsyncMock(
        return_value=("replacement-member", state["snapshot"])
    )
    await node.sync.sync(node.user)
    assert local(node)["target_id"] != old_target
    assert node.registry.workspaces[old_target].files["SOUL.md"] == b"company v1"
    assert node.server.services.agent_repo.get(old_target).user_id == node.user.id


async def test_chat_archive_and_project_thread_survive_resource_update(company):
    from octop.infra.db.repos.thread_messages import ThreadMessageInput

    node = company.nodes[0]
    publish(company, definition())
    await node.sync.sync(node.user)
    services = node.server.services
    target = local(node)["target_id"]
    services.thread_repo.insert(
        thread_id="personal-thread",
        agent_id=target,
        user_id=node.user.id,
        channel_type="dashboard",
        session_key="personal-session",
        title="Private conversation",
        project_path="personal-project",
        project_name="Private project",
    )
    services.thread_message_repo.replace_all(
        "personal-thread",
        [ThreadMessageInput("m1", "user", '{"content":"private chat text"}', 123)],
    )
    before_thread = services.thread_repo.get("personal-thread")
    before_messages = services.thread_message_repo.range_rows("personal-thread", 1, 10)
    publish(company, definition(files={"SOUL.md": b"company update"}))
    await node.sync.sync(node.user)
    assert services.thread_repo.get("personal-thread") == before_thread
    assert services.thread_message_repo.range_rows("personal-thread", 1, 10) == before_messages


async def test_skill_edit_racing_with_update_is_retained(company, monkeypatch):
    node = company.nodes[0]
    publish(company, definition("skill", "qa"))
    await node.sync.sync(node.user)
    record = local(node, "qa")
    original = node.sync.packages.compare_and_write_skill

    def edit_before_commit(package_id, slug, before, after):
        node.sync.packages.write_skill_manifest(package_id, slug, "local edit made during sync")
        return original(package_id, slug, before, after)

    monkeypatch.setattr(node.sync.packages, "compare_and_write_skill", edit_before_commit)
    publish(company, definition("skill", "qa", files={"SKILL.md": b"company update"}))
    state = await node.sync.sync(node.user)
    assert state["resources"][0]["status"] == "error"
    assert (
        dict(node.sync.packages.read_skill_files(record["target_id"], record["slug"]))["SKILL.md"]
        == b"local edit made during sync"
    )


async def test_real_manager_resource_reload_propagates_failure(company, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from octop.infra.agents.manager import AgentManager

    node = company.nodes[0]
    repo = node.server.services.agent_repo
    repo.create(agent_id="reload-test", user_id=node.user.id, name="Reload test")
    repo.set_state("reload-test", "running")
    manager = AgentManager(
        repos=node.server.services.repos, paths=node.server.paths, config=node.server.config
    )
    manager._harness_manager = SimpleNamespace(
        shared_factory=object(),
        arebuild_agent=AsyncMock(side_effect=RuntimeError("synthetic rebuild failure")),
    )
    monkeypatch.setattr(manager, "_agent_runtime_bundle", lambda row: ({}, {}, [], ""))
    monkeypatch.setattr(manager, "_octop_harness_or_none", lambda _: None)
    with pytest.raises(RuntimeError, match="synthetic rebuild failure"):
        await manager.reload_resource_content("reload-test")
    assert repo.get("reload-test").last_state == "failed"


async def test_export_candidate_listing_does_not_repair_invalid_member_content(company):
    node = company.nodes[0]
    publish(company, definition("skill", "qa"))
    await node.sync.sync(node.user)
    record = local(node, "qa")
    manifest = (
        node.sync.packages.package_skills_dir(record["target_id"]) / record["slug"] / "SKILL.md"
    )
    manifest.write_bytes(b"\xffpersonal data")
    choices = export_options(node.server, node.user)
    assert any(row["slug"] == record["slug"] for row in choices)
    assert manifest.read_bytes() == b"\xffpersonal data"


async def test_real_enterprise_device_reads_skills_using_current_owner_permissions(company):
    from octop.infra.mobile_access.access import resolve_mobile_user

    center = company.catalog.center
    await company.center.user_manager.set_permissions(company.alice.username, ["experts", "skills"])
    publish(company, definition("skill", "qa"), definition(skill_refs=["qa"]))
    challenge = await center.begin("Isolated resource device", "test-network")
    await center.approve(company.alice, challenge["user_code"])
    result = await center.exchange(challenge["pairing_secret"], "test-network")
    device = resolve_mobile_user(
        company.center,
        result["access_token"],
        path="/api/enterprise/resources/catalog",
        method="GET",
    )
    assert "skills" not in device.permissions  # purpose-limited device, not a management session
    received = company.catalog.member(device)
    assert {e.kind for e in received.entries} == {"expert", "skill"}
    skill = next(e for e in received.entries if e.kind == "skill")
    assert company.catalog.bundle(device, skill.digest).resource_id == "qa"
    with pytest.raises(OctopError):
        company.catalog.admin(device)
    await company.center.user_manager.set_permissions(company.alice.username, ["experts"])
    assert {e.kind for e in company.catalog.member(device).entries} == {"expert"}
    with pytest.raises(OctopError):
        company.catalog.bundle(device, skill.digest)


async def test_real_company_login_http_catalog_and_node_sync(company, monkeypatch):
    from fastapi import Request

    from octop.api.routers.enterprise import router as identity_router
    from octop.infra.auth.enterprise import EnterpriseClient
    from octop.infra.enterprise_resources import node as sync_module
    from octop.infra.mobile_access.access import resolve_mobile_user

    await company.center.user_manager.set_permissions(company.alice.username, ["experts", "skills"])
    publish(company, definition("skill", "qa"), definition(skill_refs=["qa"]))
    app = FastAPI()
    app.include_router(identity_router, prefix="/api")
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_server] = lambda: company.center

    def device_user(request: Request):
        return resolve_mobile_user(
            company.center,
            request.headers["Authorization"][7:],
            path=request.url.path,
            method=request.method,
        )

    app.dependency_overrides[current_user] = device_user

    @app.exception_handler(OctopError)
    async def error(_request, exc):
        return JSONResponse(status_code=exc.status, content=exc.to_envelope())

    original_client = httpx.AsyncClient

    class LocalClient(original_client):
        def __init__(self, *args, **kwargs):
            kwargs.setdefault("transport", httpx.ASGITransport(app))
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", LocalClient)
    node = company.nodes[0]
    client = EnterpriseClient(node.server)
    challenge = await client.begin("Isolated HTTP device")
    await company.catalog.center.approve(company.alice, challenge["user_code"])
    _, user = await client.poll(challenge["login_id"])
    assert user is not None
    monkeypatch.setattr(sync_module, "client_for", lambda _: client)
    state = await node.sync.sync(user)
    assert {item["kind"] for item in state["resources"]} == {"expert", "skill"}
    assert all(item["status"] == "current" for item in state["resources"])
    expert = next(item for item in state["resources"] if item["kind"] == "expert")
    assert node.registry.workspaces[expert["target_id"]].files["SOUL.md"] == b"company v1"
    assert (
        len(json.loads(node.server.services.agent_repo.get(expert["target_id"]).skill_package_ids))
        == 1
    )


@pytest.mark.parametrize("filename", ["@name", "@notes.md", "constructor", "__proto__"])
async def test_skill_local_at_sign_files_are_not_treated_as_metadata(company, filename):
    node = company.nodes[0]
    publish(company, definition("skill", "qa"))
    await node.sync.sync(node.user)
    record = local(node, "qa")
    directory = node.sync.packages.package_skills_dir(record["target_id"]) / record["slug"]
    (directory / filename).write_bytes(b"personal file; keep exact bytes")
    publish(company, definition("skill", "qa", files={"SKILL.md": b"company update"}))
    result = await node.sync.sync(node.user)
    assert result["resources"][0]["status"] == "current"
    assert (directory / filename).read_bytes() == b"personal file; keep exact bytes"


async def test_skill_file_and_profile_name_conflicts_have_distinct_choices(company):
    node = company.nodes[0]
    publish(company, definition("skill", "qa", files={"SKILL.md": b"base", "@name": b"base note"}))
    await node.sync.sync(node.user)
    record = local(node, "qa")
    directory = node.sync.packages.package_skills_dir(record["target_id"]) / record["slug"]
    (directory / "@name").write_bytes(b"personal note")
    package = node.server.services.skill_package_repo.get(record["target_id"])
    assert node.server.services.skill_package_repo.compare_and_update(
        package.id,
        str(node.user.id),
        package.name,
        package.description,
        "Personal name",
        package.description,
    )
    publish(
        company,
        definition(
            "skill",
            "qa",
            display_name="Company name",
            files={"SKILL.md": b"updated", "@name": b"company note"},
        ),
    )
    await node.sync.sync(node.user)
    detail = await node.sync.detail(node.user, "qa")
    assert {c["path"] for c in detail["conflicts"]} == {"@name", ":name"}
    await node.sync.resolve(
        node.user, "qa", detail["ticket"], {"@name": "local", ":name": "remote"}
    )
    assert (directory / "@name").read_bytes() == b"personal note"
    assert node.server.services.skill_package_repo.get(package.id).name.startswith("Company name")
