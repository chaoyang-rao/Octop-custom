"""Conservative, opt-in notification summaries; never forward tool structures."""

from __future__ import annotations

import re

from octop.infra.utils.llm_text import prepare_channel_text

_SENSITIVE = re.compile(
    r"(?:密码|密钥|口令|令牌|凭据|验证码|私钥|BEGIN [A-Z ]*KEY|https?://|```|"
    r"\b(?:password|secret|authorization|cookie|token|bearer|access[_ -]?token|api[_ -]?key|private[_ -]?key|otp)\b|"
    r"(?:sk-|ghp_|github_pat_|xox[baprs]-|eyJ)[A-Za-z0-9_./+-]+|[A-Za-z0-9_+/=-]{12,}|\b(?=[A-Za-z0-9_-]*[A-Za-z])(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]{4,}\b)",
    re.IGNORECASE,
)


def redact_summary(text: str) -> str | None:
    """If credential-like content is present, fall back to the generic notice.

    This is intentionally conservative. Only a small plain answer excerpt is
    eligible, and the recipient must have explicitly enabled previews.
    """
    if len(text) > 64000:
        return None
    visible = prepare_channel_text(text, show_thinking=False)
    if _SENSITIVE.search(visible):
        return None
    visible = re.sub(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b", "•••", visible)
    visible = re.sub(r"\d{4,}", "•••", visible)
    visible = re.sub(r"[\x00-\x1f\x7f]+", " ", visible)
    visible = " ".join(visible.split()).strip()
    return visible[:160] or None
