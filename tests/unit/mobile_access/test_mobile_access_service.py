"""Owner-approved pairing, persisted revocation and credential redaction."""

from types import SimpleNamespace

import pytest

from octop.infra.db.pool import SqlitePool
from octop.infra.db.repos.secrets import SecretRepo
from octop.infra.db.repos.settings import SettingsRepo
from octop.infra.errors import OctopError
from octop.infra.mobile_access.access import resolve_mobile_user
from octop.infra.mobile_access.service import MobileAccessService, validate_server_url
from octop.infra.users.identity import User


@pytest.fixture
def service(tmp_path):
    pool = SqlitePool(tmp_path / "test.db")
    with pool.connect() as conn:
        conn.executescript(
            "CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL); CREATE TABLE secrets(k TEXT PRIMARY KEY,v BLOB NOT NULL,created_at INTEGER NOT NULL,rotated_at INTEGER);"
        )
    yield MobileAccessService(SettingsRepo(pool), SecretRepo(pool))
    pool.close()


async def paired(service, scopes=None):
    request = await service.begin_pairing(name="My phone", platform="ios", network_key="local")
    await service.approve_pairing(
        user_id=1, code=request["user_code"], scopes=scopes or ["chat", "files", "notifications"]
    )
    return request, await service.exchange_pairing(
        pairing_secret=request["pairing_secret"], network_key="local"
    )


@pytest.mark.asyncio
async def test_pairing_requires_owner_approval_and_not_just_the_visible_code(service):
    request = await service.begin_pairing(name="My phone", platform="ios", network_key="local")
    pending = await service.exchange_pairing(
        pairing_secret=request["pairing_secret"], network_key="local"
    )
    assert pending["status"] == "pending" and "access_token" not in pending
    with pytest.raises(OctopError):
        await service.exchange_pairing(pairing_secret=request["user_code"], network_key="local")
    preview = await service.inspect_pairing(user_id=1, code=request["user_code"])
    assert preview["name"] == "My phone"
    device = await service.approve_pairing(user_id=1, code=request["user_code"], scopes=["chat"])
    with pytest.raises(OctopError):
        await service.approve_pairing(user_id=2, code=request["user_code"], scopes=["chat"])
    result = await service.exchange_pairing(
        pairing_secret=request["pairing_secret"], network_key="local"
    )
    assert result["device_id"] == device["device_id"]
    assert service.authenticate(result["access_token"]).user_id == 1
    assert await service.list_devices(2) == []


@pytest.mark.asyncio
async def test_tokens_are_hashed_and_exchange_result_is_encrypted(service):
    request, result = await paired(service)
    stored = service._settings.get("mobile_access.pending") + service._settings.get(
        "mobile_access.devices.1"
    )
    assert request["pairing_secret"] not in stored
    assert request["user_code"].replace("-", "") not in stored
    assert result["access_token"] not in stored
    assert "access_token" not in str(await service.list_devices(1))
    assert (
        await service.exchange_pairing(
            pairing_secret=request["pairing_secret"], network_key="local"
        )
        == result
    )
    with pytest.raises(OctopError):
        service.authenticate(
            result["access_token"][:-1] + ("X" if result["access_token"][-1] != "X" else "Y")
        )


@pytest.mark.asyncio
async def test_revocation_survives_restart_and_old_exchange_cannot_resurrect(service):
    request, result = await paired(service)
    await service.revoke(user_id=1, device_id=result["device_id"])
    restarted = MobileAccessService(service._settings, service._secrets)
    with pytest.raises(OctopError):
        restarted.authenticate(result["access_token"])
    with pytest.raises(OctopError):
        await restarted.exchange_pairing(
            pairing_secret=request["pairing_secret"], network_key="local"
        )
    assert (await restarted.list_devices(1))[0]["revoked_at"]


@pytest.mark.asyncio
async def test_push_token_is_encrypted_and_removed_on_revoke(service):
    _, result = await paired(service)
    await service.register_push(token=result["access_token"], platform="apns", push_token="a" * 64)
    assert "a" * 64 not in service._settings.get("mobile_access.devices.1")
    assert (await service.push_targets(1))[0]["token"] == "a" * 64
    await service.revoke(user_id=1, device_id=result["device_id"])
    assert await service.push_targets(1) == []


@pytest.mark.asyncio
async def test_device_never_inherits_admin_or_grants_lost_account_permissions(service):
    _, result = await paired(service, ["chat", "browser"])
    owner = User(id=1, username="admin", role="admin", display_name=None)
    server = SimpleNamespace(
        _mobile_access_service=service, user_manager=SimpleNamespace(get_by_id=lambda _: owner)
    )
    user = resolve_mobile_user(server, result["access_token"], path="/api/agents", method="GET")
    assert not user.is_admin and "providers" not in user.permissions
    with pytest.raises(OctopError):
        resolve_mobile_user(
            server, result["access_token"], path="/api/admin/voice/providers", method="GET"
        )
    owner.role = "user"
    owner.permissions = ["experts"]
    with pytest.raises(OctopError):
        resolve_mobile_user(
            server, result["access_token"], path="/api/browser-stream/ws", method="WS"
        )
    with pytest.raises(OctopError):
        resolve_mobile_user(server, result["access_token"])


@pytest.mark.parametrize(
    "url",
    [
        "http://192.168.1.3:8088",
        "https://user:secret@example.com",
        "https://example.com/#secret",
        "https://example.com/api",
        "file:///tmp/private",
    ],
)
def test_insecure_or_credential_bearing_server_urls_rejected(url):
    with pytest.raises(ValueError):
        validate_server_url(url)


@pytest.mark.parametrize(
    "url", ["https://octop.example.com", "http://127.0.0.1:8088", "http://[::1]:8088"]
)
def test_https_and_loopback_development_urls(url):
    assert validate_server_url(url) == url


def test_native_model_catalog_is_only_get_for_chat_scoped_device():
    from octop.infra.mobile_access.access import authorize_device_path
    from octop.infra.mobile_access.service import DeviceSession

    session = DeviceSession(1, "device", ("chat",), 9999999999)
    authorize_device_path(session, "/api/agents/A/native-cli/models", "GET")
    for path, method in [
        ("/api/agents/A/native-cli/models", "PUT"),
        ("/api/agents/A/native-cli/models", "POST"),
        ("/api/agents/A/native-cli/runner", "GET"),
        ("/api/native-cli/managed/install", "POST"),
        ("/api/agents/A/native-cli/mode", "PUT"),
    ]:
        with pytest.raises(OctopError):
            authorize_device_path(session, path, method)
