"""Headers remain destination-bound and response content is never read."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest
from tests.support.fakes import fake_bin_path

from octop.infra.connectors.accounts import vault_delivery
from octop.infra.connectors.accounts.vault_cli import run_vault_cli


class NeverRead(httpx.AsyncByteStream):
    async def __aiter__(self):
        raise AssertionError("secret-bearing response body must never be read")
        yield b""


@pytest.mark.asyncio
async def test_delivery_does_not_read_echo_body_or_follow_redirects(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            302,
            headers={"Location": "https://other.example/secret-in-location"},
            stream=NeverRead(),
        )

    monkeypatch.setattr(
        vault_delivery, "_resolve_validated_ip", AsyncMock(return_value="public-ip-token")
    )
    monkeypatch.setattr(
        vault_delivery, "PinnedIPTransport", lambda *_: httpx.MockTransport(handler)
    )
    status = await vault_delivery.send_secret_header(
        "POST",
        "https://api.example.com/one",
        headers={"Authorization": "Bearer fake-secret"},
        body={"reviewed": True},
    )
    assert status == 302 and len(calls) == 1
    assert calls[0].url.host == "api.example.com"
    assert calls[0].headers["authorization"] == "Bearer fake-secret"


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["onepassword", "bitwarden"])
async def test_cli_credentials_only_enter_isolated_environment(monkeypatch, tmp_path, provider):
    from octop.infra.connectors.accounts import vault_cli

    monkeypatch.setenv("OP_SESSION", "personal-login-must-not-inherit")
    monkeypatch.setenv("BW_SESSION", "personal-session-must-not-inherit")
    monkeypatch.setattr(vault_cli.shutil, "which", lambda _: fake_bin_path("provider-cli"))

    class Reader:
        def __init__(self):
            self.reads = 0

        async def read(self, _):
            self.reads += 1
            return b"[]" if self.reads == 1 else b""

    class Process:
        returncode = None
        stdout = Reader()

        async def wait(self):
            self.returncode = 0

        def kill(self):
            self.returncode = -1

    spawn = AsyncMock(return_value=Process())
    monkeypatch.setattr(vault_cli.asyncio, "create_subprocess_exec", spawn)
    result = await run_vault_cli(
        provider, ["list"], profile=tmp_path / "owned-profile", credential="fake-private-session"
    )
    assert result == b"[]"
    assert "fake-private-session" not in " ".join(spawn.call_args.args)
    env = spawn.call_args.kwargs["env"]
    assert "OP_SESSION" not in env
    if provider == "onepassword":
        assert "BW_SESSION" not in env
        assert env["OP_SERVICE_ACCOUNT_TOKEN"] == "fake-private-session"
        assert env["OP_CONFIG_DIR"] == str(tmp_path / "owned-profile")
        assert env["OP_BIOMETRIC_UNLOCK_ENABLED"] == "false"
    else:
        assert "OP_SERVICE_ACCOUNT_TOKEN" not in env
        assert env["BW_SESSION"] == "fake-private-session"
        assert env["BITWARDENCLI_APPDATA_DIR"] == str(tmp_path / "owned-profile")
