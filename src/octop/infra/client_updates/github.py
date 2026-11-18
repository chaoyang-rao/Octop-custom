"""Read only immutable-looking releases from the one configured source repository."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

import httpx

from octop.infra.client_updates.models import (
    MAX_ARCHIVE,
    PLATFORMS,
    REPOSITORY,
    ClientPackage,
    asset_name,
    failure,
    release_asset_url,
    valid_version,
)
from octop.infra.errors import ErrorCode


def github_download_host(url: str) -> bool:
    parsed = urlsplit(url)
    return bool(
        parsed.scheme == "https"
        and not parsed.username
        and not parsed.password
        and parsed.port in (None, 443)
        and (
            parsed.hostname == "github.com"
            or (parsed.hostname or "").endswith(".githubusercontent.com")
        )
    )


async def release_index() -> list[dict[str, Any]]:
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            response = await client.get(
                f"https://api.github.com/repos/{REPOSITORY}/releases",
                params={"per_page": 30},
                headers={"User-Agent": "OctopCustom-Updater/1"},
            )
            response.raise_for_status()
            raw = response.json()
        if not isinstance(raw, list):
            raise ValueError
        return [row for row in raw if isinstance(row, dict) and not row.get("draft")]
    except (ValueError, httpx.HTTPError):
        raise failure(ErrorCode.CLIENT_UPDATE_DOWNLOAD_FAILED) from None


def package_metadata(raw: dict[str, Any]) -> tuple[str, str, str, list[ClientPackage], str]:
    tag = str(raw.get("tag_name", ""))
    commit = str(raw.get("target_commitish", ""))
    assets = {a.get("name"): a for a in raw.get("assets", []) if isinstance(a, dict)}
    if (
        raw.get("draft")
        or not re.fullmatch(r"custom-[A-Za-z0-9.-]{1,90}", tag)
        or not re.fullmatch(r"[0-9a-f]{40}", commit)
    ):
        raise failure()
    prefix = "OctopCustom-update-windows-amd64-"
    versions = [
        name[len(prefix) : -4]
        for name in assets
        if isinstance(name, str) and name.startswith(prefix) and name.endswith(".zip")
    ]
    if len(versions) != 1:
        raise failure()
    version = valid_version(versions[0])
    packages = []
    for platform in PLATFORMS:
        filename = asset_name(platform, version)
        item = assets.get(filename, {})
        sha = str(item.get("digest", ""))
        if not sha.startswith("sha256:") or not re.fullmatch(r"sha256:[0-9a-f]{64}", sha):
            raise failure()
        size = item.get("size")
        if not isinstance(size, int) or not 100_000_000 < size <= MAX_ARCHIVE:
            raise failure()
        if item.get("browser_download_url") != release_asset_url(tag, filename):
            raise failure()
        packages.append(
            ClientPackage(
                platform=platform,
                filename=filename,
                url=release_asset_url(tag, filename),
                sha256=sha[7:],
                size=size,
            )
        )
    return tag, version, commit, packages, str(raw.get("body") or "")[:20000]
