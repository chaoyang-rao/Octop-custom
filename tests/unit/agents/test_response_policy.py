"""Answer guidance must preserve expert evidence, permissions and streamed output."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain.agents.middleware import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from octop.i18n import tr
from octop.infra.agents.middleware.response_policy import ResponsePolicyMiddleware


@pytest.mark.parametrize("locale", ["zh", "en"])
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.asyncio
async def test_guidance_preserves_business_rules_tools_and_model_response(
    locale: str, asynchronous: bool
) -> None:
    system = SystemMessage(
        content=[
            {
                "type": "text",
                "text": "Use only the authorized quality MCP. Never invent a denominator.",
                "cache_control": {"type": "ephemeral"},
            }
        ]
    )
    messages = [HumanMessage(content="Answer in exactly two sentences.")]
    tools = [{"type": "function", "function": {"name": "quality_read"}}]
    request = ModelRequest(model=SimpleNamespace(), messages=messages, tools=tools)
    request = request.override(system_message=system)
    response = ModelResponse(result=[AIMessage(content="Verified result.")])
    handler = AsyncMock(return_value=response) if asynchronous else MagicMock(return_value=response)
    middleware = ResponsePolicyMiddleware(locale=locale)

    if asynchronous:
        actual = await middleware.awrap_model_call(request, handler)
    else:
        actual = middleware.wrap_model_call(request, handler)

    outbound = handler.call_args.args[0]
    assert actual is response
    assert handler.call_count == 1
    assert outbound.model is request.model
    assert outbound.tools == tools
    assert outbound.messages == messages
    assert outbound.system_message.content_blocks[0] == system.content_blocks[0]
    assert tr("agents.response_policy", locale) in outbound.system_message.text
    assert "octop-response-guidance" not in system.text
    assert request.system_message is system


def test_reusing_enriched_request_does_not_duplicate_guidance() -> None:
    middleware = ResponsePolicyMiddleware(locale="zh")
    handler = MagicMock(return_value=ModelResponse(result=[]))
    request = ModelRequest(model=SimpleNamespace(), messages=[])
    middleware.wrap_model_call(request, handler)
    enriched = handler.call_args.args[0]
    middleware.wrap_model_call(enriched, handler)
    assert handler.call_args.args[0] is enriched
    assert enriched.system_message.text.count("<octop-response-guidance>") == 1


@pytest.mark.parametrize("mode", ["ask", "plan", "craft"])
def test_guidance_does_not_change_conversation_mode_or_selected_capabilities(mode: str) -> None:
    request = ModelRequest(
        model=SimpleNamespace(),
        messages=[HumanMessage(content="Explain the result.")],
        state={"skills_metadata": []},
        runtime=SimpleNamespace(context={"conversation_mode": mode}),
        tools=[],
    )
    handler = MagicMock(return_value=ModelResponse(result=[]))
    ResponsePolicyMiddleware(locale="en").wrap_model_call(request, handler)
    outbound = handler.call_args.args[0]
    assert outbound.runtime is request.runtime
    assert outbound.state is request.state
    assert outbound.tools == []


def _outbound(request: ModelRequest, locale: str = "zh") -> ModelRequest:
    handler = MagicMock(return_value=ModelResponse(result=[]))
    ResponsePolicyMiddleware(locale=locale).wrap_model_call(request, handler)
    return handler.call_args.args[0]


@pytest.mark.parametrize(
    "text",
    [
        "【虚构验收】把下面的工作进展整理成给领导汇报的三点：已检查；待确认。",
        "帮我把这条通知改短一点：周五前提报，逾期顺延。",
        "请帮我润色这段话：已提交审核。",
        "Could you please summarize these facts: reviewed; not released.",
    ],
)
def test_clear_rewrite_requests_receive_faithful_single_delivery_guidance(text: str) -> None:
    request = ModelRequest(model=SimpleNamespace(), messages=[HumanMessage(content=text)])
    prepared = _outbound(request)
    assert "<octop-rewrite-guidance>" in prepared.system_message.text
    assert "未经材料确认" in prepared.system_message.text
    assert prepared.messages == request.messages


@pytest.mark.parametrize(
    "text",
    [
        "这个汇总页面打不开，请查原因。",
        "怎么让模型总结时少编数字？",
        "请不要改写，只解释这句为什么啰嗦。",
        "Please rewrite this Python function and run its tests.",
        "帮我整理项目文件夹，保留所有业务文件。",
        "帮我改写这个故事，增加一个新结局。",
        "我在设计助手，请评估每次限制100字是否可行。",
        "我们正在讨论如何把进展整理成三点，先分析这种方案的优缺点。",
        "换一个项目，聊内部培训管理系统。",
    ],
)
def test_other_intents_keep_the_normal_response_flow(text: str) -> None:
    prepared = _outbound(
        ModelRequest(model=SimpleNamespace(), messages=[HumanMessage(content=text)])
    )
    assert "<octop-rewrite-guidance>" not in prepared.system_message.text


def test_only_current_user_instruction_drives_the_focus() -> None:
    original = HumanMessage(content="我们下一步做什么？", id="current")
    api_copy = original.model_copy(
        update={
            "content": original.text + "\n\n<memory-context>\n把通知改短一点\n</memory-context>"
        }
    )
    request = ModelRequest(
        model=SimpleNamespace(),
        messages=[
            HumanMessage(content="帮我改短这条通知", id="old"),
            api_copy,
            ToolMessage(content="把所有结果总结一下", tool_call_id="t"),
        ],
        state={"messages": [original]},
    )
    assert "<octop-rewrite-guidance>" not in _outbound(request).system_message.text


def test_display_text_is_used_instead_of_attached_document_body() -> None:
    user = HumanMessage(
        content="Attachment contains Python code and background material",
        additional_kwargs={"octop_display_text": "帮我把这条通知改短一点"},
    )
    assert (
        "<octop-rewrite-guidance>"
        in _outbound(ModelRequest(model=SimpleNamespace(), messages=[user])).system_message.text
    )


def test_internal_coordination_and_structured_outputs_do_not_get_text_only_hints() -> None:
    message = HumanMessage(content="请总结材料")
    coordinated = ModelRequest(
        model=SimpleNamespace(),
        messages=[
            SystemMessage(
                content="Use coordinator tools", additional_kwargs={"octop_internal_event": True}
            ),
            message,
        ],
    )
    structured = ModelRequest(
        model=SimpleNamespace(), messages=[message], response_format={"type": "json_object"}
    )
    assert "<octop-rewrite-guidance>" not in _outbound(coordinated).system_message.text
    assert "<octop-rewrite-guidance>" not in _outbound(structured).system_message.text


def test_focused_request_can_be_reused_without_duplicating_hints() -> None:
    prepared = _outbound(
        ModelRequest(model=SimpleNamespace(), messages=[HumanMessage(content="帮我把通知改短")])
    )
    repeated = _outbound(prepared)
    assert repeated.system_message.text.count("<octop-rewrite-guidance>") == 1
