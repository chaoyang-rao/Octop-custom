"""Remote setup checks identity and preserves unrelated Tailscale mappings."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from tests.unit.mobile_access.test_mobile_access_service import service as service

from octop.infra.errors import OctopError
from octop.infra.mobile_access.remote import RemoteAccessService


@pytest.fixture
def remote(service):
    return RemoteAccessService(
        service,
        SimpleNamespace(port=8088, bind_host="127.0.0.1", tls=SimpleNamespace(enabled=False)),
    )


@pytest.mark.asyncio
async def test_diagnostic_requires_matching_host_and_never_sends_credentials(remote, monkeypatch):
    fingerprint = remote.access._host_fingerprint()
    identity = {"protocol": "octop-mobile-v1", "host_fingerprint": fingerprint}
    calls = []

    class Client:
        def __init__(self, **kwargs):
            assert kwargs.get("follow_redirects") is False and kwargs.get("verify", True) is True

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, **kwargs):
            calls.append((url, kwargs))
            return SimpleNamespace(status_code=200, content=b"{}", json=lambda: identity)

    monkeypatch.setattr("octop.infra.mobile_access.remote.httpx.AsyncClient", Client)
    monkeypatch.setattr(
        "octop.infra.mobile_access.remote.socket.getaddrinfo", lambda *_: ["resolved"]
    )
    result = await remote.diagnose("https://our.example")
    assert result["ok"] and result["identity_matches"]
    assert calls == [("https://our.example/api/mobile-access/identity", {})]
    identity["host_fingerprint"] = "another-host"
    result = await remote.diagnose("https://our.example")
    assert not result["ok"] and result["reason"] == "identity_mismatch"


@pytest.mark.asyncio
async def test_tailscale_refuses_existing_non_octop_mapping(remote, monkeypatch):
    calls = []

    async def command(*args):
        calls.append(args)
        if args[0] == "status":
            return {"BackendState": "Running", "Self": {"DNSName": "node.tailnet.ts.net."}}
        return {
            "TCP": {"443": {"HTTPS": True}},
            "Web": {
                "node.tailnet.ts.net:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:9999"}}}
            },
        }

    monkeypatch.setattr(remote, "_command", command)
    with pytest.raises(OctopError):
        await remote.enable_tailscale()
    assert all(args[:2] in [("status", "--json"), ("serve", "status")] for args in calls)


@pytest.mark.asyncio
async def test_owned_tailscale_enable_disable_without_funnel_or_global_reset(remote, monkeypatch):
    calls = []
    state = {"value": {"TCP": {}, "Web": {}}}

    async def command(*args):
        calls.append(args)
        if args[0] == "status":
            return {"BackendState": "Running", "Self": {"DNSName": "node.tailnet.ts.net."}}
        if args[1] == "status":
            return state["value"]
        state["value"] = {
            "TCP": {"443": {"HTTPS": True}},
            "Web": {
                "node.tailnet.ts.net:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8088"}}}
            },
        }
        return {}

    monkeypatch.setattr(remote, "_command", command)
    assert (await remote.enable_tailscale())["network"] == "tailnet"
    assert remote.access._read("mobile_access.public_url", None) == "https://node.tailnet.ts.net"
    await remote.disable_tailscale()
    assert ("serve", "--bg", "--https=443", "http://127.0.0.1:8088") in calls
    assert ("serve", "--https=443", "off") in calls
    assert all("funnel" not in args and "reset" not in args for args in calls)


@pytest.mark.asyncio
async def test_changed_tailscale_mapping_cannot_be_removed(remote, monkeypatch):
    remote.access._write(
        "mobile_access.tailscale_owned",
        {"url": "https://node.tailnet.ts.net", "target": "http://127.0.0.1:8088"},
    )
    command = AsyncMock(
        return_value={
            "TCP": {"443": {"HTTPS": True}},
            "Web": {
                "host:443": {
                    "Handlers": {
                        "/": {"Proxy": "http://127.0.0.1:8088"},
                        "/other": {"Proxy": "http://127.0.0.1:9999"},
                    }
                }
            },
        }
    )
    monkeypatch.setattr(remote, "_command", command)
    with pytest.raises(OctopError):
        await remote.disable_tailscale()
    command.assert_awaited_once_with("serve", "status", "--json")
