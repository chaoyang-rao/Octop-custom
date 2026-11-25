"""Run the bundled engine with an app-owned home and a parent-lifetime guard."""

from __future__ import annotations

import os
from pathlib import Path
import runpy
import signal
import sys
import threading


def main() -> None:
    runtime = Path(sys.argv[1]).resolve(strict=True)
    launch = runtime / "launch.py"
    if not launch.is_file() or os.environ.get("OCTOP_COMPANION_MODE") != "1":
        raise SystemExit("Companion engine launch refused")
    if os.name == "posix" and os.getpgrp() != os.getpid():
        os.setsid()

    def parent_lifetime() -> None:
        # EOF means the pet quit/crashed. Only signal our own process group.
        try:
            while sys.stdin.buffer.read(1):
                pass
        finally:
            if os.name == "posix":
                os.killpg(os.getpgrp(), signal.SIGTERM)
            else:
                # Only this app-owned engine exits; never kill by process name.
                os._exit(0)

    threading.Thread(target=parent_lifetime, daemon=True).start()
    sys.argv = [str(launch), *sys.argv[2:]]
    runpy.run_path(str(launch), run_name="__main__")


if __name__ == "__main__":
    main()
