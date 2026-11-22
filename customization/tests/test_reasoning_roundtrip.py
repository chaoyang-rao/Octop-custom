"""DeepSeek tool history must survive empty reasoning and old checkpoints."""

import unittest
from types import SimpleNamespace

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGenerationChunk
from langchain_openai import ChatOpenAI

from octop_harness.llm.factory import (
    _copy_reasoning_from_chunk,
    _copy_reasoning_from_response,
    _get_reasoning_aware_chat_openai,
)


class ReasoningRoundTripTests(unittest.TestCase):
    def test_empty_response_and_stream_reasoning_are_retained(self):
        for raw in [
            {"choices": [{"message": {"reasoning_content": ""}}]},
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(reasoning_content=""))]),
        ]:
            message = AIMessage(content="", tool_calls=[{"name": "lookup", "id": "call1", "args": {}}])
            result = SimpleNamespace(generations=[SimpleNamespace(message=message)])
            _copy_reasoning_from_response(result, raw)
            self.assertIn("reasoning_content", message.additional_kwargs)
            self.assertEqual(message.additional_kwargs["reasoning_content"], "")
        chunk = ChatGenerationChunk(message=AIMessageChunk(content=""))
        _copy_reasoning_from_chunk(chunk, {"choices": [{"delta": {"reasoning_content": ""}}]})
        self.assertEqual(chunk.message.additional_kwargs, {"reasoning_content": ""})

    def test_real_serializer_keeps_tool_pairs_reasoning_and_original_history(self):
        cls = _get_reasoning_aware_chat_openai(ChatOpenAI)
        model = cls(model="deepseek-v4-pro", api_key="fixture", extra_body={"thinking": {"type": "enabled"}})
        real = AIMessage(content="", additional_kwargs={"reasoning_content": "fixture evidence"}, tool_calls=[{"id": "call1", "name": "lookup", "args": {}}])
        old = AIMessage(content="", tool_calls=[{"id": "call2", "name": "lookup", "args": {}}])
        notice = AIMessage(content="Expert task completed", additional_kwargs={"speaker_agent_id": "member"})
        messages = [HumanMessage("Review evidence"), real, ToolMessage("one", tool_call_id="call1"), old, ToolMessage("two", tool_call_id="call2"), notice]
        tools = [{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object", "properties": {}}}}]
        payload = model._get_request_payload(messages, tools=tools)
        assistants = [m for m in payload["messages"] if m["role"] == "assistant"]
        self.assertEqual([m["reasoning_content"] for m in assistants], ["fixture evidence", "", ""])
        self.assertEqual([m["tool_call_id"] for m in payload["messages"] if m["role"] == "tool"], ["call1", "call2"])
        self.assertNotIn("reasoning_content", old.additional_kwargs)
        self.assertNotIn("reasoning_content", notice.additional_kwargs)

    def test_disabled_deepseek_and_other_providers_do_not_gain_fields(self):
        cls = _get_reasoning_aware_chat_openai(ChatOpenAI)
        messages = [AIMessage(content="", tool_calls=[{"id": "call1", "name": "lookup", "args": {}}])]
        tools = [{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object", "properties": {}}}}]
        for model_id, extra in [("gpt-5.4", {}), ("deepseek-v4-pro", {"thinking": {"type": "disabled"}}), ("deepseek-v4-pro", {"reasoning_effort": "none"})]:
            model = cls(model=model_id, api_key="fixture", extra_body=extra)
            wire = model._get_request_payload(messages, tools=tools)["messages"][0]
            self.assertNotIn("reasoning_content", wire)


if __name__ == "__main__":
    unittest.main()
