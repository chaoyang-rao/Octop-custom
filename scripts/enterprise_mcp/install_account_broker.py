#!/usr/bin/python3
"""Install restricted Unix IPC without relaxing the identity service sandbox."""
import os
import hashlib
from pathlib import Path
import pwd
import shutil
import subprocess

SERVICE='''[Unit]
Description=Octop verified business account grant broker
After=docker.service
Requires=docker.service
[Service]
Type=simple
User=root
Group=octop-enterprise
RuntimeDirectory=octop-mcp-accounts
RuntimeDirectoryMode=0750
ExecStart=/usr/bin/python3 /usr/local/libexec/octop-mcp-account-broker
Restart=on-failure
NoNewPrivileges=yes
PrivateTmp=yes
ProtectHome=yes
ProtectSystem=strict
RestrictAddressFamilies=AF_UNIX
ReadWritePaths=/var/lib/aiq-team-mcp /var/lib/aftersales-team-mcp /run/octop-mcp-accounts
CapabilityBoundingSet=CAP_DAC_OVERRIDE CAP_CHOWN
UMask=0077
Environment=DOCKER_CONFIG=/run/octop-mcp-accounts/docker-config
[Install]
WantedBy=multi-user.target
'''


def main():
    assert os.geteuid()==0
    source=Path(__file__).resolve().parent
    target=Path('/usr/local/libexec/octop-mcp-account-broker')
    if target.exists():assert target.read_bytes()==(source/'account_broker.py').read_bytes()
    shutil.copyfile(source/'account_broker.py',target);target.chmod(0o755)
    helper=Path('/usr/local/libexec/octop-mcp-account-helper')
    updated=(source/'account_helper.py').read_bytes()
    # Only the exact reviewed initial helper versions may be upgraded.
    previous=helper.read_bytes()
    assert previous==updated or hashlib.sha256(previous).hexdigest() in {
        'e1268ad1168ed7f56a04bccb97f3e791d5ee9efc7b3ec500b2134a738a3be92b',
        'f6ae93c24c4385372dafc4e1aa995662db754e65b89399aaaac031cde07c93d6',
        '37d46a1fb290f512f2217e5b98786a42be44317a5c1666619916cd8e7ee6f486',
    }
    helper_next=helper.with_suffix('.next')
    helper_next.write_bytes(updated);helper_next.chmod(0o755);helper_next.replace(helper)
    account=pwd.getpwnam('aiq-mcp');state=Path('/var/lib/aiq-team-mcp')
    state.mkdir(mode=0o700,exist_ok=True);os.chown(state,account.pw_uid,account.pw_gid)
    unit=Path('/etc/systemd/system/octop-mcp-account-broker.service')
    if unit.exists():assert unit.read_text().replace(' CAP_SETUID CAP_SETGID','')==SERVICE
    unit.write_text(SERVICE)
    # Retire only our earlier exact sudo rule. No broader host rule is changed.
    rule=Path('/etc/sudoers.d/octop-mcp-accounts')
    if rule.exists():
        assert rule.read_text()=='octop-enterprise ALL=(root) NOPASSWD: /usr/local/libexec/octop-mcp-account-helper\n'
        rollback=Path('/etc/octop-enterprise/rollbacks');rollback.mkdir(mode=0o700,exist_ok=True)
        rule.rename(rollback/'octop-mcp-accounts.sudoers')
    subprocess.run(['systemctl','daemon-reload'],check=True)
    subprocess.run(['systemctl','enable','--now','octop-mcp-account-broker.service'],check=True)
    subprocess.run(['systemctl','restart','octop-mcp-account-broker.service'],check=True)
    subprocess.run(['systemctl','is-active','--quiet','octop-mcp-account-broker.service'],check=True)
    print('Local business-account broker installed; identity sandbox remains enabled')


if __name__=='__main__':main()
