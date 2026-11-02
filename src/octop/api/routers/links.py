"""Link metadata helpers for the dashboard (titles for pasted URLs)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from octop.api.deps import current_user
from octop.infra.knowledge.fetch import fetch_page_title

router = APIRouter()

_CACHE: dict[str, str] = {}
_CACHE_LIMIT = 500


class LinkTitleBody(BaseModel):
    url: str = Field(max_length=2048)


@router.post("/link-titles", summary="Resolve page titles for links")
def link_titles(
    body: list[LinkTitleBody],
    user: Any = Depends(current_user),
) -> list[dict[str, str]]:
    """Return ``{url, title}`` for each URL; ``title`` is empty when unavailable."""
    out: list[dict[str, str]] = []
    for item in body[:20]:
        url = item.url.strip()
        if not url:
            continue
        if url in _CACHE:
            out.append({"url": url, "title": _CACHE[url]})
            continue
        title = fetch_page_title(url)
        if len(_CACHE) >= _CACHE_LIMIT:
            _CACHE.clear()
        _CACHE[url] = title
        out.append({"url": url, "title": title})
    return out


__all__ = ["router"]
