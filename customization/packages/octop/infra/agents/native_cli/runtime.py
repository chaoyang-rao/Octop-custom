"""Owner/agent/thread-bound ACP sessions with graph-mediated tool futures."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import sys
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, cast

from acp import PROTOCOL_VERSION, spawn_agent_process
from acp.schema import (
    AgentCapabilities,
    ClientCapabilities,
    EnvVariable,
    HttpHeader,
    HttpMcpServer,
    Implementation,
    McpServerStdio,
)
from acp.task import InMemoryMessageQueue
from octop_harness.acp.models import ACPRunnerConfig

from octop.infra.agents.native_cli.bridge import NativeCall, NativeToolBridge
from octop.infra.agents.native_cli.capabilities import capabilities_snapshot
from octop.infra.agents.native_cli.client import NativeACPClient
from octop.infra.agents.native_cli.config import NativeCLIError, NativeSpec
from octop.infra.agents.native_cli.dispatcher import OrderedNativeDispatcher
from octop.infra.agents.native_cli.launch import resolve_native_launch


@dataclass(frozen=True)
class NativeContext:
    user_id: int
    agent_id: str
    thread_id: str
    cwd: str
    spec: NativeSpec
    runner: ACPRunnerConfig
    locale: str = "en"
    model_override: str | None = None

    @property
    def key(self) -> str:
        return hashlib.sha256(
            f"{self.user_id}:{self.agent_id}:{self.thread_id}".encode()
        ).hexdigest()


@dataclass
class NativeConversation:
    context: NativeContext
    schemas_hash: str
    events: asyncio.Queue[Any]
    bridge: NativeToolBridge
    client: NativeACPClient
    connection: Any
    process: Any
    stack: AsyncExitStack
    session_id: str
    loaded: bool
    notification_queue: Any
    capabilities: dict[str, Any]
    prompt_task: asyncio.Task[None] | None = None
    delivered_ids: set[str] = field(default_factory=set)
    state: str = "idle"


class NativeRuntime:
    def __init__(
        self,
        *,
        settings_repo: Any,
        context_for: Callable[[str, str, int], Awaitable[NativeContext]],
    ) -> None:
        self.settings = settings_repo
        self.context_for = context_for
        self.sessions: dict[str, NativeConversation] = {}
        self.locks: dict[str, asyncio.Lock] = {}
        self.maintenance = asyncio.Lock()
        self.managed_packages: Any | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.last_failure: tuple[str, str] | None = None

    @staticmethod
    def _storage_key(context: NativeContext) -> str:
        return "native_cli.session." + context.key

    async def _record(self, context: NativeContext) -> dict[str, Any]:
        raw = await asyncio.to_thread(self.settings.get, self._storage_key(context))
        if not raw:
            return {}
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}

    async def _save(self, session: NativeConversation, state: str) -> None:
        session.state = state
        await asyncio.to_thread(
            self.settings.set,
            self._storage_key(session.context),
            json.dumps(
                {
                    "session_id": session.session_id,
                    "cwd": session.context.cwd,
                    "runner": session.context.spec.runner,
                    "state": state,
                    "schemas_hash": session.schemas_hash,
                }
            ),
        )

    async def conversation(
        self, context: NativeContext, schemas: list[dict[str, Any]]
    ) -> NativeConversation:
        async with self.maintenance:
            fresh = await self.context_for(context.agent_id, context.thread_id, context.user_id)
            if context.model_override is not None:
                fresh = replace(
                    fresh,
                    spec=replace(fresh.spec, model_id=context.model_override),
                    model_override=context.model_override,
                )
            if context.spec.mode_id == "read-only":
                fresh = replace(fresh, spec=replace(fresh.spec, mode_id="read-only"))
            return await self._conversation(fresh, schemas)

    async def _conversation(
        self, context: NativeContext, schemas: list[dict[str, Any]]
    ) -> NativeConversation:
        self.loop = asyncio.get_running_loop()
        digest = hashlib.sha256(
            json.dumps(
                {
                    "tools": schemas,
                    "runner": context.runner.to_dict(),
                    "spec": context.spec.to_dict(),
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        async with self.locks.setdefault(context.key, asyncio.Lock()):
            current = self.sessions.get(context.key)
            if current is not None:
                if os.path.normcase(os.path.realpath(current.context.cwd)) != os.path.normcase(
                    os.path.realpath(context.cwd)
                ):
                    raise NativeCLIError("cwd_changed", context.locale)
                if (
                    current.context.spec == context.spec
                    and current.schemas_hash == digest
                    and current.process.returncode is None
                ):
                    return current
                if current.prompt_task is not None and not current.prompt_task.done():
                    raise NativeCLIError("busy", context.locale)
                await self._close(current)
                self.sessions.pop(context.key, None)
                await asyncio.to_thread(self.settings.delete, self._storage_key(context))
            record = await self._record(context)
            if record and os.path.normcase(
                os.path.realpath(str(record.get("cwd") or ""))
            ) != os.path.normcase(os.path.realpath(context.cwd)):
                raise NativeCLIError("cwd_changed", context.locale)
            if record.get("state") in {"working", "waiting"}:
                # The previous process may already have performed external work.
                # Explicit close/reset is required before a fresh prompt.
                raise NativeCLIError("interrupted", context.locale)
            session = await self._open(context, schemas, digest, record)
            self.sessions[context.key] = session
            await self._save(session, "idle")
            return session

    async def _open(
        self,
        context: NativeContext,
        schemas: list[dict[str, Any]],
        digest: str,
        record: dict[str, Any],
        *,
        probe: bool = False,
    ) -> NativeConversation:
        events: asyncio.Queue[Any] = asyncio.Queue(maxsize=256)
        bridge = NativeToolBridge(events, schemas)
        stack = AsyncExitStack()
        await stack.__aenter__()
        stage = "bridge"
        try:
            await bridge.start()
            stack.push_async_callback(bridge.close)
            client = NativeACPClient(
                runner=context.spec.runner,
                config=context.runner,
                cwd=context.cwd,
                bridge=bridge,
                events=events,
            )
            environment = dict(os.environ)
            environment.update(context.runner.env)
            client.permissions_enabled = not probe
            notification_queue = InMemoryMessageQueue()
            stage = "spawn"
            command, arguments = await asyncio.to_thread(
                resolve_native_launch, context.runner.command, context.runner.args
            )
            connection, process = await stack.enter_async_context(
                spawn_agent_process(
                    cast(Any, client),
                    command,
                    *arguments,
                    cwd=context.cwd,
                    env=environment,
                    queue=notification_queue,
                    dispatcher_factory=lambda *args: OrderedNativeDispatcher(
                        queue=args[0],
                        supervisor=args[1],
                        store=args[2],
                        request_runner=args[3],
                        notification_runner=args[4],
                    ),
                    transport_kwargs={
                        "limit": min(context.runner.stdio_buffer_limit_bytes, 8 * 1024 * 1024),
                        "stderr": asyncio.subprocess.DEVNULL,
                    },
                )
            )
            async with asyncio.timeout(30):
                stage = "initialize"
                initialized = await connection.initialize(
                    protocol_version=PROTOCOL_VERSION,
                    client_capabilities=ClientCapabilities(),
                    client_info=Implementation(name="octop-native-cli", version="1.0"),
                )
                if initialized.protocol_version != PROTOCOL_VERSION:
                    raise NativeCLIError("protocol_failed", context.locale)
                capabilities = initialized.agent_capabilities or AgentCapabilities()
                if getattr(capabilities.mcp_capabilities, "http", False):
                    servers: list[Any] = [
                        HttpMcpServer(
                            type="http",
                            name="octop-tools",
                            url=bridge.url,
                            headers=[
                                HttpHeader(name="Authorization", value="Bearer " + bridge.token)
                            ],
                        )
                    ]
                else:
                    package_root = str(Path(__file__).resolve().parents[4])
                    servers = [
                        McpServerStdio(
                            name="octop-tools",
                            command=sys.executable,
                            args=["-m", "octop.infra.agents.native_cli.bridge_stdio"],
                            env=[
                                EnvVariable(name="OCTOP_NATIVE_BRIDGE_URL", value=bridge.url),
                                EnvVariable(name="OCTOP_NATIVE_BRIDGE_TOKEN", value=bridge.token),
                                EnvVariable(
                                    name="PYTHONPATH",
                                    value=package_root
                                    + os.pathsep
                                    + os.environ.get("PYTHONPATH", ""),
                                ),
                            ],
                        )
                    ]
                session_id = (
                    str(record.get("session_id") or "")
                    if record.get("runner") == context.spec.runner
                    and record.get("schemas_hash") == digest
                    else ""
                )
                loaded = bool(session_id and capabilities.load_session)
                setup: Any
                stage = "session"
                client.replaying = True
                try:
                    if loaded:
                        setup = await connection.load_session(
                            session_id=session_id, cwd=context.cwd, mcp_servers=servers
                        )
                    else:
                        setup = await connection.new_session(cwd=context.cwd, mcp_servers=servers)
                        session_id = setup.session_id
                    client.session_id = session_id
                    await notification_queue.join()
                finally:
                    client.replaying = False
                if context.spec.mode_id:
                    modes = getattr(setup, "modes", None)
                    available = {mode.id for mode in getattr(modes, "available_modes", [])}
                    if context.spec.mode_id not in available:
                        raise NativeCLIError("mode_unavailable", context.locale)
                    await connection.set_session_mode(
                        session_id=session_id, mode_id=context.spec.mode_id
                    )
                if context.spec.model_id:
                    options = getattr(setup, "config_options", None) or []
                    advertised = capabilities_snapshot(capabilities, setup)
                    if context.spec.model_id not in {
                        choice["value"] for choice in advertised["models"]
                    }:
                        raise NativeCLIError("model_unavailable", context.locale)
                    option = next(
                        (
                            item
                            for item in options
                            if getattr(item, "category", None) == "model"
                            or getattr(item, "id", None) == "model"
                        ),
                        None,
                    )
                    if option is None:
                        raise NativeCLIError("model_unavailable", context.locale)
                    selection = await connection.set_config_option(
                        session_id=session_id, config_id=option.id, value=context.spec.model_id
                    )
                    setup.config_options = selection.config_options
            snapshot = capabilities_snapshot(capabilities, setup, mode_id=context.spec.mode_id)
            snapshot.update(
                runner=context.spec.runner,
                origin_cwd=context.cwd,
                configured_model_id=context.spec.model_id,
            )
            await asyncio.to_thread(
                self.settings.set,
                self.capability_key(context.user_id, context.agent_id, context.spec.runner),
                json.dumps(snapshot),
            )
            bridge.supports_images = snapshot["image"]
            return NativeConversation(
                context,
                digest,
                events,
                bridge,
                client,
                connection,
                process,
                stack,
                session_id,
                loaded,
                notification_queue,
                snapshot,
            )
        except asyncio.CancelledError:
            await stack.aclose()
            raise
        except NativeCLIError:
            await stack.aclose()
            raise
        except Exception as exc:
            self.last_failure = (stage, type(exc).__name__)
            await stack.aclose()
            raise NativeCLIError("protocol_failed", context.locale) from None

    @staticmethod
    def capability_key(user_id: int, agent_id: str, runner: str) -> str:
        return (
            "native_cli.capabilities."
            + hashlib.sha256(f"{user_id}:{agent_id}:{runner}".encode()).hexdigest()
        )

    async def probe(self, context: NativeContext) -> dict[str, Any]:
        # No prompt, no graph tool definitions and no startup permission grants.
        safe = replace(context, spec=replace(context.spec, model_id="", mode_id=""))
        async with self.maintenance:
            session = await self._open(safe, [], "capability-probe", {}, probe=True)
            try:
                return session.capabilities
            finally:
                await self._close(session)

    async def begin(self, session: NativeConversation, prompt: list[Any]) -> None:
        if session.prompt_task is not None:
            raise NativeCLIError("busy", session.context.locale)
        session.client.permission_denied = False
        session.client.usage_info = None
        await self._save(session, "working")

        async def run() -> None:
            try:
                outcome = await session.connection.prompt(
                    session_id=session.session_id, prompt=prompt
                )
                await session.notification_queue.join()
                reason = str(getattr(outcome, "stop_reason", "end_turn"))
                await session.events.put({"kind": "done", "reason": reason})
            except asyncio.CancelledError:
                raise
            except Exception:
                await session.events.put({"kind": "error"})

        session.prompt_task = asyncio.create_task(
            run(), name=f"native-cli-{session.context.agent_id}-{session.context.thread_id}"
        )

    async def next_event(self, session: NativeConversation) -> Any:
        event = await session.events.get()
        if isinstance(event, NativeCall):
            session.delivered_ids.add(event.call_id)
            await self._save(session, "waiting")
        elif event.get("kind") in {"done", "error"}:
            if session.prompt_task:
                await session.prompt_task
                session.prompt_task = None
            await self._save(session, "idle" if event["kind"] == "done" else "failed")
        return event

    async def close_thread(self, *, user_id: int, agent_id: str, thread_id: str) -> None:
        key = hashlib.sha256(f"{user_id}:{agent_id}:{thread_id}".encode()).hexdigest()
        async with self.locks.setdefault(key, asyncio.Lock()):
            current = self.sessions.get(key)
            if current:
                await self._close(current)
                self.sessions.pop(key, None)
            await asyncio.to_thread(self.settings.delete, "native_cli.session." + key)

    async def close_agent(self, agent_id: str) -> None:
        for key, current in list(self.sessions.items()):
            if current.context.agent_id == agent_id:
                async with self.locks.setdefault(key, asyncio.Lock()):
                    if self.sessions.get(key) is current:
                        await self._close(current)
                        self.sessions.pop(key, None)

    async def _close(self, session: NativeConversation) -> None:
        session.client.closing = True
        while not session.events.empty():
            with contextlib.suppress(asyncio.QueueEmpty):
                session.events.get_nowait()
        if session.prompt_task is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(
                    session.connection.cancel(session_id=session.session_id), timeout=2
                )
            session.prompt_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await session.prompt_task
            session.prompt_task = None
        await session.bridge.close()
        import psutil

        def descendants() -> list[Any]:
            try:
                return list(psutil.Process(session.process.pid).children(recursive=True))
            except psutil.Error:
                return []

        children = await asyncio.to_thread(descendants)
        try:
            await session.stack.aclose()
        finally:
            for child in children:
                with contextlib.suppress(psutil.Error):
                    child.kill()

    async def aclose(self) -> None:
        if self.managed_packages is not None:
            await self.managed_packages.aclose()
        sessions = list(self.sessions.values())
        self.sessions.clear()
        for session in sessions:
            await self._close(session)

    def close(self) -> None:
        loop = self.loop
        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(self.aclose(), loop)
