"""Durable task queue and workflow HTTP adapters."""

from __future__ import annotations

from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from octop.api.deps import current_user, get_server, require_permission
from octop.infra.tasks.manager import TaskManager
from octop.infra.tasks.models import TaskCreate, TaskOptions, TaskState, WorkflowDefinition

router = APIRouter()
hook_router = APIRouter()


def _manager(server: Any) -> TaskManager:
    return cast(TaskManager, server.task_manager)


class TaskView(BaseModel):
    id: str
    task_id: str
    user_id: int
    agent_id: str
    thread_id: str | None = None
    title: str
    state: TaskState
    run_id: str | None = None
    step_key: str | None = None
    dependencies: list[str] = Field(default_factory=list)
    archived: bool
    attempt: int
    error_code: str | None = None
    created_at: int
    updated_at: int
    started_at: int | None = None
    finished_at: int | None = None


class TaskEventView(BaseModel):
    action: str
    state: TaskState
    actor_user_id: int | None = None
    created_at: int


class TaskDetail(TaskView):
    prompt: str
    result: str
    options: TaskOptions
    events: list[TaskEventView] = Field(default_factory=list)


class TaskAction(BaseModel):
    action: Literal["pause", "resume", "retry", "cancel", "archive", "restore", "reassign"]
    expected_attempt: int | None = Field(
        default=None,
        ge=0,
        description="Reject stale widget/actions after the task has started a newer attempt.",
    )
    agent_id: str | None = Field(
        default=None,
        description="Owned expert to assign for reassign; creates a separate conversation on its next run.",
    )


class QueueControl(BaseModel):
    paused: bool = Field(
        description="Pause admission after the current task; does not interrupt active tool execution."
    )


class WorkflowWrite(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    definition: WorkflowDefinition
    enabled: bool = True


class WorkflowView(BaseModel):
    id: str
    user_id: int
    name: str
    definition: WorkflowDefinition
    enabled: bool
    webhook_enabled: bool
    next_run_at: int | None = None
    last_run_at: int | None = None
    schedule_paused: bool = False
    created_at: int
    updated_at: int


class WorkflowRunBody(BaseModel):
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="JSON input appended as data to root steps; limited to 32 KiB.",
    )
    idempotency_key: str | None = Field(default=None, max_length=200)


class WorkflowRunResult(BaseModel):
    run_id: str


class WorkflowWebhookWrite(BaseModel):
    enabled: bool


class WorkflowWebhookResult(BaseModel):
    token: str | None = Field(
        description="Returned once on rotation; only a hash is retained. Never place it in the URL."
    )
    path: str


class WorkflowRunView(BaseModel):
    run_id: str
    workflow_id: str | None = None
    name: str
    source: str
    state: str
    created_at: int
    tasks: list[TaskView]


@router.get(
    "/tasks", response_model=list[TaskView], summary="List my durable queued and completed tasks"
)
async def list_tasks(
    archived: bool = Query(False),
    agent_id: str | None = Query(None),
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
    _: Any = Depends(require_permission("tasks")),
) -> list[dict[str, Any]]:
    return await _manager(server).list(user.id, archived=archived, agent_id=agent_id)


@router.post(
    "/tasks", response_model=TaskView, status_code=201, summary="Queue a persistent expert task"
)
async def create_task(
    body: TaskCreate,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
    _: Any = Depends(require_permission("tasks")),
) -> dict[str, Any]:
    return (await _manager(server).enqueue(user.id, body)).to_public(detail=False)


@router.get(
    "/tasks/queue-controls",
    response_model=dict[str, bool],
    summary="Read my per-expert task queue pause controls",
)
async def queue_controls(
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
    _: Any = Depends(require_permission("tasks")),
) -> dict[str, bool]:
    return await _manager(server).controls(user.id)


@router.put(
    "/tasks/queue-controls/{agent_id}",
    response_model=QueueControl,
    summary="Pause or resume subsequent expert tasks",
)
async def set_queue_control(
    agent_id: str,
    body: QueueControl,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
    _: Any = Depends(require_permission("tasks")),
) -> QueueControl:
    await _manager(server).pause_queue(user.id, agent_id, body.paused)
    return body


@router.get(
    "/tasks/{task_id}",
    response_model=TaskDetail,
    summary="Read an owned task, output and state-change history",
)
async def get_task(
    task_id: str,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
    _: Any = Depends(require_permission("tasks")),
) -> dict[str, Any]:
    return await _manager(server).detail(user.id, task_id)


@router.post(
    "/tasks/{task_id}/actions",
    response_model=TaskView,
    summary="Control, reassign or archive an owned task",
)
async def task_action(
    task_id: str,
    body: TaskAction,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
    _: Any = Depends(require_permission("tasks")),
) -> dict[str, Any]:
    return (
        await _manager(server).action(
            user.id,
            task_id,
            body.action,
            agent_id=body.agent_id,
            expected_attempt=body.expected_attempt,
        )
    ).to_public(detail=False)


@router.get(
    "/task-workflows", response_model=list[WorkflowView], summary="List my reusable task workflows"
)
async def list_workflows(
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
    _: Any = Depends(require_permission("tasks")),
) -> list[dict[str, Any]]:
    return await _manager(server).workflows(user.id)


@router.post(
    "/task-workflows",
    response_model=WorkflowView,
    status_code=201,
    summary="Create a validated dependency workflow",
)
async def create_workflow(
    body: WorkflowWrite,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
    _: Any = Depends(require_permission("tasks")),
) -> dict[str, Any]:
    return (
        await _manager(server).create_workflow(
            user.id, **body.model_dump(exclude={"definition"}), definition=body.definition
        )
    ).to_public()


@router.put(
    "/task-workflows/{workflow_id}",
    response_model=WorkflowView,
    summary="Update future workflow runs",
)
async def update_workflow(
    workflow_id: str,
    body: WorkflowWrite,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
    _: Any = Depends(require_permission("tasks")),
) -> dict[str, Any]:
    return (
        await _manager(server).update_workflow(
            user.id,
            workflow_id,
            **body.model_dump(exclude={"definition"}),
            definition=body.definition,
        )
    ).to_public()


@router.post(
    "/task-workflows/{workflow_id}/runs",
    response_model=WorkflowRunResult,
    status_code=202,
    summary="Start a durable workflow run",
    description="Creates every step atomically. Completed dependency outputs are passed as data to each dependent step. Requires ownership of every selected expert.",
)
async def run_workflow(
    workflow_id: str,
    body: WorkflowRunBody,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
    _: Any = Depends(require_permission("tasks")),
) -> WorkflowRunResult:
    return WorkflowRunResult(
        run_id=await _manager(server).run_workflow(user.id, workflow_id, **body.model_dump())
    )


@router.get(
    "/task-runs",
    response_model=list[WorkflowRunView],
    summary="List my workflow runs with individual step states",
)
async def list_runs(
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
    _: Any = Depends(require_permission("tasks")),
) -> list[dict[str, Any]]:
    return await _manager(server).runs(user.id)


@router.put(
    "/task-workflows/{workflow_id}/webhook",
    response_model=WorkflowWebhookResult,
    summary="Rotate or revoke a workflow trigger token",
    description="Returns the new bearer token once. Revocation invalidates all earlier tokens. The server stores a SHA-256 hash, never the token itself.",
)
async def workflow_webhook(
    workflow_id: str,
    body: WorkflowWebhookWrite,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
    _: Any = Depends(require_permission("tasks")),
) -> WorkflowWebhookResult:
    token = await _manager(server).rotate_webhook(user.id, workflow_id, enabled=body.enabled)
    return WorkflowWebhookResult(token=token, path=f"/api/task-hooks/{workflow_id}")


@hook_router.post(
    "/task-hooks/{workflow_id}",
    response_model=WorkflowRunResult,
    status_code=202,
    summary="Trigger a workflow using its scoped bearer token",
    description="Uses the workflow trigger token, not an account JWT. 32 KiB JSON body limit, optional Idempotency-Key, and 30 accepted calls per minute per workflow. No token in URLs or logs.",
)
async def trigger_hook(
    workflow_id: str,
    request: Request,
    authorization: str = Header(""),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key", max_length=200),
    server: Any = Depends(get_server),
) -> WorkflowRunResult:
    # Bound the byte stream before decoding, rather than loading an unbounded JSON body.
    data = bytearray()
    async for part in request.stream():
        data.extend(part)
        if len(data) > 32768:
            raise _manager(server)._error("payload_large", status=413)
    import json

    try:
        payload = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        raise _manager(server)._error("bad_payload") from None
    if not isinstance(payload, dict):
        raise _manager(server)._error("bad_payload")
    token = authorization[7:] if authorization.lower().startswith("bearer ") else ""
    return WorkflowRunResult(
        run_id=await _manager(server).trigger_webhook(
            workflow_id, token, payload, idempotency_key=idempotency_key
        )
    )


class CalendarTokenResult(BaseModel):
    path: str | None = Field(
        description="Read-only iCalendar subscription path; returned once and revocable."
    )


@router.put(
    "/task-workflows/{workflow_id}/schedule",
    response_model=QueueControl,
    summary="Pause or resume a workflow's future schedule",
)
async def pause_workflow_schedule(
    workflow_id: str,
    body: QueueControl,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
    _: Any = Depends(require_permission("tasks")),
) -> QueueControl:
    await _manager(server).set_schedule_paused(user.id, workflow_id, body.paused)
    return body


@router.get(
    "/tasks-calendar",
    response_class=Response,
    summary="Export my next seven days of workflow schedules",
    responses={200: {"content": {"text/calendar": {}}}},
)
async def export_calendar(
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
    _: Any = Depends(require_permission("tasks")),
) -> Response:
    return Response(
        await _manager(server).calendar(user.id),
        media_type="text/calendar",
        headers={
            "Content-Disposition": "attachment; filename=octop-workflows.ics",
            "Cache-Control": "no-store",
        },
    )


@router.put(
    "/tasks-calendar/token",
    response_model=CalendarTokenResult,
    summary="Rotate or revoke my read-only calendar subscription link",
)
async def calendar_token(
    body: WorkflowWebhookWrite,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
    _: Any = Depends(require_permission("tasks")),
) -> CalendarTokenResult:
    token = await _manager(server).rotate_calendar(user.id, enabled=body.enabled)
    return CalendarTokenResult(path=f"/api/task-calendar/{token}.ics" if token else None)


@hook_router.get(
    "/task-calendar/{token}.ics",
    response_class=Response,
    summary="Read a scoped calendar subscription",
    description="Read-only capability link for calendar clients that cannot attach an account JWT. Revocation invalidates the link. No conversation content or execution privileges.",
    responses={200: {"content": {"text/calendar": {}}}},
)
async def subscribed_calendar(token: str, server: Any = Depends(get_server)) -> Response:
    return Response(
        await _manager(server).calendar_for_token(token),
        media_type="text/calendar",
        headers={"Cache-Control": "no-store"},
    )


@router.delete(
    "/task-workflows/{workflow_id}",
    status_code=204,
    summary="Remove an owned workflow definition",
    description="Stops future schedule and webhook triggers. Existing run snapshots, queued tasks and history are retained; cancel those tasks separately.",
)
async def delete_workflow(
    workflow_id: str,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
    _: Any = Depends(require_permission("tasks")),
) -> None:
    await _manager(server).delete_workflow(user.id, workflow_id)
