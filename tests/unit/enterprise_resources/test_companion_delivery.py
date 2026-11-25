import base64
import hashlib
import plistlib
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from octop.infra.enterprise_resources.companion_installers import (
    installer_directory,
    installer_for,
    register_installer,
)
from octop.infra.enterprise_resources.member_access import MemberSelection, access_for
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.setup import companion as launcher_module
from octop.infra.setup import companion_package
from octop.infra.setup.companion import CompanionLauncher, validate_archive
from octop.infra.setup.companion_package import BUNDLE_ID, CompanionInstaller


@pytest.fixture
def signed(company, monkeypatch, tmp_path):
    key = Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    monkeypatch.setattr(companion_package, "PUBLIC_KEY", base64.b64encode(pub).decode())
    path = tmp_path / "Dora-macos-universal-0.4.0.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(
            "哆啦.app/Contents/Info.plist",
            plistlib.dumps(
                {"CFBundleIdentifier": BUNDLE_ID, "CFBundleShortVersionString": "0.4.0"}
            ),
        )
    metadata = CompanionInstaller(
        filename=path.name,
        version="0.4.0",
        size=path.stat().st_size,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        signature="A" * 88,
    )
    metadata = metadata.model_copy(
        update={"signature": base64.b64encode(key.sign(metadata.signed_bytes())).decode()}
    )
    access = access_for(company.center)
    access.ensure_default()
    state = access.admin(company.admin)
    access.save(
        company.admin, [MemberSelection(user_id=company.alice.id, companion=True)], state["etag"]
    )
    directory = installer_directory(company.center)
    directory.mkdir(parents=True)
    (directory / path.name).write_bytes(path.read_bytes())
    register_installer(company.center, company.admin, metadata)
    return SimpleNamespace(key=key, metadata=metadata, path=path, company=company)


def test_private_installer_requires_an_enabled_member_and_pinned_signature(signed):
    m, p = installer_for(signed.company.center, signed.company.alice)
    assert m.sha256 == signed.metadata.sha256 and p.is_file()
    with pytest.raises(OctopError):
        installer_for(signed.company.center, signed.company.bob)
    with pytest.raises(OctopError):
        signed.metadata.model_copy(update={"sha256": "f" * 64}).verify()
    with pytest.raises(OctopError):
        signed.metadata.model_copy(update={"signature": "A" * 88}).verify()


def test_archive_validation_rejects_escape_and_symlink_entries(tmp_path):
    for name, link in [
        ("哆啦.app/../../outside", False),
        ("/absolute/path", False),
        ("哆啦.app/link", True),
    ]:
        path = tmp_path / "invalid.zip"
        with zipfile.ZipFile(path, "w") as z:
            info = zipfile.ZipInfo(name)
            if link:
                info.external_attr = 0o120777 << 16
            z.writestr(info, b"payload")
        with pytest.raises(OctopError):
            validate_archive(path)


async def test_download_checks_size_and_hash_and_never_sends_credentials_to_redirects(
    signed, monkeypatch, tmp_path
):
    node = signed.company.nodes[0]
    root = node.server.paths.root
    payload = signed.path.read_bytes()
    requests = []
    client = SimpleNamespace(
        authority="https://company.example", _state=lambda uid: {"token": "private-company-grant"}
    )
    monkeypatch.setattr(launcher_module, "client_for", lambda server: client)
    real_client = httpx.AsyncClient

    def upstream(request):
        requests.append(request)
        assert request.headers["authorization"] == "Bearer private-company-grant"
        return httpx.Response(200, content=payload)

    monkeypatch.setattr(
        launcher_module.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(upstream), **kwargs),
    )
    target = await CompanionLauncher(node.server)._download(node.user, signed.metadata)
    assert target.read_bytes() == payload
    assert all(
        str(r.url) == "https://company.example/api/enterprise/companion/installer/file"
        for r in requests
    )
    target.unlink()

    def redirect(request):
        return httpx.Response(302, headers={"Location": "https://untrusted.example/private"})

    monkeypatch.setattr(
        launcher_module.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(redirect), **kwargs),
    )
    with pytest.raises(OctopError):
        await CompanionLauncher(node.server)._download(node.user, signed.metadata)
    assert not list((root / "downloads/companion").glob("*.part"))


async def test_launch_is_denied_before_install_or_process_execution(signed, monkeypatch):
    monkeypatch.setattr(launcher_module.sys, "platform", "darwin")
    monkeypatch.setattr(launcher_module.os, "getuid", lambda: 1000, raising=False)
    monkeypatch.setattr(
        launcher_module, "companion_access", AsyncMock(return_value={"allowed": False})
    )
    run = AsyncMock()
    monkeypatch.setattr(launcher_module.asyncio, "to_thread", run)
    with pytest.raises(OctopError) as failure:
        await CompanionLauncher(signed.company.nodes[0].server).launch(signed.company.nodes[0].user)
    assert failure.value.code == ErrorCode.COMPANION_ACCESS_DENIED
    assert not run.called


async def test_installed_pet_opens_as_an_independent_application_without_main_process_parenting(
    signed, monkeypatch, tmp_path
):
    node = signed.company.nodes[0]
    monkeypatch.setattr(launcher_module, "os", SimpleNamespace(getuid=lambda: 1000))
    home = tmp_path / "home"
    app = home / "Applications/哆啦.app"
    (app / "Contents").mkdir(parents=True)
    (app / "Contents/Info.plist").write_bytes(
        plistlib.dumps({"CFBundleIdentifier": BUNDLE_ID, "CFBundleShortVersionString": "0.4.0"})
    )
    monkeypatch.setattr(launcher_module.Path, "home", lambda: home)
    monkeypatch.setattr(launcher_module.sys, "platform", "darwin")
    monkeypatch.setattr(
        launcher_module, "companion_access", AsyncMock(return_value={"allowed": True})
    )
    remote = AsyncMock(return_value=signed.metadata.model_dump())
    client = SimpleNamespace(_state=lambda uid: {"token": "company-private"}, _remote=remote)
    monkeypatch.setattr(launcher_module, "client_for", lambda server: client)
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=1 if command[0].endswith("pgrep") else 0)

    monkeypatch.setattr(launcher_module.subprocess, "run", run)
    result = await CompanionLauncher(node.server).launch(node.user)
    assert result["opened"] and not result["installed"]
    assert calls[-1] == ["/usr/bin/open", "-a", str(app), "--args", "--show-chat"]
    assert all("token" not in str(command).lower() for command in calls)


def test_windows_and_artwork_channels_preserve_existing_mac_manifest(signed):
    before = installer_for(signed.company.center, signed.company.alice)[0]
    directory = installer_directory(signed.company.center)
    for platform in ("windows-amd64", "artwork"):
        value = before.model_copy(update={"filename": f"Dora-{platform}-0.4.0.zip"})
        value = value.model_copy(
            update={"signature": base64.b64encode(signed.key.sign(value.signed_bytes())).decode()}
        )
        (directory / value.filename).write_bytes(signed.path.read_bytes())
        register_installer(signed.company.center, signed.company.admin, value, platform)
        assert installer_for(signed.company.center, signed.company.alice, platform)[0] == value
        with pytest.raises(OctopError):
            installer_for(signed.company.center, signed.company.bob, platform)
    assert installer_for(signed.company.center, signed.company.alice)[0] == before


def test_windows_install_preserves_data_and_rejects_alias_paths(tmp_path):
    import json

    from octop.infra.setup import companion_windows

    archive = tmp_path / "windows.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("Dora/Dora.exe", b"fixture executable, never run")
        bundle.writestr(
            "Dora/companion-version.json", json.dumps({"bundle_id": BUNDLE_ID, "version": "0.8.0"})
        )
    metadata = CompanionInstaller(
        filename=archive.name,
        version="0.8.0",
        size=archive.stat().st_size,
        sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
        signature="A" * 88,
    )
    data = tmp_path / "OctopCompanion/Data/history"
    data.parent.mkdir(parents=True)
    data.write_text("existing member history")
    target = companion_windows.install(archive, metadata, tmp_path / "Programs")
    assert companion_windows.installed_version(target) == (0, 8, 0)
    assert data.read_text() == "existing member history"
    for name in (
        "Dora/../../outside",
        "Dora/NUL.txt",
        "Dora/file:stream",
        "Dora/trailing.",
        "Dora/a\\b",
    ):
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr(name, b"bad")
        with pytest.raises(OctopError):
            companion_windows.validate_archive(archive)
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("Dora/File", b"one")
        bundle.writestr("Dora/file", b"two")
    with pytest.raises(OctopError):
        companion_windows.validate_archive(archive)
