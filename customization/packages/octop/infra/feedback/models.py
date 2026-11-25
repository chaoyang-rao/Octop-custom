"""Feedback forms and the stable sidebar section catalogue."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from octop.infra.enterprise_resources.models import StrictModel

Status = Literal["new", "in_progress", "resolved"]
Kind = Literal["problem", "suggestion", "other"]

# Section IDs match the sidebar; paths omit account, conversation and file IDs.
SECTIONS = (
    ("general", "feedback.general", "/"),
    ("chat", "nav.chat", "/chat"),
    ("conversations", "nav.conversations", "/conversations"),
    ("experts", "nav.experts", "/experts"),
    ("tasks", "nav.tasks", "/tasks"),
    ("task-queue", "nav.taskQueue", "/task-queue"),
    ("token-usage", "nav.tokenUsage", "/token-usage"),
    ("companion", "nav.companion", "/companion"),
    ("personalization", "nav.personalization", "/personalization"),
    ("channels", "nav.channels", "/personalization/channels"),
    ("connectors", "nav.connectors", "/connectors"),
    ("account-connections", "nav.accountConnections", "/account-connections"),
    ("mobile-access", "nav.mobileAccess", "/mobile-access"),
    ("skill-packages", "nav.skillPackages", "/skill-packages"),
    ("knowledge-bases", "nav.knowledgeBases", "/knowledge-bases"),
    ("bridge", "nav.bridge", "/bridge"),
    ("workbench", "nav.workbench", "/workbench"),
    ("remote-desktop", "nav.remoteDesktop", "/remote-desktop"),
    ("acp", "nav.acp", "/acp"),
    ("admin-users", "nav.adminUsers", "/admin/users"),
    ("models", "nav.models", "/admin/models"),
    ("admin-storage", "nav.adminStorage", "/admin/backend"),
    ("admin-plugins", "nav.adminPlugins", "/admin/plugins"),
    ("admin-security", "nav.security", "/admin/security"),
    ("admin-advanced", "nav.adminAdvanced", "/admin/advanced"),
)
SECTION_KEYS = frozenset(key for key, _, _ in SECTIONS)


class FeedbackCreate(StrictModel):
    submission_key: str = Field(pattern=r"^[a-f0-9]{32}$")
    section: str = Field(max_length=64)
    kind: Kind = "problem"
    title: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=1, max_length=6000)
    client_version: str = Field(default="", pattern=r"^[a-zA-Z0-9.+_-]{0,80}$")
    client_platform: Literal["", "macos", "windows", "linux", "web"] = ""

    @field_validator("section")
    @classmethod
    def section_exists(cls, value: str) -> str:
        if value not in SECTION_KEYS:
            raise ValueError("Unknown feedback section")
        return value

    @field_validator("title", "content")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Feedback text is required")
        return value.strip()


class FeedbackRecord(BaseModel):
    feedback_id: str
    author_name: str
    section: str
    kind: Kind
    title: str
    content: str
    client_version: str
    client_platform: str
    status: Status
    reply: str
    revision: int
    created_at: int
    updated_at: int


class FeedbackList(BaseModel):
    items: list[FeedbackRecord]
    total: int
    limit: int
    offset: int


class FeedbackUpdate(StrictModel):
    expected_revision: int = Field(ge=1)
    status: Status
    reply: str = Field(default="", max_length=4000)


class FeedbackSection(BaseModel):
    key: str
    label_key: str
    path: str


class FeedbackOptions(BaseModel):
    sections: list[FeedbackSection]
    destination: Literal["company", "local"]
    local_admin: bool
