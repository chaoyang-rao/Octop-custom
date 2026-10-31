"""Resolve CLI launchers without a shell, including Windows npm shims."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from octop.infra.agents.native_cli.config import NativeCLIError

_NPM_SCRIPTS = {
    "npx": "npm/bin/npx-cli.js",
    "npm": "npm/bin/npm-cli.js",
    "codex": "@openai/codex/bin/codex.js",
    "claude": "@anthropic-ai/claude-code/cli.js",
    "gemini": "@google/gemini-cli/dist/index.js",
    "opencode": "opencode-ai/bin/opencode",
}


def resolve_native_launch(command: str, args: list[str]) -> tuple[str, list[str]]:
    executable = shutil.which(command)
    if not executable:
        raise NativeCLIError("runner_missing")
    path = Path(executable)
    if sys.platform == "win32" and path.suffix.lower() in {".cmd", ".bat", ".ps1"}:
        relative = _NPM_SCRIPTS.get(path.stem.lower())
        node = shutil.which("node")
        script = path.parent / "node_modules" / relative if relative else None
        if not node or script is None or not script.is_file():
            # No cmd.exe fallback: metacharacters remain literal argv data.
            raise NativeCLIError("runner_missing")
        return node, [str(script), *args]
    return executable, list(args)
