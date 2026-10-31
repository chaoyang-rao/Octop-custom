"""Independent ACP facade over Pi's official RPC and tool-extension interfaces."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import re
import secrets
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

import aiohttp
from acp import PROTOCOL_VERSION, RequestError, run_agent
from acp import schema as acp

from octop.i18n import tr


def failure() -> RequestError:
    # Do not relay provider diagnostics, credentials or subprocess stderr.
    return RequestError(-32000, "Pi RPC operation failed")


class PiRPC:
    def __init__(self, executable: str, arguments: list[str]) -> None:
        self.executable = executable
        self.arguments = arguments
        self.process: asyncio.subprocess.Process | None = None
        self.reader_task: asyncio.Task[None] | None = None
        self.pending: dict[str, asyncio.Future[Any]] = {}
        self.output: Any = None
        self.turn: asyncio.Future[dict[str, Any]] | None = None
        self.failed = False
        self.send_lock = asyncio.Lock()

    async def start(self, cwd: str, arguments: list[str], environment: dict[str, str]) -> None:
        self.process = await asyncio.create_subprocess_exec(
            self.executable,
            *self.arguments,
            *arguments,
            cwd=cwd,
            env=environment,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            limit=32 * 1024 * 1024,
        )
        self.reader_task = asyncio.create_task(self._read())

    async def _read(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        try:
            while raw := await self.process.stdout.readline():
                row = json.loads(raw)
                if not isinstance(row, dict):
                    raise failure()
                if row.get("type") == "response":
                    pending = self.pending.pop(str(row.get("id") or ""), None)
                    if pending is not None and not pending.done():
                        if row.get("success") is True:
                            pending.set_result(row.get("data") or {})
                        else:
                            pending.set_exception(failure())
                elif row.get("type") == "agent_settled":
                    if self.turn is not None and not self.turn.done():
                        self.turn.set_result(row)
                elif row.get("type") == "message_update":
                    update = row.get("assistantMessageEvent") or {}
                    if update.get("type") in {"text_delta", "thinking_delta"} and self.output:
                        await self.output(str(update.get("delta") or ""), update["type"])
                elif row.get("type") == "message_end":
                    message = row.get("message") or {}
                    if message.get("role") == "assistant" and message.get("stopReason") == "error":
                        self.failed = True
                elif row.get("type") == "extension_ui_request":
                    # No global extension/UI approval is auto-granted. All enabled
                    # tools are our bridge extension; anything else fails closed.
                    raise failure()
        except (asyncio.CancelledError, Exception):
            pass
        finally:
            for pending in self.pending.values():
                if not pending.done():
                    pending.set_exception(failure())
            self.pending.clear()
            if self.turn is not None and not self.turn.done():
                self.turn.set_exception(failure())

    async def call(self, command: str, **params: Any) -> Any:
        process = self.process
        if process is None or process.returncode is not None or process.stdin is None:
            raise failure()
        identifier = secrets.token_hex(12)
        future = asyncio.get_running_loop().create_future()
        self.pending[identifier] = future
        try:
            async with self.send_lock:
                process.stdin.write(
                    json.dumps({"id": identifier, "type": command, **params}).encode() + b"\n"
                )
                await process.stdin.drain()
            return await asyncio.wait_for(future, 25)
        finally:
            self.pending.pop(identifier, None)

    async def close(self) -> None:
        process = self.process
        if process is not None:
            if process.stdin is not None:
                process.stdin.close()
            try:
                await asyncio.wait_for(process.wait(), 2)
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
                await process.wait()
        if self.reader_task is not None:
            self.reader_task.cancel()
            await asyncio.gather(self.reader_task, return_exceptions=True)


class PiAgent:
    def __init__(self, executable: str, arguments: list[str]) -> None:
        self.rpc = PiRPC(executable, arguments)
        self.connection: Any = None
        self.session_id = ""
        self.session_dir: Path | None = None
        self.cwd = ""
        self.bridge_config: Path | None = None
        self.models: list[dict[str, Any]] = []
        self.selected_model = ""
        self.locale = os.environ.get("OCTOP_PI_LOCALE", "en")

    def on_connect(self, conn: Any) -> None:
        self.connection = conn

    async def initialize(self, protocol_version: int, **kwargs: Any) -> acp.InitializeResponse:
        return acp.InitializeResponse(
            protocol_version=PROTOCOL_VERSION,
            agent_capabilities=acp.AgentCapabilities(
                load_session=True,
                mcp_capabilities=acp.McpCapabilities(http=True),
                prompt_capabilities=acp.PromptCapabilities(image=True),
            ),
            agent_info=acp.Implementation(name="octop-pi-rpc", version="1.0"),
        )

    def _root(self) -> Path:
        namespace = os.environ.get("OCTOP_PI_SESSION_NAMESPACE", "")
        root = os.environ.get("OCTOP_PI_STATE_ROOT", "")
        if not root or not re.fullmatch(r"[a-f0-9]{64}", namespace):
            raise failure()
        return Path(root).resolve() / namespace

    async def _bridge(self, servers: list[Any] | None) -> dict[str, Any]:
        if not servers or len(servers) != 1:
            raise failure()
        raw = servers[0].model_dump(by_alias=True)
        parsed = urlsplit(str(raw.get("url") or ""))
        if (
            raw.get("type") != "http"
            or raw.get("name") != "octop-tools"
            or parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or not parsed.port
            or parsed.path != "/mcp"
            or parsed.query
            or parsed.username
            or parsed.fragment
        ):
            raise failure()
        headers = {str(row["name"]): str(row["value"]) for row in raw.get("headers", [])}
        async with (
            aiohttp.ClientSession(
                trust_env=False, timeout=aiohttp.ClientTimeout(total=15)
            ) as client,
            client.post(
                raw["url"],
                headers=headers,
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                allow_redirects=False,
            ) as response,
        ):
            if response.status != 200:
                raise failure()
            body = await response.content.read(4 * 1024 * 1024 + 1)
            if len(body) > 4 * 1024 * 1024:
                raise failure()
            payload = json.loads(body)
        tools = (payload.get("result") or {}).get("tools")
        if not isinstance(tools, list) or len(tools) > 500:
            raise failure()
        return {"url": raw["url"], "headers": headers, "tools": tools}

    def _modes(self) -> acp.SessionModeState:
        return acp.SessionModeState(
            current_mode_id="octop",
            available_modes=[
                acp.SessionMode(id="octop", name=tr("nativeCli.pi.graphTools", self.locale)),
                acp.SessionMode(id="read-only", name=tr("nativeCli.pi.readOnly", self.locale)),
            ],
        )

    def _options(self) -> list[acp.SessionConfigOptionSelect | acp.SessionConfigOptionBoolean]:
        return [
            acp.SessionConfigOptionSelect(
                id="model",
                name=tr("nativeCli.pi.model", self.locale),
                category="model",
                type="select",
                current_value=self.selected_model,
                options=[
                    acp.SessionConfigSelectOption(
                        value=f"{m['provider']}/{m['id']}", name=str(m.get("name") or m["id"])
                    )
                    for m in self.models
                ],
            )
        ]

    async def _start(
        self, cwd: str, servers: list[Any] | None, session_id: str, *, load: bool
    ) -> None:
        if self.session_id or not re.fullmatch(r"[a-f0-9]{32}", session_id):
            raise failure()
        directory = self._root() / session_id
        actual_cwd = str(Path(cwd).resolve())
        metadata = directory / "octop-session.json"
        arguments = [
            "--mode",
            "rpc",
            "--no-tools",
            "--no-extensions",
            "--no-mcp",
            "--no-skills",
            "--no-prompt-templates",
            "--no-themes",
            "--no-context-files",
            "--extension",
            str(Path(__file__).with_name("pi_tools.mjs")),
            "--session-dir",
            str(directory),
        ]
        if load:

            def restore() -> str:
                record = json.loads(metadata.read_text())
                path = directory / str(record.get("session_file") or "")
                if (
                    record.get("cwd") != actual_cwd
                    or not path.resolve().is_relative_to(directory.resolve())
                    or not path.is_file()
                ):
                    raise failure()
                return str(path)

            arguments.extend(["--session", await asyncio.to_thread(restore)])
        else:
            await asyncio.to_thread(directory.mkdir, parents=True, exist_ok=False, mode=0o700)
            arguments.extend(["--session-id", session_id])
        config = await self._bridge(servers)
        self.bridge_config = directory / (".bridge-" + secrets.token_hex(12) + ".json")

        def write_config() -> None:
            assert self.bridge_config is not None
            with self.bridge_config.open("x", encoding="utf-8") as stream:
                stream.write(json.dumps(config))
            self.bridge_config.chmod(0o600)

        await asyncio.to_thread(write_config)
        environment = dict(os.environ)
        environment["OCTOP_PI_TOOL_CONFIG"] = str(self.bridge_config)
        await self.rpc.start(actual_cwd, arguments, environment)
        self.session_id, self.session_dir, self.cwd = session_id, directory, actual_cwd
        self.rpc.output = self._output
        state = await self.rpc.call("get_state")
        available = await self.rpc.call("get_available_models")
        self.models = [
            m
            for m in available.get("models", [])[:300]
            if isinstance(m, dict)
            and isinstance(m.get("provider"), str)
            and isinstance(m.get("id"), str)
        ]
        model = state.get("model") or {}
        self.selected_model = (
            f"{model['provider']}/{model['id']}"
            if model.get("provider") and model.get("id")
            else ""
        )

    async def new_session(
        self, cwd: str, mcp_servers: list[Any] | None = None, **kwargs: Any
    ) -> acp.NewSessionResponse:
        await self._start(cwd, mcp_servers, secrets.token_hex(16), load=False)
        return acp.NewSessionResponse(
            session_id=self.session_id, modes=self._modes(), config_options=self._options()
        )

    async def load_session(
        self, cwd: str, session_id: str, mcp_servers: list[Any] | None = None, **kwargs: Any
    ) -> acp.LoadSessionResponse:
        await self._start(cwd, mcp_servers, session_id, load=True)
        return acp.LoadSessionResponse(modes=self._modes(), config_options=self._options())

    async def _output(self, text: str, kind: str) -> None:
        for offset in range(0, len(text), 4096):
            block = acp.TextContentBlock(type="text", text=text[offset : offset + 4096])
            update = (
                acp.AgentThoughtChunk(session_update="agent_thought_chunk", content=block)
                if kind == "thinking_delta"
                else acp.AgentMessageChunk(session_update="agent_message_chunk", content=block)
            )
            await self.connection.session_update(session_id=self.session_id, update=update)

    def _session(self, session_id: str) -> None:
        if not self.session_id or session_id != self.session_id:
            raise failure()

    async def set_session_mode(
        self, session_id: str, mode_id: str, **kwargs: Any
    ) -> acp.SetSessionModeResponse:
        self._session(session_id)
        if mode_id not in {"octop", "read-only"}:
            raise failure()
        # There are no Pi builtins or discovered tools. The authenticated Octop
        # conversation mode guards every operation through the Graph bridge.
        return acp.SetSessionModeResponse()

    async def set_config_option(
        self, config_id: str, session_id: str, value: str | bool, **kwargs: Any
    ) -> acp.SetSessionConfigOptionResponse:
        self._session(session_id)
        if config_id != "model" or value not in {f"{m['provider']}/{m['id']}" for m in self.models}:
            raise failure()
        provider, _, model_id = str(value).partition("/")
        await self.rpc.call("set_model", provider=provider, modelId=model_id)
        self.selected_model = str(value)
        return acp.SetSessionConfigOptionResponse(config_options=self._options())

    async def prompt(self, session_id: str, prompt: list[Any], **kwargs: Any) -> acp.PromptResponse:
        self._session(session_id)
        if self.rpc.turn is not None and not self.rpc.turn.done():
            raise failure()
        text = []
        images = []
        for block in prompt:
            if isinstance(block, acp.TextContentBlock):
                text.append(block.text)
            elif isinstance(block, acp.ImageContentBlock):
                images.append({"type": "image", "data": block.data, "mimeType": block.mime_type})
            else:
                raise failure()
        self.rpc.failed = False
        self.rpc.turn = asyncio.get_running_loop().create_future()
        accepted = await self.rpc.call("prompt", message="\n".join(text), images=images)
        if accepted.get("disposition") == "handled":
            return acp.PromptResponse(stop_reason="end_turn")
        completed = await self.rpc.turn
        if self.rpc.failed:
            raise failure()
        if completed.get("aborted"):
            return acp.PromptResponse(stop_reason="cancelled")
        state = await self.rpc.call("get_state")
        directory = self.session_dir
        session_file = Path(str(state.get("sessionFile") or ""))
        if directory is None or not session_file.resolve().is_relative_to(directory.resolve()):
            raise failure()

        def save() -> None:
            assert directory is not None
            if not session_file.is_file():
                raise failure()
            target = directory / "octop-session.json"
            temp = directory / (".meta-" + secrets.token_hex(8))
            temp.write_text(
                json.dumps(
                    {"cwd": self.cwd, "session_file": str(session_file.relative_to(directory))}
                )
            )
            temp.chmod(0o600)
            os.replace(temp, target)

        await asyncio.to_thread(save)
        return acp.PromptResponse(stop_reason="end_turn")

    async def cancel(self, session_id: str, **kwargs: Any) -> None:
        self._session(session_id)
        with contextlib.suppress(Exception):
            await self.rpc.call("abort")

    async def close_session(self, session_id: str, **kwargs: Any) -> acp.CloseSessionResponse:
        self._session(session_id)
        await self.close()
        return acp.CloseSessionResponse()

    async def close(self) -> None:
        await self.rpc.close()
        if self.bridge_config is not None:
            await asyncio.to_thread(self.bridge_config.unlink, missing_ok=True)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pi", required=True)
    parser.add_argument("--pi-arg", action="append", default=[])
    args = parser.parse_args()
    agent = PiAgent(args.pi, args.pi_arg)
    try:
        await run_agent(cast(Any, agent), stdio_buffer_limit_bytes=32 * 1024 * 1024)
    finally:
        await agent.close()


if __name__ == "__main__":
    asyncio.run(main())
