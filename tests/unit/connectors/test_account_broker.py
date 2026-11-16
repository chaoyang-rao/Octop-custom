import importlib.util
import io
import json
import os
import shutil
import struct
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

path = Path(__file__).resolve().parents[3] / "scripts/enterprise_mcp/account_broker.py"
spec = importlib.util.spec_from_file_location("account_broker", path)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Connection:
    def __init__(self, uid):
        self.uid = uid
        self.sent = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def settimeout(self, value):
        pass

    def getsockopt(self, *args):
        return struct.pack("3i", 1, self.uid, 1)

    def makefile(self, *args):
        return io.BytesIO(
            json.dumps(
                {"action": "list", "entry_id": "quota-workbench", "command": "untrusted"}
            ).encode()
            + b"\n"
        )

    def sendall(self, data):
        self.sent.append(data)


def test_broker_refuses_other_os_users_and_never_executes_a_request_command(monkeypatch):
    calls = []
    monkeypatch.setattr(module.socket, "SO_PEERCRED", 17, raising=False)
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda args, **kwargs: calls.append(args) or SimpleNamespace(stdout=b'{"accounts":[]}'),
    )
    module.handle(Connection(99), 42)
    assert not calls
    permitted = Connection(42)
    module.handle(permitted, 42)
    assert calls == [["/usr/bin/python3", module.HELPER]]
    assert json.loads(permitted.sent[0]) == {"accounts": []}


def test_quality_credential_reader_rejects_symlinks_and_public_files(tmp_path):
    pytest.importorskip("fcntl")
    helper_path = path.with_name("account_helper.py")
    helper_spec = importlib.util.spec_from_file_location("account_helper_test", helper_path)
    assert helper_spec and helper_spec.loader
    helper = importlib.util.module_from_spec(helper_spec)
    helper_spec.loader.exec_module(helper)
    token = tmp_path / "personal.token"
    token.write_text("fixture-token")
    token.chmod(0o600)
    assert helper.read_private(token, os.getuid(), 100) == "fixture-token"
    with pytest.raises(ValueError):
        helper.read_private(token, os.getuid(), 2)
    token.chmod(0o644)
    with pytest.raises(ValueError):
        helper.read_private(token, os.getuid(), 100)
    token.chmod(0o600)
    alias = tmp_path / "alias.token"
    alias.symlink_to(token)
    with pytest.raises(OSError):
        helper.read_private(alias, os.getuid(), 100)


def test_node_issuer_preserves_private_owner_before_atomic_registry_rename(tmp_path):
    pytest.importorskip("fcntl")
    executable = shutil.which("node")
    if executable is None:
        pytest.skip("Node is unavailable")
    helper_path = path.with_name("account_helper.py")
    helper_spec = importlib.util.spec_from_file_location("node_issuer_helper", helper_path)
    assert helper_spec and helper_spec.loader
    helper = importlib.util.module_from_spec(helper_spec)
    helper_spec.loader.exec_module(helper)
    state = tmp_path / "state"
    state.mkdir()
    issuer = tmp_path / "issuer.cjs"
    issuer.write_text(
        "const fs=require('node:fs');exports.issueCredential=(state)=>{const f=state+'/new.tmp';const fd=fs.openSync(f,fs.constants.O_WRONLY|fs.constants.O_CREAT|fs.constants.O_EXCL|fs.constants.O_NOFOLLOW,0o600);fs.writeSync(fd,'fixture');fs.closeSync(fd);fs.renameSync(f,state+'/credential.json');return {ok:true};};"
    )
    payload = {
        "module": str(issuer),
        "state": str(state),
        "uid": os.getuid(),
        "gid": os.getgid(),
        "options": {},
    }
    result = subprocess.run(
        [executable, "-e", helper.NODE_ISSUER],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(result.stdout) == {"ok": True}
    info = (state / "credential.json").stat()
    assert info.st_uid == os.getuid() and info.st_mode & 0o777 == 0o600
