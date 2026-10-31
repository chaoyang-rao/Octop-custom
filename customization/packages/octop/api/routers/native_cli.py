"""Native CLI execution settings; configuration does not run a model prompt."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field

from octop.api.deps import current_user, get_server, require_admin, require_permission
from octop.infra.agents.native_cli.config import NativeCLIError, NativeSpec
from octop.infra.agents.native_cli.settings import NativeCLISettings
from octop.infra.utils.locale import resolve_request_locale


class _NativeRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handle(request: Request) -> Response:
            try:
                return await original(request)
            except NativeCLIError as exc:
                return JSONResponse(
                    status_code=409 if exc.code in {"busy", "cwd_changed", "interrupted"} else 400,
                    content={
                        "message": str(NativeCLIError(exc.code, resolve_request_locale(request))),
                        "reason": exc.code,
                    },
                )

        return handle


router = APIRouter(route_class=_NativeRoute, dependencies=[Depends(require_permission("experts"))])
model_router = APIRouter(route_class=_NativeRoute)


class NativeConfigBody(BaseModel):
    enabled: bool = False
    runner: str = Field(default="", max_length=100)
    model_id: str = Field(
        default="",
        max_length=200,
        description="Optional model config-option value advertised by the CLI. Empty uses the CLI default.",
    )
    mode_id: str = Field(
        default="",
        max_length=100,
        description="Optional exact permission-mode ID advertised by the CLI. Unsupported IDs fail rather than lowering restrictions.",
    )


class RunnerView(BaseModel):
    runner: str
    enabled: bool
    command: str
    launcher_available: bool
    uses_package_launcher: bool
    environment_configured: bool


class SessionView(BaseModel):
    thread_id: str
    title: str
    cwd: str | None = None
    runner: str | None = None
    state: str


class NativeChoice(BaseModel):
    value: str
    name: str


class NativeModelsView(BaseModel):
    runner: str
    effective_model_id: str
    configured_model_id: str
    models: list[NativeChoice]
    has_capabilities: bool


@model_router.get(
    "/agents/{agent_id}/native-cli/models",
    summary="Read this conversation's authorized native CLI model choices",
    response_model=NativeModelsView,
)
async def get_native_model_choices(
    agent_id: str,
    request: Request,
    thread_id: str | None = None,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    from octop.infra.agents.native_cli.model_selection import model_choices

    return await model_choices(
        server.app_runtime.agent_registry,
        agent_id=agent_id,
        user_id=user.id,
        thread_id=thread_id,
        locale=resolve_request_locale(request),
    )


class NativeOption(BaseModel):
    id: str
    name: str
    category: str
    type: str
    current_value: str | bool
    options: list[NativeChoice]


class NativeCapabilitiesView(BaseModel):
    image: bool
    audio: bool
    embedded_context: bool
    models: list[NativeChoice]
    modes: list[NativeChoice]
    config_options: list[NativeOption]
    current_mode: str
    read_at: int
    runner: str
    origin_cwd: str


class NativeProbeBody(BaseModel):
    runner: str = Field(min_length=1, max_length=100)


class NativeConfigView(NativeConfigBody):
    can_manage: bool
    capabilities: NativeCapabilitiesView | None = None
    runners: list[RunnerView]
    sessions: list[SessionView]


class RunnerInspection(BaseModel):
    runner: str
    launcher_available: bool
    version: str | None = None
    version_kind: str


def _settings(request: Request, user: Any, server: Any) -> NativeCLISettings:
    return NativeCLISettings(
        server.app_runtime.agent_registry, user_id=user.id, locale=resolve_request_locale(request)
    )


@router.get(
    "/agents/{agent_id}/native-cli",
    summary="Inspect my expert's execution engine and native sessions",
    response_model=NativeConfigView,
)
async def get_native_config(
    agent_id: str,
    request: Request,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    return await _settings(request, user, server).view(agent_id)


@router.put(
    "/agents/{agent_id}/native-cli",
    summary="Choose API or native CLI execution for my expert",
    description="Refuses changes while the expert or its team alias has work or approval pending. Preserves other expert settings, model presets, workspace and conversation history. Does not start a paid CLI prompt or change global CLI login/configuration.",
    response_model=NativeConfigView,
)
async def save_native_config(
    agent_id: str,
    body: NativeConfigBody,
    request: Request,
    user: Any = Depends(require_admin()),
    server: Any = Depends(get_server),
) -> Any:
    spec = NativeSpec.from_config({"native_cli": body.model_dump()})
    return await _settings(request, user, server).save(agent_id, spec)


@router.post(
    "/native-cli/runners/{runner}/inspect",
    summary="Inspect an installed CLI launcher without installing packages",
    response_model=RunnerInspection,
)
async def inspect_runner(
    runner: str,
    request: Request,
    user: Any = Depends(require_admin()),
    server: Any = Depends(get_server),
) -> Any:
    return await _settings(request, user, server).inspect_runner(runner)


@router.delete(
    "/agents/{agent_id}/native-cli/sessions/{thread_id}",
    summary="Explicitly close one native session and forget its resume mapping",
    response_model=dict[str, bool],
)
async def close_native_session(
    agent_id: str,
    thread_id: str,
    request: Request,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    await _settings(request, user, server).close_session(agent_id, thread_id)
    return {"ok": True}


class ManagedInstallBody(BaseModel):
    version: str = Field(min_length=1, max_length=40)


class ManagedStateView(BaseModel):
    phase: str = "idle"
    version: str | None = None
    error_code: str | None = None


class ManagedArtifactView(BaseModel):
    version: str
    url: str
    sha256: str
    integrity: str | None = None
    size: int
    license_url: str
    license_sha256: str
    release_url: str


class ManagedPackageView(BaseModel):
    package: str
    label: str
    license: str
    repository: str
    runner: str
    versions: list[str]
    latest_approved: str
    approved: list[ManagedArtifactView]
    supported: bool
    platform: str
    installed: list[str]
    active_version: str | None = None
    previous_version: str | None = None
    state: ManagedStateView


class ManagedActivationView(BaseModel):
    version: str
    runner: str


@router.get(
    "/native-cli/managed",
    summary="Inspect pinned managed CLI packages and installation state",
    response_model=list[ManagedPackageView],
)
async def list_managed_cli(
    user: Any = Depends(require_admin()), server: Any = Depends(get_server)
) -> Any:
    from octop.infra.agents.native_cli.managed import managed_for

    service = await managed_for(server.app_runtime.agent_registry)
    return await service.status(user.id)


@router.post(
    "/native-cli/managed/{package}/install",
    summary="Install a reviewed CLI version in this account's managed directory",
    description="Downloads only fixed official archives and dependency locks, verifies exact sizes, SHA256 or npm SHA512 SRI and license hashes, and stages a version beneath OCTOP_HOME. Never starts a vendor CLI or npm lifecycle script. When required, only a hash-verified private Node runtime runs Octop's fixed bounded Brotli decoder. Does not activate the version, modify global CLI/login files or send a model prompt.",
    response_model=ManagedStateView,
)
async def install_managed_cli(
    package: str,
    body: ManagedInstallBody,
    user: Any = Depends(require_admin()),
    server: Any = Depends(get_server),
) -> Any:
    from octop.infra.agents.native_cli.managed import managed_for

    service = await managed_for(server.app_runtime.agent_registry)
    return await service.install(user.id, package, body.version)


@router.post(
    "/native-cli/managed/{package}/activate",
    summary="Select one installed managed version without replacing global CLIs",
    description="Verifies the installed binary hash, refuses modified/custom runner drift and active expert work, and updates only this account's dedicated managed runner. Other runner definitions and host login state are preserved.",
    response_model=ManagedActivationView,
)
async def activate_managed_cli(
    package: str,
    body: ManagedInstallBody,
    user: Any = Depends(require_admin()),
    server: Any = Depends(get_server),
) -> Any:
    from octop.infra.agents.native_cli.managed import managed_for

    service = await managed_for(server.app_runtime.agent_registry)
    return await service.activate(user.id, package, body.version)


@router.post(
    "/native-cli/managed/{package}/rollback",
    summary="Return the managed runner to its previously selected executable",
    description="Switches only the managed executable pointer after hash and busy checks. It never restores an older user database, workspace, CLI profile or login data.",
    response_model=ManagedActivationView,
)
async def rollback_managed_cli(
    package: str, user: Any = Depends(require_admin()), server: Any = Depends(get_server)
) -> Any:
    from octop.infra.agents.native_cli.managed import managed_for

    service = await managed_for(server.app_runtime.agent_registry)
    return await service.rollback(user.id, package)


@router.post(
    "/agents/{agent_id}/native-cli/probe",
    summary="Read this CLI's advertised models, modes and media capabilities",
    description="Explicit administrator action. Starts and closes an isolated ACP session in the expert's existing working directory, sends no model prompt, exposes no tools and rejects startup permission requests. Refuses while expert work or approval is pending. Caches only bounded advertised metadata, never login tokens.",
    response_model=NativeCapabilitiesView,
)
async def probe_native_capabilities(
    agent_id: str,
    body: NativeProbeBody,
    request: Request,
    user: Any = Depends(require_admin()),
    server: Any = Depends(get_server),
) -> Any:
    return await _settings(request, user, server).probe(agent_id, body.runner)
