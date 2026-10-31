"""Real local ACP subprocess used for graph/approval tests; no model network."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import aiohttp
from acp import PROTOCOL_VERSION


async def main():
    session = "native-test-session"
    bridge = None
    pending = {}
    tasks = set()
    cancel = asyncio.Event()
    mode = os.environ.get("FAKE_NATIVE_MODE", "tool")
    marker = os.environ.get("FAKE_NATIVE_MARKER")

    def record(value):
        if marker:
            with Path(marker).open("a", encoding="utf-8") as target:
                target.write(json.dumps(value) + "\n")

    def send(value):
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", **value}) + "\n")
        sys.stdout.flush()

    def text(value):
        send(
            {
                "method": "session/update",
                "params": {
                    "sessionId": session,
                    "update": {
                        "sessionUpdate": "agent_message_chunk",
                        "content": {"type": "text", "text": value},
                    },
                },
            }
        )

    async def prompt(identifier, params):
        record({"event": "prompt", "cwd": os.getcwd(), "prompt": params.get("prompt")})
        if mode == "wait":
            text("working")
            await cancel.wait()
            send({"id": identifier, "result": {"stopReason": "cancelled"}})
            return
        if mode == "permission":
            future = asyncio.get_running_loop().create_future()
            pending["permission"] = future
            send(
                {
                    "id": "permission",
                    "method": "session/request_permission",
                    "params": {
                        "sessionId": session,
                        "options": [
                            {"optionId": "once", "name": "Once", "kind": "allow_once"},
                            {"optionId": "always", "name": "Always", "kind": "allow_always"},
                            {"optionId": "reject", "name": "Reject", "kind": "reject_once"},
                        ],
                        "toolCall": {
                            "toolCallId": "vendor-action",
                            "title": "Write a local test marker",
                            "kind": "execute",
                            "rawInput": {"command": "fake-local-action"},
                        },
                    },
                }
            )
            answer = await future
            outcome = answer.get("outcome", {})
            record({"event": "permission", "outcome": outcome})
            if outcome.get("optionId") == "once":
                record({"event": "action"})
            text("approved" if outcome.get("optionId") == "once" else "rejected")
        elif mode == "tool":
            assert bridge is not None
            headers = {header["name"]: header["value"] for header in bridge["headers"]}
            async with (
                aiohttp.ClientSession() as client,
                client.post(
                    bridge["url"],
                    headers=headers,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {"name": "recorded_tool", "arguments": {"value": "from-native"}},
                    },
                ) as response,
            ):
                answer = await response.json()
            record({"event": "tool_result", "result": answer})
            text(
                "Octop tool completed"
                if not answer.get("result", {}).get("isError")
                else "Octop tool rejected"
            )
        else:
            text("native text")
        send({"id": identifier, "result": {"stopReason": "end_turn"}})

    while True:
        line = await asyncio.to_thread(sys.stdin.readline)
        if not line:
            break
        value = json.loads(line)
        method = value.get("method")
        identifier = value.get("id")
        params = value.get("params", {})
        if method == "initialize":
            send(
                {
                    "id": identifier,
                    "result": {
                        "protocolVersion": PROTOCOL_VERSION,
                        "agentCapabilities": {
                            "loadSession": os.environ.get("FAKE_NATIVE_LOAD", "1") == "1",
                            "mcpCapabilities": {"http": True},
                            "promptCapabilities": {
                                "image": os.environ.get("FAKE_NATIVE_IMAGE") == "1",
                                "audio": os.environ.get("FAKE_NATIVE_AUDIO") == "1",
                                "embeddedContext": os.environ.get("FAKE_NATIVE_RESOURCE") == "1",
                            },
                        },
                        "agentInfo": {"name": "fake-native", "version": "1"},
                    },
                }
            )
        elif method in {"session/new", "session/load"}:
            servers = params.get("mcpServers", [])
            bridge = servers[0] if servers else None
            if method == "session/load":
                session = params["sessionId"]
            record({"event": method, "cwd": params["cwd"]})
            result = {
                "configOptions": [
                    {
                        "type": "select",
                        "id": "model",
                        "name": "Model",
                        "category": "model",
                        "currentValue": "fake-a",
                        "options": [
                            {"value": "fake-a", "name": "Fake A"},
                            {"value": "fake-b", "name": "Fake B"},
                        ],
                    }
                ],
                "modes": {
                    "currentModeId": "read-only",
                    "availableModes": [{"id": "read-only", "name": "Read only"}],
                },
            }
            if method == "session/new":
                result["sessionId"] = session
            send({"id": identifier, "result": result})
        elif method == "session/set_config_option":
            record({"event": "model_value", "value": params.get("value")})
            send(
                {
                    "id": identifier,
                    "result": {
                        "configOptions": [
                            {
                                "type": "select",
                                "id": "model",
                                "name": "Model",
                                "category": "model",
                                "currentValue": params.get("value"),
                                "options": [
                                    {"value": "fake-a", "name": "Fake A"},
                                    {"value": "fake-b", "name": "Fake B"},
                                ],
                            }
                        ]
                    },
                }
            )
        elif method == "session/set_mode":
            send({"id": identifier, "result": {}})
        elif method == "session/prompt":
            task = asyncio.create_task(prompt(identifier, params))
            tasks.add(task)
            task.add_done_callback(tasks.discard)
        elif method == "session/cancel":
            cancel.set()
        elif method == "session/close":
            send({"id": identifier, "result": {}})
        elif identifier in pending:
            pending.pop(identifier).set_result(value.get("result", {}))
        elif identifier is not None:
            send({"id": identifier, "result": {}})
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
