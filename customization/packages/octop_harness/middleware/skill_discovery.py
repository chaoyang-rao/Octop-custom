"""Load skill metadata on demand after the host's skill and permission filters."""

from __future__ import annotations

import json
import re
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from threading import RLock
from typing import Annotated, Any, NotRequired, cast

from deepagents.backends.protocol import BackendProtocol
from deepagents.middleware._utils import append_to_system_message
from deepagents.middleware.skills import SkillMetadata, SkillsMiddleware, SkillsState
from langchain.agents.middleware import ModelRequest
from langchain.agents.middleware.types import OmitFromInput, OmitFromOutput
from langchain.tools import ToolRuntime
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.config import get_config
from langgraph.types import Command
from pydantic import BaseModel, Field

from octop_harness.middleware.runtime import runtime_config
from octop_harness.middleware.skill_filter import slash_skill_slug
from octop_harness.skills.catalog import skill_identity_keys

_EAGER_CATALOG_LIMIT = 8
_MAX_CATALOGS = 128
_SEARCH_TOOL = "search_skills"
_WORD_RE = re.compile(r"[a-z0-9]+|[\u3400-\u9fff]+")


def _merge_names(left: list[str] | None, right: list[str] | None) -> list[str]:
    return sorted(set(left or ()) | set(right or ()))


class SkillDiscoveryState(SkillsState):
    discovered_skill_names: NotRequired[Annotated[list[str], OmitFromInput, OmitFromOutput, _merge_names]]


class SkillSearchInput(BaseModel):
    query: str = Field(description="Skill name or capability keywords in English or Chinese; '*' lists a page.")
    max_results: int = Field(default=5, ge=1, le=5)
    offset: int = Field(default=0, ge=0)


def _key(configurable: Mapping[str, Any]) -> tuple[str, str] | None:
    thread = configurable.get("thread_id")
    actor = configurable.get("octop_execution_user_id", configurable.get("user", configurable.get("user_id", "")))
    return (str(thread), str(actor)) if thread else None


def _words(text: str) -> set[str]:
    result: set[str] = set()
    for word in _WORD_RE.findall(text.casefold().replace("_", " ")):
        if "\u3400" <= word[0] <= "\u9fff":
            result.update(word)
            result.update(word[i : i + 2] for i in range(len(word) - 1))
        else:
            result.add(word)
    return result


class SkillDiscoveryMiddleware(SkillsMiddleware[Any, Any]):
    """Replace the standard skills renderer with scoped, searchable metadata.

    Full metadata stays in checkpoint state. Only current, filtered metadata is
    searchable. Search results are remembered by skill name; subsequent model
    steps resolve those names against the current catalog again. Small catalogs,
    explicit /skill invocations and runtimes without discovery retain direct use.
    """

    state_schema = SkillDiscoveryState
    skills_discovery_renderer = True

    @property
    def name(self) -> str:
        return "SkillsMiddleware"

    def __init__(self, *, backend: BackendProtocol, sources: Sequence[str], language: str = "en") -> None:
        super().__init__(backend=backend, sources=sources)
        self._language = language
        self._catalogs: OrderedDict[tuple[str, str], list[SkillMetadata]] = OrderedDict()
        self._lock = RLock()
        self.tools = [
            StructuredTool.from_function(
                self._search,
                name=_SEARCH_TOOL,
                description=(
                    "Find available skills by name or capability keywords (English or Chinese). "
                    "Returns descriptions and SKILL.md paths; read the selected file before following it. "
                    "Use query='*' and offset to list pages. Search does not execute skills or grant tools."
                ),
                args_schema=SkillSearchInput,
                infer_schema=False,
            )
        ]

    def modify_request(self, request: ModelRequest[Any]) -> ModelRequest[Any]:
        configurable = runtime_config(request).get("configurable") or {}
        key = _key(configurable)
        raw_metadata = request.state.get("skills_metadata")
        metadata = cast(list[SkillMetadata], list(raw_metadata)) if isinstance(raw_metadata, list) else []
        if configurable.get("conversation_mode") in {"ask", "plan"}:
            metadata = []
        if key is not None:
            with self._lock:
                self._catalogs[key] = metadata
                self._catalogs.move_to_end(key)
                while len(self._catalogs) > _MAX_CATALOGS:
                    self._catalogs.popitem(last=False)
        if not metadata:
            tools = [tool for tool in request.tools if getattr(tool, "name", "") != _SEARCH_TOOL]
            return request.override(tools=tools)
        can_search = key is not None and any(getattr(tool, "name", "") == _SEARCH_TOOL for tool in request.tools)
        if len(metadata) <= _EAGER_CATALOG_LIMIT or not can_search:
            return super().modify_request(request)
        raw_names = request.state.get("discovered_skill_names")
        names = set(cast(list[str], raw_names)) if isinstance(raw_names, list) else set()
        user = next((message for message in reversed(request.messages) if isinstance(message, HumanMessage)), None)
        explicit = slash_skill_slug(user.text) if user is not None else None
        if explicit:
            names.add(explicit)
        selected = [skill for skill in metadata if skill_identity_keys(skill) & names]
        if self._language == "zh":
            guide = (
                f"当前有 {len(metadata)} 个可用技能, 完整目录按需加载。普通问答无需先搜索技能。"
                "编码、界面、文档、表格、数据处理等专项任务, 或用户点名技能时, "
                "动手前先用 search_skills 按名称或中英文关键词查找, 未命中时换用同义词或英文关键词, "
                "再 read_file 读取返回的 SKILL.md 并按其执行。搜索不会执行技能或授予额外权限。"
                "查询 '*' 可分页浏览目录。不要编造未返回的技能或路径。"
            )
        else:
            guide = (
                f"{len(metadata)} skills are available through on-demand discovery. "
                "Ordinary questions need no skill search. "
                "Before coding, UI, document, spreadsheet, data-processing or other specialized work, "
                "or for a named skill, use search_skills with its name or capability "
                "keywords, then read the returned SKILL.md before following it. Search grants no permissions and "
                "executes nothing. Query '*' lists pages. Do not invent unreturned skills or paths."
            )
        section = "## Skills System\n\n" + guide
        section += "\n\n" + self._format_skills_locations()
        if selected:
            section += "\n\n" + self._format_skills_list(selected)
        raw_errors = request.state.get("skills_load_errors")
        errors = cast(list[str], raw_errors) if isinstance(raw_errors, list) else []
        section += self._format_skills_load_warnings(errors)
        return request.override(system_message=append_to_system_message(request.system_message, section))

    def _search(
        self, query: str, max_results: int, offset: int, runtime: ToolRuntime[Any, SkillDiscoveryState]
    ) -> Command[Any]:
        configurable = runtime.config.get("configurable") or {}
        try:
            current = get_config().get("configurable") or {}
        except RuntimeError:
            current = {}
        key = _key(configurable)
        with self._lock:
            catalog = list(self._catalogs.get(key, [])) if key is not None else []
        if configurable.get("conversation_mode") in {"ask", "plan"} or current.get("conversation_mode") in {
            "ask",
            "plan",
        }:
            catalog = []
        terms = _words(query)

        def score(skill: SkillMetadata) -> int:
            return 20 * len(terms & _words(skill["name"])) + len(terms & _words(skill["description"]))

        ranked = sorted(catalog, key=lambda skill: (-score(skill), skill["name"]))
        if query.strip() != "*":
            ranked = [skill for skill in ranked if score(skill) > 0]
        found = ranked[offset : offset + max_results]
        payload = {
            "matches": [
                {"name": skill["name"], "description": skill["description"], "path": skill["path"]} for skill in found
            ],
            "total": len(ranked),
            "next_offset": offset + len(found) if offset + len(found) < len(ranked) else None,
            "instruction": (
                "Read the selected SKILL.md before using it. No match: try another keyword or list pages with '*'."
            ),
        }
        return Command(
            update={
                "discovered_skill_names": [skill["name"] for skill in found],
                "messages": [
                    ToolMessage(
                        content=json.dumps(payload, ensure_ascii=False), tool_call_id=runtime.tool_call_id or ""
                    )
                ],
            }
        )


def _order_skill_discovery(middleware: Sequence[Any]) -> list[Any]:
    """Legacy deepagents adapters render only after skill/mode/tool filters."""
    renderers = [mw for mw in middleware if getattr(mw, "skills_discovery_renderer", False) is True]
    if not renderers:
        return list(middleware)
    rest = [mw for mw in middleware if mw not in renderers]
    tail = next(
        (
            i
            for i, mw in enumerate(rest)
            if getattr(mw, "final_context_budget_guard", False) is True
            or mw.__class__.__name__ == "ContextUsageMiddleware"
            or getattr(mw, "name", "") == "ModelRefusalMiddleware"
        ),
        len(rest),
    )
    return [*rest[:tail], *renderers, *rest[tail:]]


__all__ = ["SkillDiscoveryMiddleware", "SkillDiscoveryState"]
