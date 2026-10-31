"""Real ACP media frames and advertised choices; unsupported never means text-only."""

from __future__ import annotations

import base64
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from acp.schema import EmbeddedResourceContentBlock, ImageContentBlock
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from octop_gateway.models import FileContent, ImageContent
from tests.unit.agents.native_cli.test_graph_acp import config, events, runtime_for

from octop.infra.agents.native_cli.config import NativeCLIError
from octop.infra.agents.native_cli.media import (
    acp_content,
    mcp_content,
    media_block,
    native_attachment_content,
)
from octop.infra.agents.native_cli.model import NativeACPChatModel

_DATA = base64.b64encode(b"synthetic image bytes").decode()


@pytest.mark.asyncio
async def test_image_prompt_is_real_acp_image_and_not_base64_text(tmp_path):
    runtime, marker = runtime_for(tmp_path, mode="text")
    original = runtime.context_for

    async def context(*args):
        value = await original(*args)
        return replace(
            value, runner=replace(value.runner, env={**value.runner.env, "FAKE_NATIVE_IMAGE": "1"})
        )

    runtime.context_for = context
    graph = create_agent(
        model=NativeACPChatModel(runtime=runtime, agent_id="agent1", owner_id=1), tools=[]
    )
    try:
        await graph.ainvoke(
            {
                "messages": [
                    HumanMessage(
                        content=[
                            {"type": "text", "text": "look"},
                            {
                                "type": "image_url",
                                "image_url": {"url": "data:image/png;base64," + _DATA},
                            },
                        ]
                    )
                ]
            },
            config=config(),
        )
        prompt = next(item["prompt"] for item in events(marker) if item["event"] == "prompt")
        image = next(item for item in prompt if item["type"] == "image")
        assert image["data"] == _DATA and image["mimeType"] == "image/png"
        assert _DATA not in prompt[0]["text"]
    finally:
        await runtime.aclose()


@pytest.mark.asyncio
async def test_unadvertised_image_fails_before_model_prompt(tmp_path):
    runtime, marker = runtime_for(tmp_path, mode="text")
    graph = create_agent(
        model=NativeACPChatModel(runtime=runtime, agent_id="agent1", owner_id=1), tools=[]
    )
    try:
        with pytest.raises(NativeCLIError) as error:
            await graph.ainvoke(
                {
                    "messages": [
                        HumanMessage(
                            content=[
                                {
                                    "type": "image_url",
                                    "image_url": {"url": "data:image/png;base64," + _DATA},
                                }
                            ]
                        )
                    ]
                },
                config=config(),
            )
        assert error.value.code == "unsupported_media"
        assert not any(item["event"] == "prompt" for item in events(marker))
    finally:
        await runtime.aclose()


@pytest.mark.asyncio
async def test_mcp_image_result_stays_image_not_json_text(tmp_path):
    runtime, marker = runtime_for(tmp_path, mode="tool")
    original = runtime.context_for

    async def context(*args):
        value = await original(*args)
        return replace(
            value, runner=replace(value.runner, env={**value.runner.env, "FAKE_NATIVE_IMAGE": "1"})
        )

    runtime.context_for = context

    @tool
    async def recorded_tool(value: str) -> list:
        """Return a synthetic browser screenshot."""
        return [{"type": "image_url", "image_url": {"url": "data:image/png;base64," + _DATA}}]

    graph = create_agent(
        model=NativeACPChatModel(runtime=runtime, agent_id="agent1", owner_id=1),
        tools=[recorded_tool],
    )
    try:
        await graph.ainvoke({"messages": [HumanMessage(content="screen")]}, config=config())
        result = next(
            item["result"]["result"] for item in events(marker) if item["event"] == "tool_result"
        )
        assert result["content"] == [{"type": "image", "data": _DATA, "mimeType": "image/png"}]
    finally:
        await runtime.aclose()


@pytest.mark.asyncio
async def test_probe_reads_actual_models_modes_without_any_prompt(tmp_path):
    runtime, marker = runtime_for(tmp_path, mode="text")
    context = await runtime.context_for("agent1", "thread1", 1)
    try:
        result = await runtime.probe(context)
        assert [choice["value"] for choice in result["models"]] == ["fake-a", "fake-b"]
        assert [choice["value"] for choice in result["modes"]] == ["read-only"]
        assert result["config_options"][0]["id"] == "model"
        assert not any(item["event"] == "prompt" for item in events(marker))
        assert runtime.sessions == {}
        assert runtime.settings.get(runtime.capability_key(1, "agent1", "fake"))
    finally:
        await runtime.aclose()


def test_embedded_file_resource_requires_declared_capability():
    block = media_block(
        {
            "type": "file",
            "file": {"filename": "report.pdf", "file_data": "data:application/pdf;base64," + _DATA},
        }
    )
    with pytest.raises(NativeCLIError):
        acp_content(block, {"embedded_context": False})
    assert isinstance(acp_content(block, {"embedded_context": True}), EmbeddedResourceContentBlock)
    assert isinstance(
        acp_content({"type": "image", "data": _DATA, "mimeType": "image/png"}, {"image": True}),
        ImageContentBlock,
    )
    assert (
        mcp_content([{"type": "image", "data": _DATA, "mimeType": "image/png"}])[0]["type"]
        == "image"
    )


@pytest.mark.asyncio
async def test_workspace_image_file_and_audio_are_typed_real_acp_prompt_blocks(tmp_path):
    runtime, marker = runtime_for(tmp_path, mode="text")
    original = runtime.context_for

    async def context(*args):
        value = await original(*args)
        return replace(
            value,
            runner=replace(
                value.runner,
                env={
                    **value.runner.env,
                    "FAKE_NATIVE_IMAGE": "1",
                    "FAKE_NATIVE_RESOURCE": "1",
                    "FAKE_NATIVE_AUDIO": "1",
                },
            ),
        )

    runtime.context_for = context
    backend = SimpleNamespace(read=AsyncMock(return_value=b"synthetic attachment bytes"))
    message = SimpleNamespace(
        content=[
            ImageContent(local_path="inbound/image.png", mime_type="image/png"),
            FileContent(
                local_path="inbound/report.pdf", filename="report.pdf", mime_type="application/pdf"
            ),
            FileContent(
                local_path="inbound/audio.wav", filename="audio.wav", mime_type="audio/wav"
            ),
        ]
    )
    content = await native_attachment_content(message, "Read uploaded attachments", backend)
    graph = create_agent(
        model=NativeACPChatModel(runtime=runtime, agent_id="agent1", owner_id=1), tools=[]
    )
    try:
        await graph.ainvoke({"messages": [HumanMessage(content=content)]}, config=config())
        prompt = next(item["prompt"] for item in events(marker) if item["event"] == "prompt")
        assert [block["type"] for block in prompt] == ["text", "image", "resource", "audio"]
        assert prompt[2]["resource"]["mimeType"] == "application/pdf"
        assert len(backend.read.await_args_list) == 3
    finally:
        await runtime.aclose()


@pytest.mark.asyncio
async def test_ingress_attachment_missing_or_unbounded_is_explicit_failure():
    backend = SimpleNamespace(read=AsyncMock(return_value=b"x" * (12 * 1024 * 1024 + 1)))
    message = SimpleNamespace(
        content=[ImageContent(local_path="inbound/large.png", mime_type="image/png")]
    )
    with pytest.raises(NativeCLIError) as error:
        await native_attachment_content(message, "existing hint", backend)
    assert error.value.code == "input_too_large"
    message.content = [
        ImageContent(url="https://external.example/image.png", mime_type="image/png")
    ]
    with pytest.raises(NativeCLIError) as error:
        await native_attachment_content(message, "existing hint", backend)
    assert error.value.code == "unsupported_media"
