"""Cold-start a candidate portable and verify its pre-acceptance admission gate."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


def smoke(root: Path) -> dict[str, str]:
    manifest = json.loads((root / "custom-release-manifest.json").read_text())
    python = root / "runtime" / ("python.exe" if os.name == "nt" else "bin/python3")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    env = {key: value for key, value in os.environ.items() if not key.startswith("OCTOP_")}
    with tempfile.TemporaryDirectory(prefix="octop-candidate-smoke-") as temporary:
        home = Path(temporary) / "data"
        identifier = "e" * 32
        journal = home / "client-updates/jobs" / identifier / "job.json"
        journal.parent.mkdir(parents=True)
        journal.write_text(json.dumps({"id": identifier, "phase": "candidate_ready"}))
        env.update(
            OCTOP_HOME=str(home),
            OCTOP_BIND_HOST="127.0.0.1",
            OCTOP_PORT=str(port),
            OCTOP_REQUIRE_SETUP_PASSWORD="false",
            OCTOP_DESKTOP="1",
            OCTOP_DESKTOP_CLIENT_VERSION=manifest["custom_version"],
            OCTOP_DESKTOP_UPDATER_PROTOCOL="1",
            OCTOP_DESKTOP_PROGRAM_ROOT=str(Path(temporary) / "application"),
            OCTOP_CLIENT_UPDATE_PENDING=identifier,
            PYTHONNOUSERSITE="1",
            PYTHONPATH="",
            PYTHONUTF8="1",
            PYTHONIOENCODING="utf-8",
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def read(path: str) -> dict[str, object]:
            with opener.open(f"http://127.0.0.1:{port}/api/{path}", timeout=3) as response:
                return json.load(response)

        with (Path(temporary) / "startup.log").open("w") as log:
            process = subprocess.Popen(
                [str(python), str(root / "launch.py"), "run"],
                cwd=root,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                deadline = time.monotonic() + 90
                while True:
                    if process.poll() is not None:
                        raise RuntimeError(f"Candidate exited: {process.returncode}")
                    try:
                        health = read("health")
                        break
                    except (urllib.error.URLError, TimeoutError, ValueError):
                        if time.monotonic() > deadline:
                            raise RuntimeError("Candidate failed to start") from None
                        time.sleep(0.25)
                assert health.get("custom_release") == manifest["custom_version"]
                assert health.get("client_update_pending") is True
                try:
                    read("setup/status")
                except urllib.error.HTTPError as error:
                    assert error.code == 503
                    assert json.load(error)["error"]["code"] == "CLIENT_UPDATE_IN_PROGRESS"
                else:
                    raise AssertionError("Candidate admitted work before acceptance")
                temporary_journal = journal.with_suffix(".writing")
                temporary_journal.write_text(json.dumps({"id": identifier, "phase": "accepted"}))
                temporary_journal.replace(journal)
                deadline = time.monotonic() + 45
                while read("health").get("client_update_pending") is not False:
                    if time.monotonic() > deadline:
                        raise RuntimeError("Candidate failed to resume after acceptance")
                    time.sleep(0.25)
                assert read("setup/status").get("database_bound") is True
                return {"pending_admission_gate": "passed", "resume_after_acceptance": "passed"}
            finally:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    print(json.dumps(smoke(Path(sys.argv[1]).resolve())))
