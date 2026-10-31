"""Reuse only the four explicit native settings, preserving legacy behavior."""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest

from octop.infra.agents.settings.acp import ACPSettingsStore
from octop.infra.agents.settings.cli_reuse import reuse_cli_config
from octop.infra.errors import OctopError


class Registry:
    def __init__(self, native=None):
        self.rows = {
            name: SimpleNamespace(agent_id=name, user_id=1, kind="expert", is_shared=False)
            for name in ["source", "a", "b"]
        }
        self.configs = {
            "source": {"acp": {"tool_enabled": True}},
            "a": {
                "workspace_dir": "keep",
                "native_cli": {"enabled": True, "runner": "old"},
                "temperature": 0.3,
            },
            "b": {"tools_disabled": ["execute"]},
        }
        if native is not None:
            self.configs["source"]["native_cli"] = native
        self.busy = set()
        self.changed = []
        self.teams = SimpleNamespace(jobs=SimpleNamespace(is_member_busy=lambda aid: False))
        self.acp_settings = SimpleNamespace(load_runners=lambda uid: {})

    def get_row(self, aid):
        return self.rows.get(aid)

    def get_config(self, aid):
        return copy.deepcopy(self.configs[aid])

    def is_agent_active(self, aid):
        return aid in self.busy

    async def update_config_json(self, aid, value):
        self.configs[aid] = json.loads(value)
        self.changed.append(aid)


@pytest.mark.asyncio
async def test_native_four_fields_reused_without_logins_installs_or_other_config():
    source = {
        "enabled": True,
        "runner": "managed_codex",
        "model_id": "selected",
        "mode_id": "read-only",
        "login_token": "synthetic-do-not-copy",
        "sessions": ["private"],
    }
    registry = Registry(source)
    await reuse_cli_config(registry, "source", ["a", "b"], user_id=1)
    expected = {key: source[key] for key in ["enabled", "runner", "model_id", "mode_id"]}
    assert registry.configs["a"]["native_cli"] == expected == registry.configs["b"]["native_cli"]
    assert (
        registry.configs["a"]["workspace_dir"] == "keep"
        and registry.configs["a"]["temperature"] == 0.3
    )
    assert "execute" in registry.configs["b"]["tools_disabled"]
    assert "synthetic-do-not-copy" not in json.dumps([registry.configs["a"], registry.configs["b"]])


@pytest.mark.asyncio
async def test_source_without_native_never_changes_target_native_mode():
    registry = Registry()
    before = copy.deepcopy(registry.configs["a"]["native_cli"])
    await reuse_cli_config(registry, "source", ["a"], user_id=1)
    assert registry.configs["a"]["native_cli"] == before


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["shared", "busy", "foreign"])
async def test_native_selection_validated_before_any_write(case):
    registry = Registry({"enabled": True, "runner": "codex"})
    if case == "shared":
        registry.rows["b"].is_shared = True
    elif case == "busy":
        registry.busy.add("b")
    else:
        registry.rows["b"].user_id = 2
    before = copy.deepcopy(registry.configs)
    with pytest.raises(OctopError):
        await reuse_cli_config(registry, "source", ["a", "b"], user_id=1)
    assert registry.changed == [] and registry.configs == before


def test_managed_runner_patch_keeps_all_other_raw_data():
    class Settings:
        def __init__(self):
            self.values = {}

        def get(self, key):
            return self.values.get(key)

        def set(self, key, value):
            self.values[key] = value

    settings = Settings()
    original = {
        "runners": {
            "custom": {
                "enabled": True,
                "extra_vendor_field": "keep",
                "env": {"PROFILE": "preserve"},
            },
            "qwen_code": {"enabled": False, "extra": "also keep"},
        },
        "schema_note": "preserve",
    }
    settings.values["acp_runners:user:1"] = json.dumps(original)
    store = ACPSettingsStore(settings_repo=settings, agents_repo=None)
    store.save_managed_runner(1, "managed_codex", {"enabled": True, "command": "managed"})
    value = json.loads(settings.values["acp_runners:user:1"])
    assert value["runners"]["custom"] == original["runners"]["custom"]
    assert value["runners"]["qwen_code"] == original["runners"]["qwen_code"]
    assert value["schema_note"] == "preserve"
