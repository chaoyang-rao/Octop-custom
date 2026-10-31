"""ACP callbacks projected into graph model events and approval requests."""

from __future__ import annotations

import asyncio
import json
import secrets
from typing import Any

from acp.schema import AllowedOutcome, DeniedOutcome, RequestPermissionResponse
from octop_harness.acp.client import ACPHostedClient
from octop_harness.acp.models import ACPRunnerConfig

from octop.infra.agents.native_cli.bridge import NativeToolBridge


class NativeACPClient(ACPHostedClient):
    def __init__(
        self,
        *,
        runner: str,
        config: ACPRunnerConfig,
        cwd: str,
        bridge: NativeToolBridge,
        events: asyncio.Queue[Any],
    ) -> None:
        super().__init__(runner_name=runner, runner_config=config, cwd=cwd)
        self.bridge = bridge
        self.events = events
        self.replaying = False
        self.permission_denied = False
        self.session_id = ""
        self.closing = False
        self.permissions_enabled = True
        self.usage_info: dict[str, Any] | None = None

    async def session_update(self, session_id: str, update: Any, **kwargs: Any) -> None:
        if self.closing or self.replaying or (self.session_id and session_id != self.session_id):
            return
        from acp.schema import AgentMessageChunk, AgentThoughtChunk, UsageUpdate

        if isinstance(update, UsageUpdate):
            self.usage_info = {"used": update.used, "size": update.size}
            return
        if isinstance(update, AgentMessageChunk | AgentThoughtChunk):
            text = self._extract_text_from_content(update.content)
            if text:
                for offset in range(0, len(text), 4096):
                    if self.closing:
                        return
                    await self.events.put(
                        {
                            "kind": "thinking" if isinstance(update, AgentThoughtChunk) else "text",
                            "text": text[offset : offset + 4096],
                        }
                    )

    async def request_permission(
        self, options: list[Any], session_id: str, tool_call: Any, **kwargs: Any
    ) -> Any:
        if not self.permissions_enabled or (self.session_id and session_id != self.session_id):
            return RequestPermissionResponse(outcome=DeniedOutcome(outcome="cancelled"))
        values = [
            option.model_dump(by_alias=True) if hasattr(option, "model_dump") else option
            for option in options
        ]
        once = next(
            (
                option
                for option in values
                if isinstance(option, dict) and option.get("kind") == "allow_once"
            ),
            None,
        )
        reject = next(
            (
                option
                for option in values
                if isinstance(option, dict) and option.get("kind") == "reject_once"
            ),
            None,
        )
        if once is None or self._permission_adapter.is_hard_blocked(tool_call):
            self.permission_denied = True
            return RequestPermissionResponse(outcome=DeniedOutcome(outcome="cancelled"))
        operation = (
            tool_call.model_dump(by_alias=True, exclude_none=True)
            if hasattr(tool_call, "model_dump")
            else dict(tool_call or {})
        )
        request_id = secrets.token_hex(12)
        result = await self.bridge.enqueue(
            "native_cli_permission",
            {
                "request_id": request_id,
                "runner": self.runner_name,
                "title": str(operation.get("title") or ""),
                "operation": operation,
            },
            permission=True,
        )
        approved = False
        try:
            value = json.loads(str(result["content"][0]["text"]))
            approved = (
                not result.get("isError")
                and value.get("approved") is True
                and value.get("request_id") == request_id
            )
        except (ValueError, KeyError, IndexError, TypeError):
            pass
        selected = once if approved else reject
        if not approved:
            self.permission_denied = True
        if selected is None:
            return RequestPermissionResponse(outcome=DeniedOutcome(outcome="cancelled"))
        option_id = str(selected.get("optionId") or selected.get("option_id") or "")
        return RequestPermissionResponse(
            outcome=AllowedOutcome(option_id=option_id, outcome="selected")
        )
