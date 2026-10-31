"""Expert execution selection, runner diagnostics and explicit session reset."""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import shutil
from pathlib import Path
from typing import Any, cast

from octop_harness.acp.models import ACPRunnerConfig

from octop.infra.agents.experts.copy import owned_expert
from octop.infra.agents.native_cli.config import NativeCLIError, NativeSpec
from octop.infra.agents.native_cli.launch import resolve_native_launch
from octop.infra.agents.native_cli.runtime import NativeContext
from octop.infra.agents.settings.cli_reuse import _busy

_VERSION = re.compile(
    r"^(?:(?:codex(?:-cli)?|claude|gemini|opencode|node|npm|npx|python|kimi|cursor|agent|codebuddy)(?:\s+version)?\s+)?v?(\d+\.\d+(?:\.\d+)?(?:[-+][0-9A-Za-z.-]{1,40})?)(?:\s*\([^\n]{0,40}\))?$",
    re.I,
)
_VERSION_COMMANDS = {
    "codex",
    "claude",
    "gemini",
    "opencode",
    "node",
    "npm",
    "npx",
    "python",
    "python3",
    "kimi",
    "agent",
    "codebuddy",
}


class NativeCLISettings:
    def __init__(self, manager: Any, *, user_id: int, locale: str = "en") -> None:
        self.manager = manager
        self.user_id = user_id
        self.locale = locale

    async def _owner(self, agent_id: str) -> Any:
        row = await asyncio.to_thread(owned_expert, self.manager, agent_id, self.user_id)
        if bool(row.is_shared):
            raise NativeCLIError("actor_required", self.locale)
        return row

    async def runners(self) -> list[dict[str, Any]]:
        definitions = await asyncio.to_thread(self.manager.acp_settings.load_runners, self.user_id)
        output = []
        for name, raw in definitions.items():
            command = str(raw.get("command") or "")
            resolved = await asyncio.to_thread(shutil.which, command) if command else None
            output.append(
                {
                    "runner": name,
                    "enabled": bool(raw.get("enabled")),
                    "command": command,
                    "launcher_available": resolved is not None,
                    "uses_package_launcher": Path(command).stem.lower() in {"npx", "npm"},
                    "environment_configured": bool(raw.get("env")),
                }
            )
        return output

    async def inspect_runner(self, runner: str) -> dict[str, Any]:
        definitions = await asyncio.to_thread(self.manager.acp_settings.load_runners, self.user_id)
        raw = definitions.get(runner)
        if not isinstance(raw, dict):
            raise NativeCLIError("invalid_input", self.locale)
        command = str(raw.get("command") or "")
        resolved = await asyncio.to_thread(shutil.which, command)
        if not resolved:
            raise NativeCLIError("runner_missing", self.locale)
        name = Path(resolved).stem.lower()
        if name not in _VERSION_COMMANDS:
            return {
                "runner": runner,
                "launcher_available": True,
                "version": None,
                "version_kind": "not_probed",
            }
        # Never run npx package arguments or install anything during inspection.
        executable, arguments = await asyncio.to_thread(
            resolve_native_launch, command, ["--version"]
        )
        process = await asyncio.create_subprocess_exec(
            executable,
            *arguments,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            stdin=asyncio.subprocess.DEVNULL,
        )
        try:
            assert process.stdout is not None
            stdout = await asyncio.wait_for(process.stdout.read(201), timeout=5)
            await asyncio.wait_for(process.wait(), timeout=1)
            line = stdout.decode("utf-8", errors="replace").strip()
            match = _VERSION.fullmatch(line) if len(line) <= 200 else None
            return {
                "runner": runner,
                "launcher_available": True,
                "version": match[1] if match else None,
                "version_kind": "launcher"
                if name in {"node", "npx", "npm", "python", "python3"}
                else "cli",
            }
        except (TimeoutError, OSError):
            raise NativeCLIError("cli_failed", self.locale) from None
        finally:
            if process.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
                await process.wait()

    async def view(self, agent_id: str) -> dict[str, Any]:
        await self._owner(agent_id)
        config = await asyncio.to_thread(self.manager.get_config, agent_id)
        spec = NativeSpec.from_config(config)
        user = await asyncio.to_thread(self.manager._repos.user_repo.get, self.user_id)
        cached = (
            await asyncio.to_thread(
                self.manager._repos.settings_repo.get,
                self.manager.native_cli.capability_key(self.user_id, agent_id, spec.runner),
            )
            if spec.runner
            else None
        )
        return {
            **spec.to_dict(),
            "capabilities": json.loads(cached) if cached else None,
            "can_manage": bool(user and not user.disabled and user.role == "admin"),
            "runners": await self.runners(),
            "sessions": await self.sessions(agent_id),
        }

    async def save(self, agent_id: str, spec: NativeSpec) -> dict[str, Any]:
        await self._owner(agent_id)
        if not self.manager.try_begin_runtime_update(agent_id):
            raise NativeCLIError("busy", self.locale)
        try:
            return await self._save_reserved(agent_id, spec)
        finally:
            self.manager.end_runtime_update(agent_id)

    async def _save_reserved(self, agent_id: str, spec: NativeSpec) -> dict[str, Any]:
        await self._owner(agent_id)
        user = await asyncio.to_thread(self.manager._repos.user_repo.get, self.user_id)
        if user is None or user.disabled or user.role != "admin":
            raise NativeCLIError("admin_required", self.locale)
        if await _busy(self.manager, agent_id, self.user_id):
            raise NativeCLIError("busy", self.locale)
        if spec.enabled:
            definitions = await asyncio.to_thread(
                self.manager.acp_settings.load_runners, self.user_id
            )
            runner = definitions.get(spec.runner)
            if (
                not isinstance(runner, dict)
                or not runner.get("enabled")
                or not runner.get("command")
            ):
                raise NativeCLIError("runner_disabled", self.locale)
        await self.manager.native_cli.close_agent(agent_id)
        config = await asyncio.to_thread(self.manager.get_config, agent_id)
        if spec.enabled or spec.runner:
            config["native_cli"] = spec.to_dict()
        else:
            config.pop("native_cli", None)
        await self.manager.update_config_json(
            agent_id, json.dumps(config, ensure_ascii=False), schedule_reload=False
        )
        await self.manager.reload(agent_id)
        return await self.view(agent_id)

    async def probe(self, agent_id: str, runner_name: str) -> dict[str, Any]:
        await self._owner(agent_id)
        user = await asyncio.to_thread(self.manager._repos.user_repo.get, self.user_id)
        if user is None or user.disabled or user.role != "admin":
            raise NativeCLIError("admin_required", self.locale)
        if not self.manager.try_begin_runtime_update(agent_id):
            raise NativeCLIError("busy", self.locale)
        try:
            if await _busy(self.manager, agent_id, self.user_id):
                raise NativeCLIError("busy", self.locale)
            definitions = await asyncio.to_thread(
                self.manager.acp_settings.load_runners, self.user_id
            )
            raw = definitions.get(runner_name)
            if not isinstance(raw, dict) or not raw.get("enabled"):
                raise NativeCLIError("runner_disabled", self.locale)
            cwd = await asyncio.to_thread(
                self.manager.resolve_workspace_dir, agent_id, persist_if_missing=False
            )
            if not await asyncio.to_thread(cwd.is_dir):
                raise NativeCLIError("cwd_unavailable", self.locale)
            context = NativeContext(
                self.user_id,
                agent_id,
                "capability-probe",
                str(cwd),
                NativeSpec(True, runner_name),
                ACPRunnerConfig.from_dict(raw),
                self.locale,
            )
            return cast(dict[str, Any], await self.manager.native_cli.probe(context))
        finally:
            self.manager.end_runtime_update(agent_id)

    async def _threads(self, agent_id: str) -> list[Any]:
        pairs = await asyncio.to_thread(self.manager._repos.thread_repo.list_for_user, self.user_id)

        def owned() -> list[Any]:
            values = []
            for aid, tid in pairs:
                if aid == agent_id or self.manager.principal_agent_id(aid) == agent_id:
                    row = self.manager._repos.thread_repo.get(tid)
                    if row is not None and row.user_id == self.user_id:
                        values.append(row)
            return values

        return await asyncio.to_thread(owned)

    async def sessions(self, agent_id: str) -> list[dict[str, Any]]:
        import hashlib

        output = []
        for thread in await self._threads(agent_id):
            key = hashlib.sha256(
                f"{self.user_id}:{agent_id}:{thread.thread_id}".encode()
            ).hexdigest()
            raw = await asyncio.to_thread(
                self.manager._repos.settings_repo.get, "native_cli.session." + key
            )
            if not raw:
                continue
            record = json.loads(raw)
            state = str(record.get("state") or "idle")
            if state in {"working", "waiting"} and key not in self.manager.native_cli.sessions:
                state = "interrupted"
            output.append(
                {
                    "thread_id": thread.thread_id,
                    "title": thread.title or thread.thread_id,
                    "cwd": record.get("cwd"),
                    "runner": record.get("runner"),
                    "state": state,
                }
            )
        return output

    async def close_session(self, agent_id: str, thread_id: str) -> None:
        await self._owner(agent_id)
        threads = await self._threads(agent_id)
        if not any(thread.thread_id == thread_id for thread in threads):
            raise NativeCLIError("thread_not_owned", self.locale)
        if await _busy(self.manager, agent_id, self.user_id):
            raise NativeCLIError("busy", self.locale)
        await self.manager.native_cli.close_thread(
            user_id=self.user_id, agent_id=agent_id, thread_id=thread_id
        )
