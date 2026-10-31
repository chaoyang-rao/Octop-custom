"""Remote access setup, identity diagnostics and optional owned Tailscale Serve."""

from __future__ import annotations

import asyncio
import json
import shutil
import socket
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from octop.infra.errors import ErrorCode, OctopError
from octop.infra.mobile_access.service import MobileAccessService, validate_server_url


def tailscale_binary() -> str | None:
    found = shutil.which("tailscale")
    if found is not None:
        return found
    if sys.platform == "darwin":
        bundled = Path("/Applications/Tailscale.app/Contents/MacOS/Tailscale")
        if bundled.is_file():
            return str(bundled)
    return None


class RemoteAccessService:
    def __init__(self, access: MobileAccessService, config: Any) -> None:
        self.access = access
        self.config = config
        self._network_lock = asyncio.Lock()

    async def status(self, request_origin: str) -> dict[str, Any]:
        public = await asyncio.to_thread(self.access._read, "mobile_access.public_url", None)
        listener_scheme = "https" if self.config.tls.enabled else "http"
        listener_host = str(self.config.bind_host)
        if ":" in listener_host:
            listener_host = f"[{listener_host}]"
        return {
            "public_url": public,
            "request_origin": request_origin,
            "listener": f"{listener_scheme}://{listener_host}:{self.config.port}",
            "native_tls": bool(self.config.tls.enabled),
            "tailscale_installed": bool(await asyncio.to_thread(tailscale_binary)),
            "last_check": await asyncio.to_thread(
                self.access._read, "mobile_access.remote_check", None
            ),
        }

    async def configure(self, url: str) -> str:
        normalized = validate_server_url(url)
        if urlsplit(normalized).scheme != "https":
            raise ValueError("mobile_access.https_required")
        await asyncio.to_thread(self.access._write, "mobile_access.public_url", normalized)
        await asyncio.to_thread(self.access._write, "mobile_access.remote_check", None)
        return normalized

    async def diagnose(self, url: str) -> dict[str, Any]:
        normalized = validate_server_url(url)
        if urlsplit(normalized).scheme != "https":
            raise ValueError("mobile_access.https_required")
        result: dict[str, Any] = {
            "url": normalized,
            "checked_at": int(time.time()),
            "dns": False,
            "tls": False,
            "http_status": None,
            "identity_matches": False,
            "ok": False,
            "reason": "unreachable",
        }
        try:
            host = urlsplit(normalized).hostname
            await asyncio.wait_for(
                asyncio.to_thread(socket.getaddrinfo, host, urlsplit(normalized).port or 443),
                timeout=5,
            )
            result["dns"] = True
            # Fixed identity path, no caller-supplied headers, redirects or credentials.
            async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
                response = await client.get(normalized + "/api/mobile-access/identity")
            result["tls"] = True
            result["http_status"] = response.status_code
            if response.status_code == 200 and len(response.content) < 4096:
                identity = response.json()
                if not isinstance(identity, dict):
                    identity = {}
                fingerprint = await asyncio.to_thread(self.access._host_fingerprint)
                result["identity_matches"] = (
                    identity.get("host_fingerprint") == fingerprint
                    and identity.get("protocol") == "octop-mobile-v1"
                )
                result["ok"] = result["identity_matches"]
                result["reason"] = "ready" if result["ok"] else "identity_mismatch"
            else:
                result["reason"] = "route_or_proxy"
        except socket.gaierror:
            result["reason"] = "dns"
        except (httpx.ConnectError, httpx.TimeoutException, TimeoutError):
            result["reason"] = "connection_or_certificate"
        except (ValueError, httpx.HTTPError):
            result["reason"] = "route_or_proxy"
        await asyncio.to_thread(self.access._write, "mobile_access.remote_check", result)
        return result

    async def _command(self, *arguments: str) -> dict[str, Any]:
        binary = await asyncio.to_thread(tailscale_binary)
        if binary is None:
            raise OctopError(ErrorCode.NOT_FOUND, "Tailscale CLI is not installed")
        process = await asyncio.create_subprocess_exec(
            binary, *arguments, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
        )
        try:
            output, _ = await asyncio.wait_for(process.communicate(), timeout=12)
        except TimeoutError:
            process.kill()
            await process.wait()
            raise OctopError(ErrorCode.FORBIDDEN, "Tailscale operation timed out") from None
        if process.returncode != 0 or len(output) > 2 * 1024 * 1024:
            raise OctopError(
                ErrorCode.FORBIDDEN, "Tailscale operation failed; inspect the local Tailscale app"
            )
        return json.loads(output) if output.strip().startswith(b"{") else {}

    async def tailscale_status(self) -> dict[str, Any]:
        state = await self._command("status", "--json")
        self_node = state.get("Self") or {}
        dns_name = str(self_node.get("DNSName") or "").rstrip(".")
        url = validate_server_url(f"https://{dns_name}") if dns_name else None
        owned = await asyncio.to_thread(self.access._read, "mobile_access.tailscale_owned", None)
        return {
            "authenticated": state.get("BackendState") == "Running",
            "url": url,
            "owned": bool(owned),
        }

    async def enable_tailscale(self) -> dict[str, Any]:
        async with self._network_lock:
            if self.config.tls.enabled:
                raise OctopError(
                    ErrorCode.FORBIDDEN, "use the existing TLS listener or a reverse proxy"
                )
            status = await self.tailscale_status()
            if not status["authenticated"] or not status["url"]:
                raise OctopError(
                    ErrorCode.FORBIDDEN, "sign in using the local Tailscale application first"
                )
            current = await self._command("serve", "status", "--json")
            owned = await asyncio.to_thread(
                self.access._read, "mobile_access.tailscale_owned", None
            )
            target = f"http://127.0.0.1:{self.config.port}"
            has_configuration = any(bool(value) for value in current.values())
            if has_configuration and not self._only_owned_handler(current, target):
                raise OctopError(
                    ErrorCode.FORBIDDEN, "existing Tailscale Serve configuration is preserved"
                )
            if has_configuration and not owned:
                raise OctopError(
                    ErrorCode.FORBIDDEN,
                    "existing Tailscale Serve configuration is not owned by Octop",
                )
            if not has_configuration:
                await self._command("serve", "--bg", "--https=443", target)
            record = {"url": status["url"], "target": target}
            await asyncio.to_thread(self.access._write, "mobile_access.tailscale_owned", record)
            await self.configure(status["url"])
            return {"url": status["url"], "enabled": True, "network": "tailnet"}

    @staticmethod
    def _only_owned_handler(current: dict[str, Any], target: str) -> bool:
        web = current.get("Web") or {}
        tcp = current.get("TCP") or {}
        if (
            current.get("Foreground")
            or current.get("AllowFunnel")
            or tcp != {"443": {"HTTPS": True}}
            or len(web) != 1
        ):
            return False
        site = next(iter(web.values()))
        return (
            site.get("Handlers") == {"/": {"Proxy": target}}
            and tcp.get("443", {}).get("HTTPS") is True
        )

    async def disable_tailscale(self) -> dict[str, Any]:
        async with self._network_lock:
            owned = await asyncio.to_thread(
                self.access._read, "mobile_access.tailscale_owned", None
            )
            if not owned:
                raise OctopError(
                    ErrorCode.FORBIDDEN, "Octop does not own a Tailscale Serve mapping"
                )
            current = await self._command("serve", "status", "--json")
            if not self._only_owned_handler(current, owned["target"]):
                raise OctopError(
                    ErrorCode.FORBIDDEN,
                    "Tailscale configuration changed; preserving other services",
                )
            await self._command("serve", "--https=443", "off")
            await asyncio.to_thread(self.access._write, "mobile_access.tailscale_owned", None)
            selected = await asyncio.to_thread(self.access._read, "mobile_access.public_url", None)
            if selected == owned["url"]:
                await asyncio.to_thread(self.access._write, "mobile_access.public_url", None)
            return {"enabled": False}


def remote_for(server: Any) -> RemoteAccessService:
    from octop.infra.mobile_access.service import service_for

    service = getattr(server, "_mobile_remote_service", None)
    if not isinstance(service, RemoteAccessService):
        service = RemoteAccessService(service_for(server), server.services.config)
        server._mobile_remote_service = service
    return service
