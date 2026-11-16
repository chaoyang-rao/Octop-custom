import hashlib
import importlib.util
import json
import time
from pathlib import Path

path = Path(__file__).resolve().parents[3] / "scripts/enterprise_mcp/workbench_delegation.py"
spec = importlib.util.spec_from_file_location("workbench_delegation", path)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_mcp_only_grants_require_hash_account_binding_and_current_lease(tmp_path, monkeypatch):
    registry = tmp_path / "grants.json"
    token = "fixture-long-personal-MCP-secret"
    key = hashlib.sha256(token.encode()).hexdigest()
    row = {
        "login": "__octop_mcp_13",
        "username": "alice",
        "ledger_session": "fixture-own-session",
        "expires_at": time.time() + 60,
    }
    registry.write_text(json.dumps({key: row}))
    monkeypatch.setattr(module, "REGISTRY", registry)
    assert module.resolve_delegate("__octop_mcp_13", token)["username"] == "alice"
    assert module.resolve_delegate("__octop_mcp_14", token) is None
    assert module.resolve_delegate("alice", token) is None
    assert module.resolve_delegate("__octop_mcp_13", "another-long-but-invalid-secret") is None
    row["expires_at"] = time.time() - 1
    registry.write_text(json.dumps({key: row}))
    assert module.resolve_delegate("__octop_mcp_13", token) is None
