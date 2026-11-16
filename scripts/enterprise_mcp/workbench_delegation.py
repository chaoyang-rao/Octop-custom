"""Read-only MCP adapter for member grants; existing password auth is preserved."""
import hashlib
import json
from pathlib import Path
import re
import time

REGISTRY = Path("/var/lib/aiq-team-mcp/delegated-sessions.json")


def resolve_delegate(username, token):
    if not username.startswith("__octop_mcp_") or not 24 <= len(token) <= 128:
        return None
    try:
        if REGISTRY.is_symlink():
            return None
        data = json.loads(REGISTRY.read_text())
        row = data.get(hashlib.sha256(token.encode()).hexdigest())
        if not row or row["login"] != username or row["expires_at"] <= time.time():
            return None
        session = row["ledger_session"]
        if not session or re.search(r"[;\s\x00-\x1f]",session):
            return None
        return row
    except (OSError, ValueError, KeyError, TypeError):
        return None


async def verify_session(bridge, session):
    headers={"Cookie":f"{bridge.config.cookie_name}={session}","Origin":bridge.config.ledger_base_url.rstrip("/")}
    async with bridge.client(bridge.config.ledger_base_url,bridge.ledger_transport) as client:
        async with client.stream("GET","/me",headers=headers) as response:
            # Ledger validates expiration and whether the business member is active.
            return response.status_code == 200
