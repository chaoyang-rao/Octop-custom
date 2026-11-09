"""Cold-start a built portable in isolated user data, using its actual launcher."""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


def smoke(root: Path) -> dict[str, object]:
    manifest = json.loads((root / "custom-release-manifest.json").read_text())
    expected_authority = manifest.get("enterprise_authority_url", "")
    python = root / "runtime" / ("python.exe" if os.name == "nt" else "bin/python3")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    # Do not supply the company URL here: the packaged launcher must set it.
    env = {key: value for key, value in os.environ.items() if not key.startswith("OCTOP_")}
    with tempfile.TemporaryDirectory(prefix="octop-startup-smoke-") as temporary:
        env.update(
            OCTOP_HOME=str(Path(temporary) / "user-data"),
            OCTOP_BIND_HOST="127.0.0.1",
            OCTOP_PORT=str(port),
            OCTOP_REQUIRE_SETUP_PASSWORD="false",
            PYTHONNOUSERSITE="1",
            PYTHONPATH="",
            PYTHONUTF8="1",
            PYTHONIOENCODING="utf-8",
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def read(path: str) -> dict[str, object]:
            with opener.open(f"http://127.0.0.1:{port}/api/{path}", timeout=2) as response:
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
                        raise RuntimeError(f"Portable exited during startup: {process.returncode}")
                    try:
                        setup = read("setup/status")
                        health = read("health")
                        break
                    except (urllib.error.URLError, TimeoutError, ValueError):
                        if time.monotonic() >= deadline:
                            raise RuntimeError("Portable startup did not become ready within 90 seconds")
                        time.sleep(0.25)
                assert health.get("custom_release") == manifest["custom_version"], health
                assert bool(setup.get("enterprise_login")) == bool(expected_authority), setup
                assert setup.get("enterprise_authority_url", "") == expected_authority, setup
                if expected_authority:
                    assert setup.get("database_bound") is True, setup
                    assert setup.get("setup_required") is False, setup
                return {
                    "custom_release": health["custom_release"],
                    "enterprise_login": bool(setup.get("enterprise_login")),
                    "enterprise_authority_url": expected_authority,
                    "database_bound": setup.get("database_bound"),
                    "actual_launcher_cold_start": "passed",
                }
            finally:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    print(json.dumps(smoke(Path(sys.argv[1]).resolve())))
