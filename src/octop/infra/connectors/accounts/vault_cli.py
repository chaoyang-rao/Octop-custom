"""Bounded official vault CLI calls; credentials never appear in argv or errors."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

_MAX_OUTPUT = 8 * 1024 * 1024


class VaultCliError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


async def run_vault_cli(
    provider: str,
    args: list[str],
    *,
    profile: Path,
    credential: str,
) -> bytes:
    binary = await asyncio.to_thread(shutil.which, "op" if provider == "onepassword" else "bw")
    if not binary:
        raise VaultCliError("cli_missing")
    if not credential:
        raise VaultCliError("authentication_required")
    await asyncio.to_thread(profile.mkdir, parents=True, exist_ok=True, mode=0o700)
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("OP_", "BW_", "BITWARDENCLI_"))
    }
    if provider == "onepassword":
        env.update(
            OP_CONFIG_DIR=str(profile),
            OP_SERVICE_ACCOUNT_TOKEN=credential,
            OP_CACHE="false",
            OP_BIOMETRIC_UNLOCK_ENABLED="false",
            OP_DEBUG="false",
        )
    else:
        env.update(
            BITWARDENCLI_APPDATA_DIR=str(profile), BW_SESSION=credential, BW_NOINTERACTION="true"
        )
    process = await asyncio.create_subprocess_exec(
        binary,
        *args,
        env=env,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        async with asyncio.timeout(30):
            assert process.stdout is not None
            result = bytearray()
            while chunk := await process.stdout.read(65536):
                result.extend(chunk)
                if len(result) > _MAX_OUTPUT:
                    raise VaultCliError("output_too_large")
            await process.wait()
        if process.returncode:
            raise VaultCliError("cli_failed")
        return bytes(result)
    except asyncio.CancelledError:
        raise
    except VaultCliError:
        raise
    except Exception:
        raise VaultCliError("cli_failed") from None
    finally:
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            await process.wait()


def item_metadata(
    provider: str, raw: bytes, *, limit: int = 100, offset: int = 0, search: str = ""
) -> list[dict[str, str]]:
    """Immediately project CLI output onto metadata; values/notes never escape."""
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError):
        raise VaultCliError("cli_failed") from None
    if not isinstance(data, list):
        raise VaultCliError("cli_failed")
    out = []
    for item in data:
        if not isinstance(item, dict):
            continue
        identifier = str(item.get("id") or "")
        if not identifier:
            continue
        raw_vault = item.get("vault")
        vault: dict[str, Any] = raw_vault if isinstance(raw_vault, dict) else {}
        title = str((item.get("title") if provider == "onepassword" else item.get("name")) or "")[
            :300
        ]
        if search.casefold() not in title.casefold():
            continue
        out.append(
            {
                "item_id": identifier,
                "title": title,
                "vault_id": str(vault.get("id") or ""),
            }
        )
    return out[offset : offset + limit]
