"""Pinned package installs/update/rollback without installing a real CLI."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import io
import json
import stat
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from octop.infra.agents.native_cli.config import NativeCLIError
from octop.infra.agents.native_cli.managed import ManagedCLI, extract_managed
from octop.infra.utils.paths import PathLayout


def sha(value):
    return hashlib.sha256(value).hexdigest()


def archive(value, *, name="bin/codex-acp", symlink=False):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as target:
        member = zipfile.ZipInfo(name)
        if symlink:
            member.external_attr = (stat.S_IFLNK | 0o777) << 16
        target.writestr(member, value)
    return data.getvalue()


class Settings:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.values[key] = value

    def delete(self, key):
        self.values.pop(key, None)


class Runners:
    def __init__(self):
        self.definitions = {
            1: {
                "codex": {
                    "enabled": True,
                    "command": "existing-custom-cli",
                    "args": ["keep"],
                    "env": {"CUSTOM": "preserve"},
                }
            }
        }

    def load_runners(self, user_id):
        return copy.deepcopy(self.definitions.get(user_id, {}))

    def save_runners(self, user_id, value):
        self.definitions[user_id] = copy.deepcopy(value)

    def save_managed_runner(self, user_id, name, value):
        self.definitions.setdefault(user_id, {})[name] = copy.deepcopy(value)


def fixture(tmp_path, *, bad=False):
    settings = Settings()
    runners = Runners()
    held = set()
    active = set()
    manager = SimpleNamespace(
        paths=PathLayout(tmp_path),
        _repos=SimpleNamespace(settings_repo=settings),
        acp_settings=runners,
        list_agents=lambda uid: [SimpleNamespace(agent_id="expert")],
        get_config=lambda aid: {"native_cli": {"runner": "managed_codex"}},
        is_agent_active=lambda aid: aid in active,
        teams=SimpleNamespace(jobs=SimpleNamespace(is_member_busy=lambda aid: False)),
        native_cli=SimpleNamespace(
            maintenance=asyncio.Lock(), close_agent=lambda aid: asyncio.sleep(0)
        ),
        _team_processor=None,
    )

    def reserve(aid):
        if aid in held or aid in active:
            return False
        held.add(aid)
        return True

    manager.try_begin_runtime_update = reserve
    manager.end_runtime_update = lambda aid: held.discard(aid)
    license_bytes = b"Synthetic Apache-2.0 license for package test"
    payloads = {"one": archive(b"fake-v1"), "two": archive(b"fake-v2"), "license": license_bytes}
    if bad:
        payloads["one"] = archive(b"bad", name="../outside")
    versions = {}
    for version, key in [("1.0.0", "one"), ("2.0.0", "two")]:
        versions[version] = {
            "license_url": "https://fixture.example/license",
            "license_sha256": sha(license_bytes),
            "release_url": "https://fixture.example/release",
            "platforms": {
                "fixture": {
                    "url": "https://fixture.example/" + key,
                    "sha256": sha(payloads[key]),
                    "size": len(payloads[key]),
                    "archive": "zip",
                    "binary": "codex-acp",
                }
            },
        }
    catalog = {
        "packages": {
            "codex_acp": {
                "label": "Codex ACP",
                "runner_name": "managed_codex",
                "repository": "https://github.com/zed-industries/codex-acp",
                "license": "Apache-2.0",
                "versions": versions,
            }
        }
    }

    async def download(url, destination, *, size_limit):
        value = payloads[url.rsplit("/", 1)[-1]]
        await asyncio.to_thread(destination.write_bytes, value)

    service = ManagedCLI(manager, catalog=catalog, platform_id="fixture", downloader=download)
    return service, manager, active, payloads


async def install(service, user, version):
    await service.install(user, "codex_acp", version)
    await service.jobs[(user, "codex_acp")]
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_install_activate_update_rollback_preserves_original_cli_and_user_data(tmp_path):
    service, manager, _, _ = fixture(tmp_path)
    marker = tmp_path / "current-user-data.txt"
    marker.write_text("new conversation remains")
    before = manager.acp_settings.load_runners(1)["codex"]
    await install(service, 1, "1.0.0")
    assert "managed_codex" not in manager.acp_settings.load_runners(1)
    await service.activate(1, "codex_acp", "1.0.0")
    first = manager.acp_settings.load_runners(1)["managed_codex"]["command"]
    await install(service, 1, "2.0.0")
    await service.activate(1, "codex_acp", "2.0.0")
    second = manager.acp_settings.load_runners(1)["managed_codex"]["command"]
    assert first != second and Path(first).is_file() and Path(second).is_file()
    await service.rollback(1, "codex_acp")
    assert manager.acp_settings.load_runners(1)["managed_codex"]["command"] == first
    assert manager.acp_settings.load_runners(1)["codex"] == before
    assert marker.read_text() == "new conversation remains"
    assert Path(first).resolve().is_relative_to((tmp_path / "managed-cli" / "1").resolve())
    assert (Path(first).parent.parent / "OCTOP-UPSTREAM-LICENSE.txt").is_file()


@pytest.mark.asyncio
async def test_hash_failure_does_not_install_or_modify_runner(tmp_path):
    service, manager, _, payloads = fixture(tmp_path)
    payloads["one"] = b"tampered"
    before = copy.deepcopy(manager.acp_settings.definitions)
    await install(service, 1, "1.0.0")
    status = (await service.status(1))[0]
    assert status["state"]["phase"] == "failed"
    assert status["state"]["error_code"] == "managed_integrity"
    assert not status["installed"] and manager.acp_settings.definitions == before


@pytest.mark.asyncio
async def test_unsafe_archive_rejected_after_correct_hash(tmp_path):
    service, manager, _, _ = fixture(tmp_path, bad=True)
    await install(service, 1, "1.0.0")
    status = (await service.status(1))[0]
    assert status["state"]["error_code"] == "managed_unsafe_archive"
    assert not status["installed"] and not (tmp_path / "outside").exists()


@pytest.mark.asyncio
async def test_modified_binary_or_manual_runner_is_preserved(tmp_path):
    service, manager, _, _ = fixture(tmp_path)
    await install(service, 1, "1.0.0")
    await service.activate(1, "codex_acp", "1.0.0")
    await install(service, 1, "2.0.0")
    manager.acp_settings.definitions[1]["managed_codex"]["command"] = "manually-changed-command"
    with pytest.raises(NativeCLIError) as error:
        await service.activate(1, "codex_acp", "2.0.0")
    assert error.value.code == "managed_runner_changed"
    assert (
        manager.acp_settings.definitions[1]["managed_codex"]["command"]
        == "manually-changed-command"
    )
    record = await service._value("managed_cli.installed.1.codex_acp")
    Path(record["2.0.0"]["binary"]).write_bytes(b"manual binary change")
    with pytest.raises(NativeCLIError) as error:
        await service.activate(1, "codex_acp", "2.0.0")
    assert error.value.code == "managed_modified"


@pytest.mark.asyncio
async def test_busy_update_and_other_account_cannot_change_active_version(tmp_path):
    service, manager, active, _ = fixture(tmp_path)
    await install(service, 1, "1.0.0")
    await install(service, 1, "2.0.0")
    await service.activate(1, "codex_acp", "1.0.0")
    active.add("expert")
    with pytest.raises(NativeCLIError) as error:
        await service.activate(1, "codex_acp", "2.0.0")
    assert error.value.code == "busy"
    assert (await service.status(1))[0]["active_version"] == "1.0.0"
    assert (await service.status(2))[0]["installed"] == []
    with pytest.raises(NativeCLIError) as error:
        await service.activate(2, "codex_acp", "1.0.0")
    assert error.value.code == "managed_not_installed"


def test_archive_links_rejected_without_creating_symlink(tmp_path):
    path = tmp_path / "fixture.zip"
    path.write_bytes(archive(b"target", name="codex-acp", symlink=True))
    with pytest.raises(NativeCLIError) as error:
        extract_managed(path, tmp_path / "out", "zip", "codex-acp")
    assert error.value.code == "managed_unsafe_archive"


def test_reviewed_catalog_pins_all_versions_platforms_and_license():
    path = (
        Path(__file__).resolve().parents[4]
        / "src"
        / "octop"
        / "infra"
        / "agents"
        / "native_cli"
        / "managed_catalog.json"
    )
    data = json.loads(path.read_text())
    package = data["packages"]["codex_acp"]
    assert package["license"] == "Apache-2.0"
    assert set(package["versions"]) >= {"0.15.0", "0.16.0"}
    for version, row in package["versions"].items():
        assert len(row["license_sha256"]) == 64 and version in row["license_url"]
        for platform in ["darwin-arm64", "darwin-amd64", "windows-amd64"]:
            asset = row["platforms"][platform]
            assert len(asset["sha256"]) == 64 and version in asset["url"]
            assert asset["size"] > 0 and asset["url"].startswith(
                "https://github.com/zed-industries/codex-acp/"
            )
