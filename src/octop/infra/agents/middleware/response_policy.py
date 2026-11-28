"""Shared Octop answer guidance, independent of expert persona and tool permissions."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any

from deepagents.middleware._utils import append_to_system_message
from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import HumanMessage, SystemMessage

from octop.i18n import tr

_LABEL = re.compile(r"^\s*(?:【[^】]{0,120}】|\[[^\]]{0,120}\])\s*")
_REWRITE = re.compile(
    r"^(?:(?:请你|请|麻烦|帮我|替我|给我|可以|能不能|能否)\s*){0,3}"
    r"(?:(?:改写|改短|精简|润色|压缩|总结|汇总|整理|归纳)"
    r"|(?:把|将)[^\n]{0,120}(?:改写|改短|精简|润色|压缩|总结|汇总|整理成|归纳))"
    r"|^(?:(?:please|can you|could you|would you)\s+){0,2}"
    r"(?:rewrite|rephrase|shorten|polish|summari[sz]e|condense)\b",
    re.IGNORECASE,
)
_EXPLANATION = re.compile(
    r"^(?:(?:请你|请|麻烦|please)\s*)?(?:如何|怎么|为什么|什么是|什么叫|解释|how\b|why\b|what\b|explain\b)",
    re.IGNORECASE,
)
_OTHER_WORK = re.compile(
    r"代码|函数|接口|组件|脚本|文件夹|目录|工作区|故事|小说|诗歌|剧本|创作|续写"
    r"|\b(?:code|function|class|api|sql|html|css|python|typescript|component|script|story|fiction|poem|creative)\b",
    re.IGNORECASE,
)
_NEGATED = re.compile(
    r"^(?:(?:请你|请|please)\s*)?(?:不要|不用|别|不需要|先不|暂不|do not\b|don't\b)", re.IGNORECASE
)


def _current_user_text(request: ModelRequest[Any]) -> str:
    user = next((m for m in reversed(request.messages) if isinstance(m, HumanMessage)), None)
    if user is None:
        return ""
    original = user
    rows = request.state.get("messages")
    if user.id is not None and isinstance(rows, list):
        original = next(
            (m for m in reversed(rows) if isinstance(m, HumanMessage) and m.id == user.id), user
        )
    if original.additional_kwargs.get("octop_internal_event"):
        return ""
    display = original.additional_kwargs.get("octop_display_text")
    text = display if isinstance(display, str) else original.text
    return text.split("\n\n<memory-context>", 1)[0]


def _rewrite_requested(request: ModelRequest[Any]) -> bool:
    if request.response_format is not None or any(
        isinstance(m, SystemMessage) and m.additional_kwargs.get("octop_internal_event")
        for m in request.messages
    ):
        return False
    text = _LABEL.sub("", _current_user_text(request), count=1)
    instruction = re.split(r"[：:\n]", text, maxsplit=1)[0][:512].strip()
    if (
        _EXPLANATION.search(instruction)
        or _NEGATED.search(instruction)
        or _OTHER_WORK.search(instruction)
    ):
        return False
    return _REWRITE.search(instruction) is not None


class ResponsePolicyMiddleware(AgentMiddleware[Any, Any]):
    """Add localized product guidance without rewriting messages or model output."""

    def __init__(self, *, locale: str) -> None:
        self._prompt = tr("agents.response_policy", locale)
        self._rewrite_prompt = tr("agents.response_rewrite_focus", locale)

    def _with_policy(self, request: ModelRequest[Any]) -> ModelRequest[Any]:
        system = request.system_message
        existing = system.text if system is not None else ""
        guidance = [] if self._prompt in existing else [self._prompt]
        if _rewrite_requested(request) and self._rewrite_prompt not in existing:
            guidance.append(self._rewrite_prompt)
        if not guidance:
            return request
        return request.override(
            system_message=append_to_system_message(system, "\n\n".join(guidance)),
        )

    def wrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], ModelResponse[Any]],
    ) -> ModelResponse[Any]:
        return handler(self._with_policy(request))

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        return await handler(self._with_policy(request))
