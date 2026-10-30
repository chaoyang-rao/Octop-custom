"""Expert duplication and CLI reuse use temporary state and a fake harness."""

from __future__ import annotations

import json

from tests.support.auth import create_agent


async def test_copy_keeps_role_and_skills_but_isolates_identity_and_private_state(env_with_agent):
    client, srv, auth, source_id = env_with_agent
    registry = srv.app_runtime.agent_registry
    workspace = registry.workspace_for_agent(source_id)
    await workspace.aupload_many(
        [
            ("SOUL.md", b"Source role instructions"),
            ("USER.md", b"private user notes"),
            ("MEMORY.md", b"remembered conversation"),
            ("skills/demo/SKILL.md", b"---\nname: demo\ndescription: Demo\n---\nDo the role task."),
            (".octop/auth/token.json", b"private login"),
            (
                ".octop/manifest.json",
                json.dumps(
                    {
                        "id": source_id,
                        "welcome_message": {"zh": "Hello role"},
                        "quick_prompts": [{"prompt": {"zh": "Plan"}}],
                    }
                ).encode(),
            ),
        ]
    )
    source = registry.get_row(source_id)
    before_cfg = source.config_json
    r = await client.post(f"/api/agents/{source_id}/copy", headers=auth, json={})
    assert r.status_code == 201, r.text
    new_id = r.json()["agent_id"]
    assert new_id != source_id
    new = registry.get_row(new_id)
    assert new.user_id == source.user_id and not new.is_shared
    assert registry.get_row(source_id).config_json == before_cfg
    assert json.loads(new.config_json)["workspace_dir"] != json.loads(before_cfg)["workspace_dir"]
    assert json.loads(new.config_json)["avatar"] != json.loads(before_cfg)["avatar"]
    copied = registry.workspace_for_agent(new_id)
    assert await copied.adownload_bytes("SOUL.md") == b"Source role instructions"
    assert await copied.adownload_bytes(".octop/skills/demo/SKILL.md") is not None
    assert await copied.adownload_bytes("MEMORY.md") != b"remembered conversation"
    assert await copied.adownload_bytes("USER.md") != b"private user notes"
    assert await copied.adownload_bytes(".octop/auth/token.json") is None
    manifest = json.loads(await copied.adownload_bytes(".octop/manifest.json"))
    assert manifest["id"] == new_id
    assert manifest["welcome_message"]["zh"] == "Hello role"
    assert not srv.services.thread_repo.list_ids_for_agent(new_id)
    again = await client.post(f"/api/agents/{source_id}/copy", headers=auth, json={})
    assert again.status_code == 201 and again.json()["name"] != new.name


async def test_copy_custom_name_conflict_and_foreign_source(env_alice_bob_agent):
    client, srv, alice, bob, source_id = env_alice_bob_agent
    denied = await client.post(f"/api/agents/{source_id}/copy", headers=bob, json={})
    assert denied.status_code == 403
    first = await client.post(
        f"/api/agents/{source_id}/copy", headers=alice, json={"name": "Role copy"}
    )
    assert first.status_code == 201, first.text
    conflict = await client.post(
        f"/api/agents/{source_id}/copy", headers=alice, json={"name": "Role copy"}
    )
    assert conflict.status_code == 409


async def test_cli_reuse_preserves_target_settings_and_global_definitions(env_with_agent):
    client, srv, auth, source_id = env_with_agent
    registry = srv.app_runtime.agent_registry
    target = await create_agent(client, auth, name="Target")
    cfg = registry.get_config(source_id)
    cfg["acp"] = {"tool_enabled": True}
    cfg["tools_disabled"] = ["acp_runner", "web_fetch"]
    srv.services.agent_repo.update_config(source_id, config_json=json.dumps(cfg))
    target_cfg = registry.get_config(target)
    target_cfg.update(temperature=0.7, tools_disabled=["execute"], acp={"tool_enabled": False})
    srv.services.agent_repo.update_config(target, config_json=json.dumps(target_cfg))
    shared_before = registry.acp_settings.load_runners(registry.get_row(source_id).user_id)
    r = await client.post(
        f"/api/agents/{source_id}/cli/reuse", headers=auth, json={"agent_ids": [target, target]}
    )
    assert r.status_code == 200, r.text
    assert r.json()["agent_ids"] == [target] and r.json()["tool_enabled"] is True
    result = registry.get_config(target)
    assert result["acp"] == {"tool_enabled": True}
    assert result["temperature"] == 0.7
    assert result["tools_disabled"] == ["acp_runner", "execute"]
    assert result["workspace_dir"] == target_cfg["workspace_dir"]
    assert registry.acp_settings.load_runners(registry.get_row(source_id).user_id) == shared_before


async def test_cli_reuse_checks_entire_selection_before_changing_rows(env_alice_bob_agent):
    client, srv, alice, bob, source_id = env_alice_bob_agent
    target = await create_agent(client, alice, name="Alice target")
    foreign = await create_agent(client, bob, name="Bob target")
    before = srv.services.agent_repo.get(target).config_json
    r = await client.post(
        f"/api/agents/{source_id}/cli/reuse", headers=alice, json={"agent_ids": [target, foreign]}
    )
    assert r.status_code == 403
    assert srv.services.agent_repo.get(target).config_json == before


async def test_cli_reuse_rejects_busy_targets_without_cancelling_them(env_with_agent):
    client, srv, auth, source_id = env_with_agent
    registry = srv.app_runtime.agent_registry
    target = await create_agent(client, auth, name="Busy target")
    before = registry.get_row(target).config_json
    await registry._begin_invocation(target, "busy-thread")
    try:
        r = await client.post(
            f"/api/agents/{source_id}/cli/reuse", headers=auth, json={"agent_ids": [target]}
        )
        assert r.status_code == 409, r.text
        assert registry.is_agent_active(target)
        assert registry.get_row(target).config_json == before
    finally:
        registry._end_invocation(target, "busy-thread")


async def test_copy_and_cli_reuse_have_readable_typed_api_docs(env_with_agent):
    client, _srv, _auth, _source_id = env_with_agent
    schema = client._transport.app.openapi()
    copied = schema["paths"]["/api/agents/{agent_id}/copy"]["post"]
    reused = schema["paths"]["/api/agents/{agent_id}/cli/reuse"]["post"]
    assert copied["summary"] and copied["description"]
    assert copied["responses"]["201"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "ExpertCopyResult"
    )
    assert reused["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "CliReuseResult"
    )
