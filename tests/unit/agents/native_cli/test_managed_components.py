"""Pinned private runtimes, dependency trees and safe decoding without real CLI installs."""

from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import os
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest
from tests.unit.agents.native_cli.test_managed_packages import fixture, install, sha

from octop.api.routers.native_cli import ManagedArtifactView
from octop.infra.agents.native_cli.config import NativeCLIError
from octop.infra.agents.native_cli.managed_artifacts import (
    decode_brotli,
    extract_tree,
    locked_components,
    platform_matches,
    verify_artifact,
)


def zipped(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def sri(value):
    return "sha512-" + base64.b64encode(hashlib.sha512(value).digest()).decode()


def components(tmp_path):
    service, manager, active, payloads = fixture(tmp_path)
    payloads["node"] = zipped(
        {"node.exe": b"synthetic private runtime", "LICENSE": b"runtime license"}
    )
    runtime = {
        "url": "https://fixture.example/node",
        "size": len(payloads["node"]),
        "sha256": sha(payloads["node"]),
        "archive": "zip",
        "target": "runtime",
        "entry": "node.exe",
        "checks": {"LICENSE": sha(b"runtime license")},
    }
    for version, name in [("1.0.0", "one"), ("2.0.0", "two")]:
        payloads[name] = zipped(
            {
                "app/entry & note.js": ("script-" + version).encode(),
                "app/helper.js": b"protected helper",
            }
        )
        release = service.catalog["packages"]["codex_acp"]["versions"][version]
        release["runner_args"] = ["--acp"]
        release["platforms"]["fixture"] = {
            "url": "https://fixture.example/" + name,
            "size": len(payloads[name]),
            "sha256": "",
            "integrity": sri(payloads[name]),
            "archive": "zip",
            "entry": "app/entry & note.js",
            "runtime": copy.deepcopy(runtime),
        }
    return service, manager, active, payloads


@pytest.mark.asyncio
async def test_private_node_sri_updates_rollback_and_literal_script_args_without_running_packages(
    tmp_path, monkeypatch
):
    service, manager, _, _ = components(tmp_path)
    before_path = os.environ.get("PATH")
    before_home = os.environ.get("HOME")

    async def no_execution(*args, **kwargs):
        raise AssertionError(
            "Neither package scripts nor its runtime should execute for a plain JS package install"
        )

    monkeypatch.setattr("asyncio.create_subprocess_exec", no_execution)
    await install(service, 1, "1.0.0")
    await service.activate(1, "codex_acp", "1.0.0")
    first = manager.acp_settings.load_runners(1)["managed_codex"]
    assert Path(first["command"]).name == "node.exe"
    assert first["args"][0].endswith("entry & note.js") and first["args"][1:] == ["--acp"]
    assert Path(first["args"][0]).is_file()
    assert first["env"]["PATH"].startswith(str(Path(first["command"]).parent))
    await install(service, 1, "2.0.0")
    await service.activate(1, "codex_acp", "2.0.0")
    assert manager.acp_settings.load_runners(1)["managed_codex"]["command"] != first["command"]
    await service.rollback(1, "codex_acp")
    assert manager.acp_settings.load_runners(1)["managed_codex"] == first
    assert os.environ.get("PATH") == before_path and os.environ.get("HOME") == before_home


@pytest.mark.asyncio
async def test_dependency_tamper_and_manual_environment_changes_cannot_be_overwritten(tmp_path):
    service, manager, _, _ = components(tmp_path)
    await install(service, 1, "1.0.0")
    await service.activate(1, "codex_acp", "1.0.0")
    await install(service, 1, "2.0.0")
    record = (await service._value("managed_cli.installed.1.codex_acp"))["2.0.0"]
    helper = Path(record["directory"]) / "app" / "helper.js"
    helper.write_bytes(b"changed without altering the Node executable")
    with pytest.raises(NativeCLIError) as error:
        await service.activate(1, "codex_acp", "2.0.0")
    assert error.value.code == "managed_modified"
    helper.write_bytes(b"protected helper")
    manager.acp_settings.definitions[1]["managed_codex"]["env"]["CUSTOM"] = "manual-value"
    with pytest.raises(NativeCLIError) as error:
        await service.activate(1, "codex_acp", "2.0.0")
    assert error.value.code == "managed_runner_changed"
    assert manager.acp_settings.definitions[1]["managed_codex"]["env"]["CUSTOM"] == "manual-value"


def test_npm_sri_requires_exact_size_and_strong_digest(tmp_path):
    archive = tmp_path / "npm.tgz"
    archive.write_bytes(b"synthetic npm bytes")
    correct = {"size": archive.stat().st_size, "integrity": sri(archive.read_bytes())}
    verify_artifact(archive, correct)
    for wrong in [
        {**correct, "size": 1},
        {**correct, "integrity": sri(b"different")},
        {**correct, "integrity": "sha1-YQ=="},
    ]:
        with pytest.raises(NativeCLIError) as error:
            verify_artifact(archive, wrong)
        assert error.value.code == "managed_integrity"


@pytest.mark.parametrize("link", ["../lib/npm.js", "../../outside", "/absolute"])
def test_node_archive_can_skip_internal_links_but_never_creates_or_follows_them(tmp_path, link):
    archive = tmp_path / "runtime.tar.gz"
    with tarfile.open(archive, "w:gz") as target:
        entry = tarfile.TarInfo("node-v1/bin/node")
        entry.size = 4
        entry.mode = 0o755
        target.addfile(entry, io.BytesIO(b"node"))
        item = tarfile.TarInfo("node-v1/bin/npm")
        item.type = tarfile.SYMTYPE
        item.linkname = link
        target.addfile(item)
    destination = tmp_path / "private-node"
    if link == "../lib/npm.js":
        files = extract_tree(
            archive, destination, "tar.gz", strip_prefix="node-v1", skip_internal_links=True
        )
        assert [p.relative_to(destination).as_posix() for p in files] == ["bin/node"]
        assert not (destination / "bin" / "npm").exists()
    else:
        with pytest.raises(NativeCLIError) as error:
            extract_tree(
                archive, destination, "tar.gz", strip_prefix="node-v1", skip_internal_links=True
            )
        assert error.value.code == "managed_unsafe_archive"


@pytest.mark.parametrize(
    "platform,expected",
    [
        ("darwin-arm64", False),
        ("windows-amd64", False),
        ("linux-amd64", True),
        ("linux-musl-amd64", False),
    ],
)
def test_native_optional_dependency_platform_filter(platform, expected):
    assert (
        platform_matches({"os": ["linux"], "cpu": ["x64"], "libc": ["glibc"]}, platform) is expected
    )


def test_real_catalog_has_fixed_official_sources_node_and_complete_dependency_locks():
    root = Path(__file__).resolve().parents[4] / "src" / "octop" / "infra" / "agents" / "native_cli"
    catalog = json.loads((root / "managed_catalog.json").read_text())
    assert set(catalog["packages"]) == {
        "codex_acp",
        "pi",
        "claude",
        "opencode",
        "cline",
        "grok",
        "gemini",
        "cursor",
    }
    assert catalog["node_runtime"]["version"] == "24.22.2"
    for package in catalog["packages"].values():
        assert package["versions"] and package["runner_name"].startswith("managed_")
        for version, release in package["versions"].items():
            assert len(release["license_sha256"]) == 64
            for platform, artifact in release["platforms"].items():
                assert artifact["url"].startswith("https://") and artifact["size"] > 0
                view = ManagedArtifactView.model_validate(
                    {
                        **artifact,
                        "version": version,
                        "license_url": release["license_url"],
                        "license_sha256": release["license_sha256"],
                        "release_url": release["release_url"],
                    }
                )
                assert view.sha256 or view.integrity
                assert len(artifact.get("sha256", "")) == 64 or artifact["integrity"].startswith(
                    "sha512-"
                )
                if artifact.get("runtime"):
                    runtime = artifact["runtime"]
                    assert runtime["url"].startswith("https://nodejs.org/dist/v24.22.2/")
                    assert len(runtime["sha256"]) == 64 and len(runtime["checks"]["LICENSE"]) == 64
                if release.get("npm_lock"):
                    dependencies = locked_components(release, platform)
                    assert dependencies
                    assert all(
                        d["url"].startswith("https://registry.npmjs.org/")
                        and d["integrity"].startswith("sha512-")
                        for d in dependencies
                    )
    cursor = catalog["packages"]["cursor"]
    assert cursor["profile_files"]["cli-config.json"]["channel"] == "static"
    assert all(
        row["launch_command"].endswith("node.exe")
        for v in cursor["versions"].values()
        for p, row in v["platforms"].items()
        if p.startswith("windows")
    )


@pytest.mark.asyncio
@pytest.mark.skipif(
    shutil.which("node") is None, reason="Node unavailable for offline builtin-codec test"
)
async def test_real_node_builtin_brotli_codec_only_transforms_synthetic_data(tmp_path):
    node = Path(shutil.which("node"))
    source = tmp_path / "synthetic.br"
    target = tmp_path / "decoded.bin"
    payload = b"synthetic inert bytes; no CLI or login"
    subprocess.run(
        [
            str(node),
            "-e",
            "require('node:fs').writeFileSync(process.argv[1],require('node:zlib').brotliCompressSync(Buffer.from(process.argv[2])))",
            str(source),
            payload.decode(),
        ],
        check=True,
        capture_output=True,
    )
    await decode_brotli(node, source, target)
    assert target.read_bytes() == payload
