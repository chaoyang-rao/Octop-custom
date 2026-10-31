"""Portable resource batches use new IDs and preserve local trust boundaries."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from deepagents.backends.filesystem import FilesystemBackend
from octop_harness.backends.workspace import BackendWorkspace
from tests.unit.conversations.test_conversations import make_zip, seed
from tests.unit.tasks.test_task_manager import setup as setup

from octop.infra.conversations.archives import read_zip
from octop.infra.conversations.models import ExportSelection, ImportSelection


async def portable_agents(e, tmp_path):
    workspaces = {}
    specs = []

    def workspace(agent_id):
        if agent_id not in workspaces:
            root = tmp_path / agent_id
            workspaces[agent_id] = BackendWorkspace(
                FilesystemBackend(root_dir=root, virtual_mode=True), root
            )
        return workspaces[agent_id]

    async def create(spec, *, workspace_initializer):
        specs.append(spec)
        e.repos.agent_repo.create(
            agent_id=spec.agent_id,
            user_id=spec.user_id,
            name=spec.name,
            description=spec.description,
            system_prompt=spec.system_prompt,
            config_json=json.dumps(spec.config),
            kind=spec.kind,
        )
        row = e.repos.agent_repo.get(spec.agent_id)
        await workspace_initializer(row, workspace(spec.agent_id))
        return row

    async def delete(agent_id):
        e.repos.agent_repo.delete(agent_id)

    e.agents.workspace_for_agent = workspace
    e.agents.create = create
    e.agents.delete = delete
    return SimpleNamespace(workspace=workspace, specs=specs)


@pytest.mark.asyncio
async def test_portable_export_import_excludes_auth_and_cli_and_does_not_overwrite(setup, tmp_path):
    e = setup
    s = await seed(e)
    p = await portable_agents(e, tmp_path)
    source = p.workspace("a")
    await source.aupload_many(
        [
            ("SOUL.md", b"Helpful expert"),
            ("notes/report.txt", b"user content"),
            (".octop/auth/login.json", b"private-login"),
            (".env", b"PRIVATE_KEY=private-env"),
            ("keys/key.pem", b"private-pem"),
            (
                "skills/local/SKILL.md",
                b"---\nname: local\ndescription: A local skill\n---\nUser-authored skill",
            ),
        ]
    )
    with e.db.transaction() as conn:
        conn.execute(
            "UPDATE agents SET system_prompt=?,config_json=? WHERE agent_id='a'",
            (
                "Help the user. api_key=profile-secret",
                json.dumps(
                    {
                        "native_cli": {
                            "enabled": True,
                            "argv": ["foreign-command", "--token", "private-cli"],
                        },
                        "backend": {"root_dir": "host-sensitive"},
                        "acp": {"runners": {"secret": "private-acp"}},
                    }
                ),
            ),
        )
    data = await s.transfer.export(
        e.uid, ExportSelection(agent_ids=["a"], include_files=True, include_conversations=True)
    )
    entries = read_zip(data)
    rendered = b" ".join(entries.values())
    for secret in (
        b"private-login",
        b"private-env",
        b"private-pem",
        b"private-cli",
        b"private-acp",
        b"profile-secret",
        b"host-sensitive",
    ):
        assert secret not in rendered
    assert b"user content" in rendered and b"User-authored skill" in rendered
    assert "agents/a/workspace/.env" not in entries
    preview = await s.transfer.stage(e.uid, data)
    assert preview["items"][0]["name_conflict"]
    result = await s.transfer.confirm(
        e.uid, preview["id"], ImportSelection(keys=["a"], include_files=True)
    )
    assert len(result["agents"]) == 1 and result["agents"][0]["name"] != "a"
    target = result["agents"][0]["agent_id"]
    assert target != "a" and e.repos.agent_repo.get("a").name == "a"
    assert p.specs[0].config == {} and p.specs[0].icon is None
    assert p.specs[0].mcp_servers == [] and p.specs[0].knowledge_base_ids == []
    assert await p.workspace(target).aread_text("notes/report.txt") == "user content"
    assert (
        len(result["threads"]) == 1
        and e.repos.thread_repo.get(result["threads"][0]["thread_id"]).archived
    )
    assert e.gateway.thread_registry.get_bound_thread_id(s.key) == s.thread_id
    assert s.calls == []


@pytest.mark.asyncio
async def test_public_agent_contract_is_whitelisted_and_locked_origin_stays_locked(setup, tmp_path):
    e = setup
    s = await seed(e)
    p = await portable_agents(e, tmp_path)
    data = make_zip(
        {
            "openbot-import.json": {
                "version": 1,
                "agents": [
                    {
                        "key": "source",
                        "name": "Imported",
                        "instructions": "Reviewed expert instructions",
                        "command": "foreign-command",
                        "env": {"TOKEN": "foreign-secret"},
                        "access": "full",
                    }
                ],
                "settings": {"api_key": "foreign-secret"},
            },
            "agents/source/skills/protected/SKILL.md": b"---\nname: protected\ndescription: Example\nlocked: true\norigin: existing-local-package\n---\nAllowed skill body",
        }
    )
    preview = await s.transfer.stage(e.uid, data)
    assert preview["warnings"] == ["foreign_settings_omitted"]
    result = await s.transfer.confirm(e.uid, preview["id"], ImportSelection(keys=["source"]))
    assert result["warnings"] == ["foreign_settings_omitted", "locked_skill_preserved"]
    spec = p.specs[0]
    assert (
        spec.config == {}
        and spec.default_model is None
        and spec.system_prompt == "Reviewed expert instructions"
    )
    manifest = await p.workspace(result["agents"][0]["agent_id"]).aread_text(
        "skills/protected/SKILL.md"
    )
    assert "locked: true" in manifest and "origin: import-" in manifest
    assert "existing-local-package" not in manifest and "foreign-command" not in json.dumps(
        spec.config
    )


@pytest.mark.asyncio
async def test_transfer_export_honors_current_package_copy_and_download_policy(setup, tmp_path):
    e = setup
    s = await seed(e)
    p = await portable_agents(e, tmp_path)
    await p.workspace("a").aupload_bytes(
        "skills/restricted/SKILL.md",
        b"---\nname: restricted\ndescription: Policy protected\norigin: missing-package\nlocked: true\n---\nDo not redistribute",
    )
    archive = read_zip(await s.transfer.export(e.uid, ExportSelection(agent_ids=["a"])))
    assert all("restricted" not in path for path in archive)
    manifest = json.loads(archive["octop-transfer.json"])
    assert "skill_policy_omitted" in manifest["warnings"]


@pytest.mark.asyncio
async def test_transfer_failure_rolls_back_only_new_expert_ids(setup, tmp_path):
    e = setup
    s = await seed(e)
    await portable_agents(e, tmp_path)
    original_create = e.agents.create

    async def fail_second(spec, **kwargs):
        if spec.name == "Fail":
            raise RuntimeError("fake storage unavailable")
        return await original_create(spec, **kwargs)

    e.agents.create = fail_second
    data = make_zip(
        {
            "octop-transfer.json": {
                "format": "octop-user-transfer",
                "version": 1,
                "agents": [{"key": "new", "name": "New"}, {"key": "fail", "name": "Fail"}],
            }
        }
    )
    preview = await s.transfer.stage(e.uid, data)
    with pytest.raises(RuntimeError):
        await s.transfer.confirm(e.uid, preview["id"], ImportSelection(keys=["new", "fail"]))
    assert {row.agent_id for row in e.repos.agent_repo.list_by_user(e.uid)} == {"a", "b"}
    assert e.repos.thread_repo.get(s.thread_id) is not None
    assert e.repos.conversation_repo.preview(preview["id"], e.uid)["state"] == "failed"
