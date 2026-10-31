"""Skill revision and explicit-source import HTTP adapters."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field

from octop.api.deps import get_server, require_permission
from octop.infra.skills.library import library_for
from octop.infra.skills.library_sources import PROVIDER_ROOTS, discover
from octop.infra.users.identity import User

router = APIRouter()


class SkillRevision(BaseModel):
    revision: str
    created_at: int
    source: str
    actor: str


class RevisionHistory(BaseModel):
    current_revision: str
    revisions: list[SkillRevision]


class ChangedFile(BaseModel):
    path: str
    state: Literal["same", "incoming", "local", "conflict"]
    choice: Literal["local", "incoming"] | None = None
    local_size: int | None = None
    incoming_size: int | None = None
    diff: str | None = Field(
        default=None, description="Bounded UTF-8 unified diff. Null for binary or large files."
    )


class RevisionComparison(BaseModel):
    current_revision: str
    incoming_revision: str
    files: list[ChangedFile]


class UpdatePreview(RevisionComparison):
    plan_id: str
    package_id: str
    agent_id: str | None = None
    slug: str
    base_revision: str | None = None
    expires_at: int
    local_changes: bool


class ProviderSelection(BaseModel):
    kind: Literal["workspace", "host"] = "workspace"
    root: str = Field(
        min_length=1,
        max_length=1024,
        description="Explicit provider skill directory. Workspace paths are relative; host paths require an administrator and acknowledgement.",
    )
    source_agent_id: str | None = None
    host_acknowledged: bool = False


class ImportSelection(ProviderSelection):
    package_id: str
    slug: str = Field(min_length=1, max_length=150)


class ProviderSkill(BaseModel):
    slug: str
    name: str
    description: str


class SourcePresets(BaseModel):
    paths: list[str]


class InstallSelection(BaseModel):
    agent_id: str


class RollbackSelection(BaseModel):
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    agent_id: str | None = None


class ConfirmUpdate(BaseModel):
    choices: dict[str, Literal["local", "incoming"]] = Field(
        default_factory=dict,
        description="Every conflicting file must have an explicit choice. No silent incoming overwrite.",
    )
    confirmed: Literal[True] = Field(
        description="True only after the user reviewed and confirmed this preview."
    )


class RevisionReceipt(BaseModel):
    revision: str


class InstallationStatus(BaseModel):
    installed: bool
    baseline_revision: str | None
    current_revision: str
    local_changes: bool
    revisions: list[SkillRevision]


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


@router.get(
    "/provider-presets",
    response_model=SourcePresets,
    summary="List suggested provider directory conventions without scanning the host",
)
async def provider_presets(
    _user: User = Depends(require_permission("skill_packages")),
) -> SourcePresets:
    return SourcePresets(paths=list(PROVIDER_ROOTS))


@router.post(
    "/discover",
    response_model=list[ProviderSkill],
    summary="Discover skills only in a selected provider directory",
    description="Owned agent workspace through BackendWorkspace, or explicit administrator-only host selection. Never scans home directories automatically.",
)
async def discover_provider(
    body: ProviderSelection,
    response: Response,
    user: User = Depends(require_permission("skill_packages")),
    server: Any = Depends(get_server),
) -> list[ProviderSkill]:
    library = library_for(server)
    workspace = (
        (await library.workspace(body.source_agent_id, user))[0]
        if body.kind == "workspace" and body.source_agent_id
        else None
    )
    if body.kind == "workspace" and workspace is None:
        from octop.infra.errors import ErrorCode, OctopError

        raise OctopError(ErrorCode.FORBIDDEN, "owned source agent required")
    no_store(response)
    rows = await discover(
        kind=body.kind,
        root=body.root,
        user=user,
        explicit=body.host_acknowledged,
        workspace=workspace,
    )
    return [ProviderSkill(**row) for row in rows]


@router.post(
    "/imports/preview",
    response_model=UpdatePreview,
    summary="Stage a provider skill and compare with the current library revision",
    description="Reads the selected source, preserves both snapshots, and produces a ten-minute review plan. Does not change the package or execute skill scripts.",
)
async def preview_import(
    body: ImportSelection,
    response: Response,
    user: User = Depends(require_permission("skill_packages")),
    server: Any = Depends(get_server),
) -> UpdatePreview:
    no_store(response)
    return UpdatePreview(
        **await library_for(server).import_plan(
            package_id=body.package_id,
            slug=body.slug,
            kind=body.kind,
            root=body.root,
            user=user,
            explicit=body.host_acknowledged,
            source_agent_id=body.source_agent_id,
        )
    )


@router.get(
    "/packages/{package_id}/skills/{slug}/history",
    response_model=RevisionHistory,
    summary="List immutable skill content revisions",
)
async def history(
    package_id: str,
    slug: str,
    response: Response,
    user: User = Depends(require_permission("skill_packages")),
    server: Any = Depends(get_server),
) -> RevisionHistory:
    no_store(response)
    return RevisionHistory(**await library_for(server).history(package_id, slug, user))


@router.get(
    "/packages/{package_id}/skills/{slug}/revisions/{revision}",
    response_model=RevisionComparison,
    summary="Preview a historical skill revision against current content",
)
async def compare_revision(
    package_id: str,
    slug: str,
    revision: str,
    response: Response,
    user: User = Depends(require_permission("skill_packages")),
    server: Any = Depends(get_server),
) -> RevisionComparison:
    no_store(response)
    return RevisionComparison(
        **await library_for(server).revision_diff(package_id, slug, revision, user)
    )


@router.get(
    "/packages/{package_id}/skills/{slug}/installations/{agent_id}",
    response_model=InstallationStatus,
    summary="Detect installed content and local modifications",
)
async def installation(
    package_id: str,
    slug: str,
    agent_id: str,
    response: Response,
    user: User = Depends(require_permission("skill_packages")),
    server: Any = Depends(get_server),
) -> InstallationStatus:
    no_store(response)
    return InstallationStatus(
        **await library_for(server).installation(package_id, slug, agent_id, user)
    )


@router.post(
    "/packages/{package_id}/skills/{slug}/install-preview",
    response_model=UpdatePreview,
    summary="Compare a package update with an owned agent's installed baseline",
    description="Respects snapshot/lock/deny and mounted package protection; no workspace mutation before confirmation.",
)
async def preview_install(
    package_id: str,
    slug: str,
    body: InstallSelection,
    response: Response,
    user: User = Depends(require_permission("skill_packages")),
    server: Any = Depends(get_server),
) -> UpdatePreview:
    no_store(response)
    return UpdatePreview(
        **await library_for(server).install_plan(package_id, slug, body.agent_id, user)
    )


@router.post(
    "/packages/{package_id}/skills/{slug}/rollback-preview",
    response_model=UpdatePreview,
    summary="Review restoration of a preserved package or workspace revision",
)
async def preview_rollback(
    package_id: str,
    slug: str,
    body: RollbackSelection,
    response: Response,
    user: User = Depends(require_permission("skill_packages")),
    server: Any = Depends(get_server),
) -> UpdatePreview:
    no_store(response)
    return UpdatePreview(
        **await library_for(server).rollback_plan(
            package_id, slug, body.revision, user, body.agent_id
        )
    )


@router.post(
    "/plans/{plan_id}/apply",
    response_model=RevisionReceipt,
    summary="Apply one confirmed, unchanged skill update",
    description="Owner and policy are rechecked. Stale previews, missing conflict choices and repeated application reject; previous full contents remain recoverable.",
)
async def apply_plan(
    plan_id: str,
    body: ConfirmUpdate,
    response: Response,
    user: User = Depends(require_permission("skill_packages")),
    server: Any = Depends(get_server),
) -> RevisionReceipt:
    no_store(response)
    result = await library_for(server).apply(plan_id, body.choices, user)
    return RevisionReceipt(revision=result["revision"])
