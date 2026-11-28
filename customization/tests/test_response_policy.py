"""Answer focus must reach the model through the packaged deepagents graph."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from octop.i18n import tr
from octop.infra.agents.middleware.response_policy import ResponsePolicyMiddleware


class _Model(FakeMessagesListChatModel):
    seen: list[Any] = []

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        return self

    def _generate(
        self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> Any:
        self.seen.append(list(messages))
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


class ResponsePolicyGraphTests(unittest.IsolatedAsyncioTestCase):
    async def test_focus_reaches_native_graph_without_mutating_user_input(self) -> None:
        with TemporaryDirectory(prefix="octop-response-policy-") as directory:
            model = _Model(responses=[AIMessage(content="ready")], seen=[])
            graph = create_deep_agent(
                model=model,
                backend=FilesystemBackend(root_dir=Path(directory)),
                system_prompt="Keep the expert's business evidence requirements.",
                middleware=[ResponsePolicyMiddleware(locale="zh")],
            )
            question = HumanMessage(content="把通知改短一点：周五前提交培训需求。")
            result = await graph.ainvoke({"messages": [question]})
            self.assertEqual(result["messages"][-1].text, "ready")
            self.assertEqual(len(model.seen), 1)
            prompt = "\n".join(m.text for m in model.seen[0] if isinstance(m, SystemMessage))
            self.assertIn(tr("agents.response_rewrite_focus", "zh"), prompt)
            self.assertIn("business evidence requirements", prompt)
            self.assertEqual(
                [m.text for m in model.seen[0] if isinstance(m, HumanMessage)],
                [question.text],
            )
