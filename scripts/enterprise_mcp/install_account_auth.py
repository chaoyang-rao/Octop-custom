#!/usr/bin/python3
"""Install the reviewed read-only workbench grant adapter on the company server.

Run as root from a directory containing the three public adapter scripts.
The current business application, passwords and ordinary Basic grants stay intact.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time

BASE_SERVER_SHA = "0c9a14c7601ce3b0eff7f022bdfc492d74eac502d27b055eb0d40f5490c3cc9f"


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quality-owner-user-id",type=int,help="Explicit, already verified business-owner binding; omitted means default deny")
    args=parser.parse_args()
    assert os.geteuid() == 0
    source = Path(__file__).resolve().parent
    current = Path("/opt/aiq-team-mcp/current")
    base = current.resolve()
    assert base.is_relative_to(Path("/opt/aiq-team-mcp/releases"))
    original = (base/"mcp_service/server.py").read_bytes()
    assert hashlib.sha256(original).hexdigest() == BASE_SERVER_SHA, "Review changed business gateway before applying"
    module = (source/"workbench_delegation.py").read_bytes()
    revision = hashlib.sha256(module+(source/"account_helper.py").read_bytes()).hexdigest()[:12]
    target = base.parent/("account-picker-20261116-"+revision)
    assert not target.exists()
    shutil.copytree(base,target,ignore=shutil.ignore_patterns("__pycache__"),symlinks=True)
    text = original.decode()
    anchor = "from .bridge import Bridge, BridgeConfig, Credentials, failure, validate\n"
    assert text.count(anchor) == 1
    text = text.replace(anchor,anchor+"from .workbench_delegation import resolve_delegate, verify_session\n")
    anchor = "                accepted = await self.bridge.authenticate_password(credentials)"
    assert text.count(anchor) == 1
    text = text.replace(anchor,"""                delegated = resolve_delegate(credentials.username, credentials.password)
                if delegated is not None:
                    credentials = Credentials(username=delegated['username'], ledger_session=delegated['ledger_session'])
                    accepted = await verify_session(self.bridge, credentials.ledger_session)
                elif not credentials.username.startswith('__octop_mcp_'):
                    accepted = await self.bridge.authenticate_password(credentials)""")
    (target/"mcp_service/server.py").write_text(text)
    (target/"mcp_service/workbench_delegation.py").write_bytes(module)
    subprocess.run(["/opt/aiq-team-mcp/venv/bin/python","-c","import mcp_service.server"],env={**os.environ,"PYTHONPATH":str(target),"PYTHONDONTWRITEBYTECODE":"1"},check=True)
    unchanged=0
    for old in base.rglob("*"):
        if old.is_file() and "__pycache__" not in old.parts and old.relative_to(base).as_posix() != "mcp_service/server.py":
            assert hashlib.sha256(old.read_bytes()).digest()==hashlib.sha256((target/old.relative_to(base)).read_bytes()).digest()
            unchanged+=1
    destination=Path("/usr/local/libexec/octop-mcp-account-helper")
    assert not destination.exists()
    destination.parent.mkdir(mode=0o755,parents=True,exist_ok=True)
    shutil.copyfile(source/"account_helper.py",destination);destination.chmod(0o755)
    sudoers=Path("/etc/sudoers.d/octop-mcp-accounts")
    assert not sudoers.exists()
    sudoers.write_text("octop-enterprise ALL=(root) NOPASSWD: /usr/local/libexec/octop-mcp-account-helper\n")
    sudoers.chmod(0o440)
    subprocess.run(["/usr/sbin/visudo","-cf",str(sudoers)],check=True)
    policy=Path("/etc/octop-enterprise/mcp-account-bindings.json")
    assert not policy.exists()
    policy.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    bindings=[]
    if args.quality_owner_user_id is not None:
        assert args.quality_owner_user_id > 0
        with sqlite3.connect("file:/var/lib/octop-enterprise/octop.db?mode=ro",uri=True) as db:
            identity=db.execute("SELECT i.subject,COALESCE(u.display_name,u.username) FROM user_sso_identities i JOIN sso_providers p ON p.id=i.provider_id JOIN users u ON u.id=i.user_id WHERE u.id=? AND u.role='admin' AND p.kind='feishu'",(args.quality_owner_user_id,)).fetchone()
            assert identity is not None
        bindings=[{"company_user_id":args.quality_owner_user_id,"subject_sha256":hashlib.sha256(identity[0].encode()).hexdigest(),"principal_id":"owner","label":identity[1]+" · 售后 B/C 端只读账户","end_types":["b","c"]}]
    # This explicit owner binding is local deployment policy. Other identities
    # are denied until their actual business permissions are separately bound.
    policy.write_text(json.dumps({"quality":bindings},ensure_ascii=False,indent=2)+"\n")
    policy.chmod(0o600)
    link=current.with_name("current.next")
    assert not link.exists()
    link.symlink_to(target);link.replace(current)
    try:
        subprocess.run(["systemctl","restart","aiq-team-mcp.service"],check=True)
        time.sleep(1)
        subprocess.run(["systemctl","is-active","--quiet","aiq-team-mcp.service"],check=True)
    except BaseException:
        link.symlink_to(base);link.replace(current)
        subprocess.run(["systemctl","restart","aiq-team-mcp.service"],check=True)
        raise
    print(json.dumps({"workbench_release":str(target),"rollback_release":str(base),"non_target_files_preserved":unchanged,"business_passwords_changed":False,"grants_issued":0}))


if __name__=="__main__":
    main()
