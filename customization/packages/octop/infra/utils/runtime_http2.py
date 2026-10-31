"""Load the declared HTTP/2 extra, with a locked portable-runtime fallback."""

from __future__ import annotations

import importlib
import importlib.util
import sys
import threading
from pathlib import Path

_lock = threading.Lock()
_ready = False


def ensure_http2() -> None:
    """Initialize off the event loop; no downloads or installation at runtime.

    The portable overlay preserves its official dependencies. Its additional
    pure-Python MIT packages live in this program's private vendor directory.
    Adding that directory does not process executable .pth files.
    """
    global _ready
    with _lock:
        if _ready:
            return
        if importlib.util.find_spec("h2") is None:
            vendor = Path(__file__).resolve().parents[2] / "_vendor" / "http2"
            if not (vendor / "h2" / "__init__.py").is_file():
                raise RuntimeError("HTTP/2 runtime dependency is missing")
            sys.path.insert(0, str(vendor))
        importlib.import_module("h2.connection")
        _ready = True
