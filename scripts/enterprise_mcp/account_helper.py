#!/usr/bin/python3
"""Privileged, fixed-target grant adapter. JSON on stdin/stdout; never log secrets.

Installed root-owned at /usr/local/libexec/octop-mcp-account-helper. The company
service supplies only a server-verified Feishu union subject, never a display
name. Workbench accounts must already be linked to that exact subject. Quality
accounts require an explicit root-owned mapping; absence always denies.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import secrets
import subprocess
import sys
import time

REGISTRY = Path("/var/lib/aiq-team-mcp/delegated-sessions.json")
POLICY = Path("/etc/octop-enterprise/mcp-account-bindings.json")

WORKBENCH = '''
import json,sys
from app.config import settings
from app.db import session
from app import repo
p=json.load(sys.stdin)
with session(settings.db_path) as db:
    rows=db.execute('SELECT id,username,display_name FROM users WHERE feishu_union_id=? AND active=1 ORDER BY id', (p['subject'],)).fetchall()
    if p['action']=='list':
        result={'accounts':[{'account_id':str(r['id']),'label':(r['display_name'] or r['username'])+' · '+r['username']} for r in rows]}
    else:
        row=next((r for r in rows if str(r['id'])==p['account_id']),None)
        assert row is not None
        token,expiry=repo.create_session(db,row['id'],user_agent='Octop MCP delegated authorization',ip='127.0.0.1',usage_method='enterprise_mcp')
        repo.audit(db,row['id'],'mcp.authorize','user',row['id'],'Verified company identity; read-only MCP access')
        result={'ledger_session':token,'username':row['username'],'ttl':min(settings.session_hours*3600,30*86400)}
print(json.dumps(result,ensure_ascii=False))
'''


def workbench(payload):
    result = subprocess.run(
        ["/usr/bin/docker", "exec", "-i", "aiq-ledger", "python", "-c", WORKBENCH],
        input=json.dumps(payload).encode(), capture_output=True, timeout=12, check=True,
    )
    data = json.loads(result.stdout)
    if payload["action"] == "list":
        return data
    uid = pwd.getpwnam("aiq-mcp").pw_uid
    REGISTRY.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chown(REGISTRY.parent, uid, -1)
    lock = REGISTRY.with_suffix(".lock")
    token = secrets.token_urlsafe(32)
    with lock.open("a") as handle:
        os.chmod(lock, 0o600)
        fcntl.flock(handle, fcntl.LOCK_EX)
        records = json.loads(REGISTRY.read_text()) if REGISTRY.exists() else {}
        records = {k:v for k,v in records.items() if v["expires_at"] > time.time()}
        name = "__octop_mcp_" + payload["account_id"]
        records[hashlib.sha256(token.encode()).hexdigest()] = {
            "login": name, "username": data["username"], "ledger_session": data["ledger_session"],
            "company_user_id": payload["company_user_id"],
            "expires_at": int(time.time()) + data["ttl"],
        }
        temporary = REGISTRY.with_suffix(".next")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as out:
            json.dump(records,out)
        os.chown(temporary,uid,-1)
        temporary.replace(REGISTRY)
    return {"username": name, "password": token}


def quality(payload):
    policy = json.loads(POLICY.read_text()) if POLICY.exists() else {"quality": []}
    subject = hashlib.sha256(payload["subject"].encode()).hexdigest()
    rows = [r for r in policy["quality"] if r["subject_sha256"] == subject
            and r["company_user_id"] == payload["company_user_id"]]
    if payload["action"] == "list":
        return {"accounts": [{"account_id": r["principal_id"], "label": r["label"]} for r in rows]}
    row = next((r for r in rows if r["principal_id"] == payload["account_id"]), None)
    if row is None:
        raise ValueError("Account is not bound")
    root = Path("/opt/aftersales-team-mcp/current/server/mcp")
    tools = [r["name"] for r in json.loads((root/"contracts.json").read_text())["tools"]]
    state = Path("/var/lib/aftersales-team-mcp")
    registry_file = state/"credentials.json"
    entries = json.loads(registry_file.read_text())["clients"] if registry_file.exists() else []
    prefix = "octop-u"+str(payload["company_user_id"])+"-"
    from datetime import datetime, timezone
    for old in entries:
        if (old["clientId"].startswith(prefix) and old["principalId"] == row["principal_id"]
            and not old["revokedAt"] and datetime.fromisoformat(old["expiresAt"].replace("Z","+00:00")) > datetime.now(timezone.utc)
            and set(old["tools"]) == set(tools) and set(old["endTypes"]) == set(row["end_types"])):
            return {"token": (state/(old["clientId"]+".token")).read_text().strip()}
    if len(entries) >= 90:
        raise ValueError("Credential registry needs administrator rotation")
    result = subprocess.run([
        "/usr/bin/node", str(root/"personal-auth.cjs"), "issue-member",
        "--state-dir", str(state), "--client-id", prefix+secrets.token_hex(12),
        "--principal-id", row["principal_id"], "--tools", ",".join(tools),
        "--end-types", ",".join(row["end_types"]), "--days", "30",
    ], capture_output=True, timeout=12, check=True)
    token_path = Path(json.loads(result.stdout)["tokenFile"])
    if token_path.parent != Path("/var/lib/aftersales-team-mcp"):
        raise ValueError("Invalid credential path")
    token = token_path.read_text().strip()
    account = pwd.getpwnam("aftersales-team-mcp")
    for path in (token_path, token_path.parent/"credentials.json"):
        os.chown(path,account.pw_uid,account.pw_gid)
    return {"token": token}


def main():
    payload = json.loads(sys.stdin.read(16385))
    if payload.get("action") not in {"list", "issue"} or not isinstance(payload.get("subject"), str) or not 1 <= len(payload["subject"]) <= 256:
        raise ValueError("Invalid request")
    if not isinstance(payload.get("company_user_id"), int) or payload["company_user_id"] < 1:
        raise ValueError("Invalid member")
    if payload["action"] == "issue" and (not isinstance(payload.get("account_id"),str) or len(payload["account_id"]) > 64):
        raise ValueError("Invalid account")
    if payload.get("entry_id") == "quota-workbench":
        result = workbench(payload)
    elif payload.get("entry_id") == "aftersales-quality":
        result = quality(payload)
    else:
        raise ValueError("Unsupported service")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Docker/credential exceptions can contain private state. Never echo them.
        sys.stderr.write("Business account authorization failed\n")
        sys.exit(1)
