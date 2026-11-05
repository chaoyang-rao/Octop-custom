"""Freeze canonical Octop source with the explicit portable-only adapters.

Run --check after source changes, or --apply to regenerate the frozen backend.
Dashboard builds and the separately patched runtime libraries are not touched.
Unknown edits in the frozen backend are refused before any file is changed.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def portable_source(name: str, data: bytes, version: str) -> bytes:
    if name not in {
        "api/routers/health.py",
        "infra/agents/manager.py",
    }:
        return data
    text = data.decode("utf-8")
    if name == "api/routers/health.py":
        tree = ast.parse(text)
        returns = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)
        ]
        if len(returns) != 1 or "OCTOP_CUSTOM_BUILD" in text:
            raise ValueError("Review the portable health adapter after this upstream change")
        text = text.replace(
            "from __future__ import annotations\n",
            "from __future__ import annotations\n\nimport os\n",
            1,
        )
        lines = text.splitlines(keepends=True)
        tree = ast.parse(text)
        result = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)
        )
        lines.insert(
            result.end_lineno - 1,
            f'        **({{"custom_release": {version!r}}} if os.environ.get("OCTOP_CUSTOM_BUILD") == "1" else {{}}),\n',
        )
        text = "".join(lines)
    else:
        anchor = "from octop.infra.utils.turn_failure import turn_model_scope\n"
        if text.count(anchor) != 1 or "tool_failbreak_scope" in text:
            raise ValueError("Review the portable tool-scope adapter after this upstream change")
        text = text.replace(
            anchor,
            anchor + "from octop_harness.middleware.tool_failbreak import tool_failbreak_scope\n",
        )
        calls = [
            node
            for node in ast.walk(ast.parse(text))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "turn_model_scope"
        ]
        if len(calls) != 3:
            raise ValueError("Expected stream, call and HITL resume tool scopes")
        lines = text.splitlines(keepends=True)
        for node in sorted(calls, key=lambda node: node.end_lineno, reverse=True):
            if not lines[node.end_lineno - 1].rstrip().endswith(","):
                raise ValueError("Review the changed turn-scope layout")
            lines.insert(node.end_lineno, " " * node.col_offset + "tool_failbreak_scope(),\n")
        text = "".join(lines)
    ast.parse(text)
    return text.encode("utf-8")


def source_files(root: Path) -> dict[str, bytes]:
    source = root / "src" / "octop"
    if source.is_symlink():
        raise ValueError("Source package root must not be a symlink")
    version = json.loads((root / "scripts/custom/upstream-lock.json").read_text())["custom_version"]
    files = {}

    def walk(path: Path, ancestors: frozenset[Path]):
        resolved = path.resolve()
        if not resolved.is_relative_to(source.resolve()):
            raise ValueError(f"Source symlink escapes the package: {path}")
        real_relative = resolved.relative_to(source.resolve())
        if real_relative.parts and real_relative.parts[0] == "dashboard":
            raise ValueError(f"Source alias points into excluded dashboard output: {path}")
        if resolved.suffix in {".db", ".sqlite", ".sqlite3"} or (
            resolved.name.startswith(".env") and resolved.name != ".env.example"
        ):
            raise ValueError(f"Source alias points to private data: {path}")
        if path.is_dir():
            if resolved in ancestors:
                raise ValueError(f"Source symlink cycle: {path}")
            for child in sorted(path.iterdir()):
                if child.name not in {"__pycache__", ".DS_Store"} and child != source / "dashboard":
                    yield from walk(child, ancestors | {resolved})
        elif path.is_file():
            yield path

    # Wheel packaging also dereferences the upstream's internal skill aliases.
    for path in walk(source, frozenset()):
        relative = path.relative_to(source)
        if (
            relative.parts[0] == "dashboard"
            or "__pycache__" in relative.parts
            or path.name == ".DS_Store"
        ):
            continue
        if path.suffix in {".pyc", ".pyo"}:
            continue
        if path.suffix in {".db", ".sqlite", ".sqlite3"} or (
            path.name.startswith(".env") and path.name != ".env.example"
        ):
            raise ValueError(f"Private data must not appear in program source: {relative}")
        name = relative.as_posix()
        files[name] = portable_source(name, path.read_bytes(), version)
    return files


def sync(root: Path, *, apply: bool) -> dict[str, int]:
    target = root / "customization/packages/octop"
    for ancestor in (target, *target.parents):
        if ancestor == root:
            break
        if ancestor.is_symlink():
            raise ValueError(f"Frozen program path contains a symlink: {ancestor}")
    expected = source_files(root)
    manifest = json.loads((root / "customization/tracked-program-manifest.json").read_text())
    known = {
        row["path"].removeprefix("octop/"): row["sha256"]
        for row in manifest["files"]
        if row["path"].startswith("octop/")
    }
    existing = {}
    for path in target.rglob("*"):
        rel = path.relative_to(target)
        if (
            rel.parts[0] in {"dashboard", "_vendor"}
            or "__pycache__" in rel.parts
            or path.name == ".DS_Store"
            or path.suffix in {".pyc", ".pyo"}
        ):
            continue
        if path.is_symlink():
            raise ValueError(f"Frozen program symlink refused: {rel}")
        if path.is_file():
            existing[rel.as_posix()] = path.read_bytes()
    changed = {name: data for name, data in expected.items() if existing.get(name) != data}
    deleted = set(existing) - set(expected)
    # Complete preflight before copying or removing a single program file.
    for name in set(changed) | deleted:
        old = existing.get(name)
        if old is not None and hashlib.sha256(old).hexdigest() != known.get(name):
            raise ValueError(f"Independent frozen program edit refused: {name}")
    if apply:
        for name, data in changed.items():
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            path.chmod((root / "src/octop" / name).stat().st_mode & 0o777)
        for name in deleted:
            (target / name).unlink()
    return {"source_files": len(expected), "changed": len(changed), "obsolete": len(deleted)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--check", action="store_true")
    options = parser.parse_args()
    result = sync(ROOT, apply=options.apply)
    print(json.dumps(result))
    if options.check and (result["changed"] or result["obsolete"]):
        raise SystemExit("Frozen backend is stale; review changes and run --apply")
