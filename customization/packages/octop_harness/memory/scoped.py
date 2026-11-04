"""Host-authorized memory namespaces, using octop-memory's existing pipeline.

Checkpoint storage stays per agent. A bound view is immutable for one request,
including background capture; no shared mutable 'current project' is used.
"""

from __future__ import annotations

import json
import threading
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from octop_memory import Memory, MemoryService

from octop_harness.memory.store import memory_identity, shared_memory_store


class ScopedMemoryService:
    def __init__(
        self,
        root: Any,
        *,
        config: Any,
        workspace_path: Path,
        llm: Any,
        service_config: dict[str, Any],
    ) -> None:
        self._root = root
        self._config = config
        self._workspace_path = workspace_path
        self._llm = llm
        self._service_config = service_config
        self._lock = threading.RLock()
        self._services: dict[str, Any] = {}
        self._leases: list[Any] = []
        self._sessions: dict[str, dict[str, Any]] = {}
        self._turns: dict[str, dict[str, Any]] = {}

    @property
    def memory(self) -> Any:
        # Existing checkpoint maintenance must still address the legacy store.
        return self._root.memory

    def for_context(self, cfg: dict[str, Any], message: Any = None) -> BoundMemoryService:
        context = self._config.memory_scope_resolver(dict(cfg))
        key = str(cfg.get("thread_id") or "")
        if message is not None:
            content = message.content
            if isinstance(content, list):
                content = "\n".join(
                    str(item.get("text", "")) for item in content if isinstance(item, dict)
                )
            if cfg.get("octop_team_assignment") or cfg.get("task_id"):
                content = ""
            with self._lock:
                self._turns[key] = {"message_id": message.id, "user_text": str(content)}
                # Bounded to recently used threads; no message bodies on disk here.
                while len(self._turns) > 256:
                    self._turns.pop(next(iter(self._turns)))
        with self._lock:
            turn = dict(self._turns.get(key, {}))
        return BoundMemoryService(self, context, dict(cfg), turn)

    def open(self, name: str, context: dict[str, Any]) -> Any:
        if name == "legacy":
            if not context.get("legacy_readable"):
                raise PermissionError("unclassified memory is private to its owner")
            return self._root
        spec = context["scopes"].get(name)
        if spec is None:
            raise ValueError("scope unavailable in this conversation")
        identity = json.dumps(spec, sort_keys=True)
        with self._lock:
            if identity in self._services:
                return self._services[identity]
            cfg = replace(
                self._config, memory_namespace=spec["namespace"], memory_backend=spec["backend"]
            )
            key = memory_identity(cfg, self._workspace_path)
            assert key is not None
            backend = dict(spec["backend"])
            kind = backend.pop("type")
            if kind == "sqlite":
                Path(backend["db_path"]).parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            memory = shared_memory_store().acquire(
                key,
                lambda: Memory(namespace=spec["namespace"], backend=kind, backend_config=backend),
            )
            self._leases.append(key)
            service = MemoryService(
                memory,
                llm=self._llm,
                config=self._service_config,
                host=f"octop:{context['source']['agent_id']}",
            )
            self._services[identity] = service
            return service

    @staticmethod
    def exists(name: str, context: dict[str, Any]) -> bool:
        if name == "legacy":
            return True
        spec = context["scopes"].get(name)
        if spec is None:
            raise ValueError("scope unavailable in this conversation")
        backend = spec["backend"]
        return backend["type"] != "sqlite" or Path(backend["db_path"]).is_file()

    def extract(self, session_id: str, **kwargs: Any) -> dict[str, Any]:
        # Capture registered the exact services before crossing a worker boundary.
        # A project reassignment may leave two namespaces to finish independently.
        with self._lock:
            services = list(self._sessions.get(session_id, {}).values())
        results = [service.extract(session_id, **kwargs) for service in services]
        failures = [
            r.get("failure_reason")
            for r in results
            if isinstance(r, dict) and r.get("failure_reason")
        ]
        return {"scopes": results, **({"failure_reason": failures[0]} if failures else {})}

    def set_manual_review_scheduler(self, scheduler: Any) -> None:
        setter = getattr(self._root, "set_manual_review_scheduler", None)
        if setter is not None:
            setter(scheduler)

    def review_new_memory(self) -> Any:
        review = getattr(self._root, "review_new_memory", None)
        return review() if review is not None else None

    def maintenance_memories(self) -> list[Any]:
        with self._lock:
            return [self._root.memory, *(service.memory for service in self._services.values())]

    def close(self) -> None:
        with self._lock:
            for key in self._leases:
                shared_memory_store().release(key)
            self._leases.clear()
            self._services.clear()
            self._sessions.clear()
            self._turns.clear()


class BoundMemoryService:
    def __init__(
        self,
        owner: ScopedMemoryService,
        context: dict[str, Any],
        cfg: dict[str, Any],
        turn: dict[str, Any],
    ) -> None:
        self.owner = owner
        self.context = context
        self.cfg = cfg
        self.turn = turn
        self.scope_id = context["scope_id"]

    @property
    def source(self) -> dict[str, Any]:
        return {**self.context["source"], "message_id": self.turn.get("message_id")}

    def recall(self, query: str, **kwargs: Any) -> Any:
        parts = []
        remaining = 6000
        for name in self.context["recall_scopes"]:
            if not self.owner.exists(name, self.context):
                continue
            service = self.owner.open(name, self.context)
            result = service.recall(query, **kwargs)
            text = getattr(result, "rendered", "") or ""
            if text and remaining > 0:
                allowance = (
                    remaining
                    if name == self.context["default_scope"]
                    else min(remaining, 1000 if name == "session" else 1500)
                )
                section = f"[{name}]\n{text}"
                if len(section) > allowance:
                    section = section[:allowance].rsplit("\n", 1)[0]
                parts.append(section)
                remaining -= len(section) + 2
        return SimpleNamespace(rendered="\n\n".join(parts))

    def capture_turn(self, **kwargs: Any) -> Any:
        name = self.context["default_scope"]
        service = self.owner.open(name, self.context)
        session_id = str(kwargs.get("session_id") or kwargs.get("thread_id") or "")
        with self.owner._lock:
            self.owner._sessions.setdefault(session_id, {})[self.scope_id] = service
        # A member's peer thread is execution state; the visible room is the
        # source users can actually open. The session still isolates extraction.
        kwargs["thread_id"] = self.source["thread_id"]
        # Expert output remains in the conversation archive; it is not by
        # itself evidence of a user-confirmed long-term fact.
        kwargs["assistant"] = None
        if self.cfg.get("octop_team_assignment") or self.cfg.get("task_id"):
            kwargs["user"] = None
        return service.capture_turn(**kwargs)

    def search(self, query: str, *, scope: str = "auto", max_results: int = 5) -> dict[str, Any]:
        scopes = self.context["recall_scopes"] if scope == "auto" else [scope]
        hits = []
        for name in scopes:
            if not self.owner.exists(name, self.context):
                continue
            service = self.owner.open(name, self.context)
            result = service.search(query, max_results=min(20, max(1, max_results)))
            for hit in result.get("hits", []):
                hits.append({**hit, "scope": name, "path": f"{name}/{hit['path']}"})
        return {"hits": hits[: min(20, max(1, max_results))]}

    def get(self, path: str, **kwargs: Any) -> Any:
        name, separator, local = path.partition("/")
        if not separator or name not in {*self.context["scopes"], "legacy"}:
            raise ValueError("use a scoped path returned by memory_search")
        return self.owner.open(name, self.context).get(local, **kwargs)

    def save(
        self,
        content: str,
        *,
        scope: str = "auto",
        topic: str | None = None,
        evidence: str = "",
        replaces: str | None = None,
        user_action: bool = False,
    ) -> dict[str, Any]:
        name = self.context["default_scope"] if scope == "auto" else scope
        if name == "legacy":
            raise ValueError("legacy memory is read-only through scoped tools")
        if not content.strip() or len(content) > 4000:
            raise ValueError("memory must contain 1 to 4000 characters")
        if not user_action and (
            not evidence.strip()
            or evidence not in self.turn.get("user_text", "")
            or content.strip().casefold() not in evidence.casefold()
        ):
            raise ValueError(
                "quote evidence from the current user's message and save an exact excerpt; unconfirmed assistant conclusions must not be saved"
            )
        service = self.owner.open(name, self.context)
        source = {
            **self.source,
            "saved_at": datetime.now(UTC).isoformat(),
            "origin": "user" if user_action else "agent_tool",
            "quote": evidence,
        }
        if user_action:
            source["message_id"] = None
        if replaces:
            atom = service.memory.replace_atom(
                replaces,
                assertion=content.strip(),
                actor="user" if user_action else "auto",
                note=json.dumps({"source": source}, ensure_ascii=False),
            )
            if atom is None:
                raise ValueError("memory was removed or replaced; reload before editing")
            return {"scope": name, "atom_id": atom.id, "replaces": replaces, "source": source}
        node = service.save(content.strip(), topic=topic, metadata={"source": source})
        return {"scope": name, "atom_id": node.atom_id, "source": source}


def build_scoped_memory_tools(service: ScopedMemoryService) -> list[Any]:
    from langchain_core.tools import tool
    from langgraph.config import get_config

    def bound() -> BoundMemoryService:
        return service.for_context(dict(get_config().get("configurable") or {}))

    @tool
    def memory_search(query: str, max_results: int = 5, scope: str = "auto") -> str:
        """Find earlier memories. auto searches this session, user preferences and the CURRENT project (or expert when unbound).
        Other scopes: user, project, expert, session. legacy explicitly searches this expert's old unclassified store; never use it as proof of the current project's decisions. Results carry scoped paths for memory_get. Never merge unrelated project facts.
        """
        try:
            return json.dumps(
                bound().search(query, scope=scope, max_results=max_results), ensure_ascii=False
            )
        except (PermissionError, ValueError):
            return json.dumps({"error": "memory scope unavailable"})

    @tool
    def memory_get(path: str, start: int | None = None, lines: int | None = None) -> str:
        """Read a scoped path returned by memory_search; inspect sources before asserting a past decision."""
        try:
            return json.dumps(
                bound().get(path, start=start, lines=lines), ensure_ascii=False, default=str
            )
        except (PermissionError, ValueError):
            return json.dumps({"error": "memory scope unavailable"})

    @tool
    def memory_save(
        content: str,
        evidence: str,
        scope: str = "auto",
        topic: str | None = None,
        replaces: str | None = None,
    ) -> str:
        """Save a concise user-stated fact or explicit correction. evidence MUST be an exact quote from the CURRENT user's message; content must be an exact excerpt of that evidence, not your paraphrase.
        scope: project for shared project decisions/results, user ONLY for explicitly general personal preferences, expert for general professional methods, session for temporary information. auto uses the current project, otherwise expert. Never store your guesses or tool output as confirmed facts. To correct a memory, search/read it first and pass its atom id as replaces IN THE SAME scope; the old version remains in revision history. Only claim success after this tool succeeds.
        """
        try:
            return json.dumps(
                bound().save(
                    content, scope=scope, topic=topic, evidence=evidence, replaces=replaces
                ),
                ensure_ascii=False,
            )
        except (PermissionError, ValueError) as exc:
            return json.dumps({"error": str(exc)}, ensure_ascii=False)

    return [memory_search, memory_get, memory_save]
