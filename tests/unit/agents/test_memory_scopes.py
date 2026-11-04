"""Real temporary memory stores: projects share facts, never account identity."""

from __future__ import annotations

import importlib.util
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from langchain_core.messages import HumanMessage
from octop_harness.config import HarnessAgentConfig
from octop_memory import Memory, MemoryService

from octop.infra.agents.memory.scoped_dashboard import ScopedMemoryDashboard
from octop.infra.agents.memory.scopes import MemoryScopePolicy


def source_module(name):
    path = Path(__file__).resolve().parents[3] / "customization/packages/octop_harness" / name
    spec = importlib.util.spec_from_file_location("scoped_memory_test_" + path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def system(tmp_path, monkeypatch):
    monkeypatch.setenv("OCTOP_HOME", str(tmp_path / "octop-home"))
    actors = {
        name: NS(
            agent_id=name, user_id=1, is_shared=False, kind="team" if name == "team" else "expert"
        )
        for name in ("a", "b", "team")
    }
    actors["other"] = NS(agent_id="other", user_id=2, is_shared=False, kind="expert")
    threads = {
        name: NS(
            thread_id=name,
            agent_id=actor,
            user_id=uid,
            project_path=str(tmp_path / project) if project else None,
            project_name=project,
            title=name,
        )
        for name, actor, uid, project in (
            ("a1", "a", 1, "same"),
            ("b1", "b", 1, "same"),
            ("a2", "a", 1, "different"),
            ("a3", "a", 1, None),
            ("room", "team", 1, "same"),
            ("foreign", "other", 2, "same"),
        )
    }
    users = {uid: NS(id=uid, disabled=False) for uid in (1, 2)}
    members = {"a", "b"}
    repos = NS(
        agent_repo=NS(get=actors.get), thread_repo=NS(get=threads.get), user_repo=NS(get=users.get)
    )
    teams = NS(visible_member_ids=lambda _: members, require_primary=lambda _: actors["a"])
    policy = MemoryScopePolicy(repos, teams, NS(database=NS(is_postgresql=False)))
    module = source_module("memory/scoped.py")
    routers = []

    def router(actor):
        cfg = HarnessAgentConfig(name=f"test_{actor}", workspace_dir=str(tmp_path))
        # Keeps the tests usable with the released harness as well as the fork.
        cfg.memory_scope_resolver = lambda context: policy.resolve(actor, context)
        root = Memory(
            namespace=f"legacy_{actor}",
            backend_config={"db_path": str(tmp_path / f"legacy_{actor}.sqlite")},
        )
        service = module.ScopedMemoryService(
            MemoryService(root), config=cfg, workspace_path=tmp_path, llm=None, service_config={}
        )
        routers.append(service)
        return service

    a, b, other = router("a"), router("b"), router("other")

    def bind(router, tid, text="Remember the project baseline is amber", uid=1):
        return router.for_context(
            {"thread_id": tid, "user": str(uid)}, HumanMessage(content=text, id=f"m-{tid}")
        )

    harnesses = {
        "a": NS(memory_for_context=lambda cfg: a.for_context(cfg)),
        "b": NS(memory_for_context=lambda cfg: b.for_context(cfg)),
    }
    registry = NS(get_agent=harnesses.__getitem__)
    dashboard = ScopedMemoryDashboard(registry, repos, teams)
    yield NS(
        a=a,
        b=b,
        other=other,
        bind=bind,
        policy=policy,
        threads=threads,
        users=users,
        members=members,
        dashboard=dashboard,
    )
    for service in routers:
        service.close()
        from octop_harness.memory.store import close_memory_resources

        close_memory_resources(service.memory)


def test_same_project_shares_between_experts_and_group(system):
    s = system
    one = s.bind(s.a, "a1")
    saved = one.save("baseline is amber", evidence="baseline is amber")
    for router, tid in ((s.b, "b1"), (s.a, "room")):
        view = s.bind(router, tid)
        assert view.scope_id == one.scope_id
        assert "amber" in str(view.search("amber"))
    assert "amber" not in str(s.bind(s.a, "a2").search("amber"))
    assert "amber" not in str(s.bind(s.other, "foreign", uid=2).search("amber"))
    listed = s.dashboard.execute("b", "b1", 1, "list")
    assert listed["items"][0]["id"] == saved["atom_id"]
    assert listed["items"][0]["sources"][0]["thread_id"] == "a1"


def test_identity_ignores_forged_project_and_task_worktree(system):
    s = system
    actual = s.policy.resolve("a", {"thread_id": "a1", "user": "1"})
    forged = s.policy.resolve(
        "a",
        {
            "thread_id": "a1",
            "user": "1",
            "octop_project_path": "forged-worktree",
            "octop_project_name": "fake",
        },
    )
    assert actual == forged
    for cfg in (
        {"thread_id": "a1", "user": "2"},
        {"thread_id": "foreign", "user": "1"},
        {"thread_id": "missing", "user": "1"},
        {"thread_id": "a1", "user": True},
    ):
        with pytest.raises(PermissionError):
            s.policy.resolve("a", cfg)
    s.members.remove("b")
    with pytest.raises(PermissionError):
        s.policy.resolve("b", {"thread_id": "room", "user": "1"})
    s.users[1].disabled = True
    with pytest.raises(PermissionError):
        s.policy.resolve("a", {"thread_id": "a1", "user": "1"})


def test_user_preferences_shared_and_session_notes_stay_in_thread(system):
    s = system
    view = s.bind(s.a, "a1", "Always answer in Chinese; temporary note is saffron")
    view.save("Always answer in Chinese", scope="user", evidence="Always answer in Chinese")
    view.save("temporary note is saffron", scope="session", evidence="temporary note is saffron")
    another = s.bind(s.b, "b1")
    assert "Chinese" in str(another.search("Chinese"))
    assert "saffron" not in str(another.search("saffron"))
    assert "saffron" in str(view.search("saffron"))
    assert "Chinese" in str(s.bind(s.a, "a2").search("Chinese"))
    with pytest.raises(ValueError, match="quote evidence"):
        another.save("Assistant speculation becomes fact", evidence="not in the user's message")
    with pytest.raises(ValueError):
        s.bind(s.a, "a3").save("No project", scope="project", evidence="project")


def test_legacy_not_injected_and_cannot_be_written_by_scoped_tools(system):
    s = system
    s.a._root.save("Legacy unclassified memory is cerulean")
    view = s.bind(s.a, "a1")
    assert "cerulean" not in view.recall("cerulean").rendered
    assert "cerulean" not in str(view.search("cerulean"))
    assert "cerulean" in str(view.search("cerulean", scope="legacy"))
    assert "cerulean" in str(s.bind(s.a, "a3").search("cerulean"))
    with pytest.raises(ValueError, match="read-only"):
        view.save("cerulean", scope="legacy", user_action=True)
    shared = {**view.context, "legacy_readable": False}
    with pytest.raises(PermissionError):
        view.owner.open("legacy", shared)


def test_correction_retires_old_atom_and_preserves_journal(system):
    s = system
    view = s.bind(s.a, "a1", "Remember baseline amber; correction baseline vermilion")
    old = view.save("baseline amber", evidence="baseline amber")
    assert "amber" in str(view.search("amber"))
    assert "amber" in view.recall("amber").rendered
    new = view.save("baseline vermilion", evidence="baseline vermilion", replaces=old["atom_id"])
    memory = view.owner.open("project", view.context).memory
    assert memory.get_atom(old["atom_id"]).deprecated_at is not None
    assert memory.get_atom(old["atom_id"]).superseded_by == new["atom_id"]
    assert "amber" not in str(view.search("amber"))
    assert "vermilion" in str(s.bind(s.b, "b1").search("vermilion"))
    journal = s.dashboard.execute(
        "a", "a1", 1, "revisions", scope="project", atom_id=old["atom_id"]
    )
    assert journal["items"]
    assert any("amber" in str(item.get("before")) for item in journal["items"])


def test_background_capture_uses_bound_scope_and_visible_source(system):
    s = system
    first = s.bind(s.a, "a1")
    other = s.bind(s.a, "a2")
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(
            pool.map(
                lambda pair: pair[0].capture_turn(
                    user=pair[1],
                    session_id=pair[0].source["thread_id"],
                    thread_id=pair[0].source["thread_id"],
                    user_id="1",
                ),
                [(first, "Project one keyword magenta"), (other, "Project two keyword turquoise")],
            )
        )
    assert "turquoise" not in str(first.search("turquoise"))
    assert "magenta" not in str(other.search("magenta"))
    first_memory = first.owner.open("project", first.context).memory
    assert first_memory.list_raw()[0].thread_id == "a1"
    # The namespace snapshot survives reassignment before the worker executes.
    s.threads["a1"].project_path = s.threads["a2"].project_path
    first.capture_turn(
        user="Old project additional keyword citron", session_id="a1", thread_id="a1", user_id="1"
    )
    assert "citron" not in str(s.bind(s.a, "a1").search("citron"))


def test_scoped_snapshot_replay_never_resurrects_another_project():
    module = source_module("middleware/memory_recall.py")
    message = module.stamp_recall_snapshot(
        HumanMessage(content="question", id="u"), "secret old project", scope_id="project-one"
    )
    assert "secret" in module.replay_recall_snapshots([message], scope_id="project-one")[0].content
    assert (
        module.replay_recall_snapshots([message], scope_id="project-two")[0].content == "question"
    )
    assert "secret" in message.additional_kwargs[module.RECALL_SNAPSHOT_KEY]["suffix"]
    latest = module.stamp_recall_snapshot(
        HumanMessage(content="corrected question", id="u2"),
        "new confirmed fact",
        scope_id="project-one",
    )
    replayed = module.replay_recall_snapshots([message, latest], scope_id="project-one")
    assert replayed[0].content == "question"
    assert "new confirmed fact" in replayed[1].content
    from langchain_core.messages.utils import count_tokens_approximately

    assert module.count_tokens_with_recall([message, latest]) == count_tokens_approximately(
        replayed
    )


def test_dashboard_forbids_other_users_and_retires_without_deleting(system):
    s = system
    from octop.infra.errors import OctopError

    with pytest.raises(OctopError) as error:
        s.dashboard.execute("a", "a1", 2, "list")
    assert error.value.status == 403
    result = s.dashboard.execute(
        "a", "a1", 1, "save", content="User confirmed project specification"
    )
    s.dashboard.execute("a", "a1", 1, "deprecate", atom_id=result["atom_id"])
    assert s.dashboard.execute("b", "b1", 1, "list")["items"] == []
    assert len(s.dashboard.execute("b", "b1", 1, "list", include_deprecated=True)["items"]) == 1


def test_http_scope_authorization_validation_and_documented_schema(system):
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient

    from octop.api.deps import current_user, get_server
    from octop.api.routers.memory_scopes import router
    from octop.infra.errors import OctopError

    s = system
    app = FastAPI()
    app.include_router(router, prefix="/api")
    user = NS(id=1, is_admin=True)
    registry = NS(scoped_memory_operation=s.dashboard.execute)
    app.dependency_overrides[current_user] = lambda: user
    app.dependency_overrides[get_server] = lambda: NS(app_runtime=NS(agent_registry=registry))

    @app.exception_handler(OctopError)
    async def handle(_, error):
        return JSONResponse(error.to_envelope(), status_code=error.status)

    with TestClient(app) as client:
        base = "/api/agents/a/threads/a1/memory"
        token = client.get(base).json()["scope_token"]
        created = client.post(
            base,
            json={
                "scope": "project",
                "content": "Confirmed project standard",
                "expected_scope_token": token,
            },
        )
        assert created.status_code == 200, created.text
        assert client.get("/api/agents/b/threads/b1/memory").json()["total"] == 1
        assert client.get("/api/agents/a/threads/a2/memory").json()["total"] == 0
        assert (
            client.post(base, json={"scope": "project", "content": "x" * 4001}).status_code == 422
        )
        assert client.get(base, params={"scope": "forged-namespace"}).status_code == 422
        assert client.get("/api/agents/a/threads/foreign/memory").status_code == 403
        assert (
            client.post(
                base,
                json={
                    "scope": "project",
                    "content": "Wrong project must not receive this fact",
                    "expected_scope_token": "previous-project",
                },
            ).status_code
            == 409
        )
        user.id = 2
        assert client.get(base).status_code == 403
        schema = app.openapi()
        route = schema["paths"]["/api/agents/{agent_id}/threads/{thread_id}/memory"]["get"]
        assert route["summary"]
        assert route["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
            "ScopedMemories"
        )


def test_task_project_inheritance_preserves_user_choice_and_account_boundary(system):
    from unittest.mock import Mock

    from octop.infra.agents.threads.project_runtime import inherit_task_project

    s = system
    repo = NS(get=s.threads.get, set_project=Mock())
    inherit_task_project(repo, source_id="a1", target_id="b1", user_id=1, agent_id="b")
    repo.set_project.assert_not_called()  # Already bound: preserve user's choice.
    s.threads["b1"].project_path = None
    inherit_task_project(repo, source_id="a1", target_id="b1", user_id=1, agent_id="b")
    assert repo.set_project.call_args.kwargs["project_path"] == s.threads["a1"].project_path
    repo.set_project.reset_mock()
    inherit_task_project(repo, source_id="foreign", target_id="b1", user_id=1, agent_id="b")
    repo.set_project.assert_not_called()
