"""Transport-independent task and workflow input contracts."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from octop.i18n import tr
from octop.infra.utils.locale import DEFAULT_LOCALE

TaskState = Literal[
    "queued", "paused", "running", "waiting", "completed", "failed", "cancelled", "interrupted"
]
TERMINAL_STATES = frozenset({"completed", "failed", "cancelled", "interrupted"})


class TaskAttachment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_path: str = Field(min_length=1, max_length=500)
    filename: str = Field(default="", max_length=300)
    mime_type: str = Field(
        default="application/octet-stream",
        min_length=1,
        max_length=150,
        pattern=r"^[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+$",
    )
    size: int | None = Field(default=None, ge=0, le=25 * 1024 * 1024)
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    upload_receipt: str | None = Field(
        default=None,
        max_length=100,
        description="Owner/agent-bound receipt returned by the upload API. Required for task attachments; existing chat attachments remain compatible.",
    )


class TaskOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str | None = Field(default=None, max_length=200)
    mcp_servers: list[str] | None = Field(default=None, max_length=50)
    skills: list[str] | None = Field(default=None, max_length=100)
    knowledge_base_ids: list[str] | None = Field(default=None, max_length=50)
    conversation_mode: Literal["ask", "plan", "craft"] = "craft"
    quiet: bool = False
    attachments: list[TaskAttachment] = Field(default_factory=list, max_length=10)


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=1, max_length=32000)
    thread_id: str | None = Field(default=None, max_length=100)
    options: TaskOptions = Field(default_factory=TaskOptions)
    attachments: list[TaskAttachment] = Field(default_factory=list, max_length=10)

    @field_validator("title", "prompt")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError(tr("tasks.validation.blank", DEFAULT_LOCALE))
        return value.strip()


class WorkflowStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=200)
    agent_id: str = Field(min_length=1, max_length=100)
    prompt: str = Field(min_length=1, max_length=32000)
    depends_on: list[str] = Field(default_factory=list, max_length=32)
    options: TaskOptions = Field(default_factory=TaskOptions)

    @field_validator("key")
    @classmethod
    def safe_key(cls, value: str) -> str:
        if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]*", value):
            raise ValueError(tr("tasks.validation.step_key", DEFAULT_LOCALE))
        return value

    @field_validator("title", "prompt")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError(tr("tasks.validation.blank", DEFAULT_LOCALE))
        return value.strip()


class WorkflowDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    steps: list[WorkflowStep] = Field(min_length=1, max_length=32)
    schedule: str | None = Field(default=None, max_length=200)
    failure_policy: Literal["pause", "continue"] = "pause"
    quiet: bool = False

    @model_validator(mode="after")
    def acyclic(self) -> WorkflowDefinition:
        by_key = {step.key: step for step in self.steps}
        if len(by_key) != len(self.steps):
            raise ValueError(tr("tasks.validation.duplicate_key", DEFAULT_LOCALE))
        done: set[str] = set()
        while len(done) < len(by_key):
            ready = {
                key
                for key, step in by_key.items()
                if key not in done and set(step.depends_on) <= done
            }
            if not ready:
                raise ValueError(tr("tasks.validation.dependencies", DEFAULT_LOCALE))
            done.update(ready)
        return self

    def ordered_steps(self) -> list[WorkflowStep]:
        pending = list(self.steps)
        done: set[str] = set()
        ordered = []
        while pending:
            for step in list(pending):
                if set(step.depends_on) <= done:
                    ordered.append(step)
                    done.add(step.key)
                    pending.remove(step)
        return ordered
