#!/usr/bin/python3
"""Local fixed-action broker; keeps NoNewPrivileges on the identity center."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import pwd
import socket
import struct
import subprocess
from threading import BoundedSemaphore

SOCKET=Path("/run/octop-mcp-accounts/broker.sock")
HELPER="/usr/local/libexec/octop-mcp-account-helper"


def handle(connection, allowed_uid):
    with connection:
        connection.settimeout(5)
        _,uid,_=struct.unpack("3i",connection.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
        if uid!=allowed_uid:
            return
        try:
            with connection.makefile("rb") as stream:
                raw=stream.readline(16385)
            if len(raw)>16384 or not raw.endswith(b"\n"):
                raise ValueError
            payload=json.loads(raw)
            if not isinstance(payload,dict) or payload.get("entry_id") not in {"aftersales-quality","quota-workbench"} or payload.get("action") not in {"list","issue"}:
                raise ValueError
            result=subprocess.run(["/usr/bin/python3",HELPER],input=raw,capture_output=True,timeout=20,check=True)
            if len(result.stdout)>65536:
                raise ValueError
            json.loads(result.stdout)
            connection.sendall(result.stdout.strip()+b"\n")
        except Exception:
            try:connection.sendall(b'{"error":"authorization_unavailable"}\n')
            except OSError:pass


def main():
    account=pwd.getpwnam("octop-enterprise")
    if SOCKET.exists():SOCKET.unlink()
    slots=BoundedSemaphore(8)
    def bounded(connection):
        try:handle(connection,account.pw_uid)
        finally:slots.release()
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as listener,ThreadPoolExecutor(max_workers=4) as pool:
        listener.bind(str(SOCKET))
        import os
        os.chown(SOCKET,0,account.pw_gid)
        SOCKET.chmod(0o660)
        listener.listen(8)
        while True:
            connection,_=listener.accept()
            if slots.acquire(blocking=False):
                pool.submit(bounded,connection)
            else:
                connection.close()


if __name__=="__main__":main()
