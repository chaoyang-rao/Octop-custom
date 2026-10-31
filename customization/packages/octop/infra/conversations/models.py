"""Validated conversation message locators and portable history records."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class MessageLocator(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message_id: str | None = Field(default=None, max_length=300)
    role: Literal["user", "assistant"] = "assistant"
    content: str | None = Field(default=None, max_length=128000)
    ordinal_from_end: int | None = Field(default=None, ge=1, le=10000)


class QuoteReference(BaseModel):
    source_thread_id: str = Field(min_length=1, max_length=100)
    message: MessageLocator


class QuotedMessage(BaseModel):
    source_thread_id: str
    source_agent_id: str
    message_key: str
    role: Literal["user", "assistant"]
    content: str
    speaker_agent_id: str | None = None
    speaker_name: str | None = None


class PortableMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    content: str = Field(max_length=128000)
    external_id: str | None = Field(default=None, max_length=300)
    created_at: int | None = None


class PortableConversation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    external_id: str = Field(min_length=1, max_length=300)
    title: str = Field(max_length=300)
    messages: list[PortableMessage] = Field(max_length=10000)
    origin: dict[str, Any] = Field(default_factory=dict)


class PortableExpert(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=5000)
    instructions: str = Field(default="", max_length=128000)
    welcome_message: str = Field(default="", max_length=8000)
    kind: Literal["expert", "team"] = "expert"
    members: list[str] = Field(default_factory=list, max_length=100)
    # Archive-relative paths only. Their bytes are bounded and checked separately.
    workspace_files: list[str] = Field(default_factory=list, max_length=5000)
    skills: list[str] = Field(default_factory=list, max_length=100)


class PortableBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal["octop-user-transfer"] = "octop-user-transfer"
    version: Literal[1] = 1
    agents: list[PortableExpert] = Field(max_length=200)
    conversations: dict[str, list[PortableConversation]] = Field(default_factory=dict)
    workflows: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    warnings: list[str] = Field(default_factory=list, max_length=1000)


class ImportSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Exact keys shown by the preview. Import always creates new resources.
    keys: list[str] = Field(min_length=1, max_length=5000)
    target_agent_id: str | None = Field(default=None, max_length=100)
    names: dict[str, str] = Field(default_factory=dict)
    default_model: str | None = Field(default=None, max_length=300)
    include_files: bool = False
    include_skills: bool = True
    include_workflows: bool = False
    skip_duplicates: bool = True


class ExportSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_ids: list[str] = Field(min_length=1, max_length=200)
    include_files: bool = False
    include_skills: bool = True
    include_conversations: bool = False
    include_workflows: bool = False
