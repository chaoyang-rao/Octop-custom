"""Child MCP stdio transport forwarding to one authenticated loopback session."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit


def main() -> None:
    url = os.environ.get("OCTOP_NATIVE_BRIDGE_URL", "")
    token = os.environ.get("OCTOP_NATIVE_BRIDGE_TOKEN", "")
    parsed = urlsplit(url)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.path != "/mcp"
        or parsed.username
        or not token
    ):
        raise SystemExit("Invalid local bridge configuration")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for line in sys.stdin:
        if len(line) > 1024 * 1024:
            raise SystemExit("MCP frame exceeded limit")
        try:
            value = json.loads(line)
            request = urllib.request.Request(
                url,
                data=line.encode(),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                    "Authorization": "Bearer " + token,
                },
            )
            with opener.open(request, timeout=86400) as response:
                data = response.read(32 * 1024 * 1024 + 1)
                if len(data) > 32 * 1024 * 1024:
                    raise SystemExit("MCP result exceeded limit")
            if value.get("id") is not None and data:
                sys.stdout.write(data.decode() + "\n")
                sys.stdout.flush()
        except (ValueError, OSError, urllib.error.URLError):
            # Never log request/response bodies or the session credential.
            raise SystemExit("Local MCP bridge disconnected") from None


if __name__ == "__main__":
    main()
