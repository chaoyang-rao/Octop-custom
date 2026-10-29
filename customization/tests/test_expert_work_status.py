"""Expert activity snapshots use only fake tasks and temporary identities."""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
from unittest.mock import patch

from octop_harness.acp.models import ACPConfig
from octop_harness.acp.service import ACPService

from octop.infra.agents.manager import AgentManager
from octop.infra.agents.work_status import attach_expert_work_status
from octop.infra.gateway.hitl.store import HitlPendingStore


class WorkStatusTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.pairs = {
            1: [("a", "web"), ("a", "im"), ("a", "cron"), ("b", "team-member")],
            2: [("a", "private-other")],
        }
        self.reads = []
        self.active = {}
        self.ws = set()
        self.acp = {}
        self.acp_calls = []
        self.pending = HitlPendingStore()

        def list_for_user(uid):
            self.reads.append(uid)
            return self.pairs.get(uid, [])

        async def acp_snapshot(aid, allowed):
            self.acp_calls.append((aid, allowed))
            return self.acp.get(aid, {"working_thread_ids": set(), "waiting_thread_ids": set()})

        self.registry = NS(
            active_thread_ids=lambda aid: frozenset(self.active.get(aid, ())),
            acp_activity_snapshot=acp_snapshot,
            is_agent_active=lambda aid: (_ for _ in ()).throw(
                AssertionError("global busy is private")
            ),
        )
        self.server = NS(
            services=NS(thread_repo=NS(list_for_user=list_for_user)),
            app_runtime=NS(
                agent_registry=self.registry,
                gateway=NS(
                    ws_hub=NS(is_turn_active=lambda tid: tid in self.ws),
                    processor=NS(hitl_coordinator=NS(store=self.pending)),
                ),
            ),
        )

    def row(self, aid="a", state="running"):
        return {"agent_id": aid, "state": state}

    def pause(self, tid, aid="a", uid=1):
        return self.pending.register(
            thread_id=tid,
            agent_id=aid,
            user_id=uid,
            session_key=f"{uid}:{tid}",
            channel_type="dashboard",
            action_requests=[],
            review_configs=None,
        )

    async def get(self, rows=None, uid=1):
        return await attach_expert_work_status(self.server, uid, rows or [self.row()])

    async def test_online_loaded_agent_is_idle_without_bound_work(self):
        self.assertEqual(
            await self.get(),
            [
                {
                    "agent_id": "a",
                    "state": "running",
                    "work_status": "idle",
                    "working_count": 0,
                    "waiting_count": 0,
                }
            ],
        )

    async def test_ws_and_registry_duplicate_count_is_one_thread(self):
        self.active["a"] = {"web"}
        self.ws.add("web")
        row = (await self.get())[0]
        self.assertEqual((row["work_status"], row["working_count"]), ("working", 1))

    async def test_non_dashboard_invocation_is_visible(self):
        self.active["a"] = {"im", "cron"}
        row = (await self.get())[0]
        self.assertEqual((row["work_status"], row["working_count"]), ("working", 2))

    async def test_pending_only_overrides_ws_and_registry_flags(self):
        self.active["a"] = {"web"}
        self.ws.add("web")
        self.pause("web")
        row = (await self.get())[0]
        self.assertEqual(
            (row["work_status"], row["working_count"], row["waiting_count"]), ("waiting", 0, 1)
        )

    async def test_other_work_and_pending_coexist(self):
        self.active["a"] = {"web", "im"}
        self.pause("web")
        row = (await self.get())[0]
        self.assertEqual(
            (row["work_status"], row["working_count"], row["waiting_count"]), ("working", 1, 1)
        )

    async def test_resolved_approval_returns_to_idle(self):
        record = self.pause("web")
        self.pending.mark_resolved(record.pending_id, "approved")
        self.assertEqual((await self.get())[0]["work_status"], "idle")

    async def test_same_agent_other_user_work_is_not_exposed(self):
        self.active["a"] = {"private-other", "unbound"}
        self.ws.add("private-other")
        self.pause("private-other", uid=2)
        self.acp["a"] = {
            "working_thread_ids": {"private-other"},
            "waiting_thread_ids": {"private-other"},
        }
        row = (await self.get())[0]
        self.assertEqual(
            (row["work_status"], row["working_count"], row["waiting_count"]), ("idle", 0, 0)
        )
        self.assertNotIn("private-other", repr(row))
        self.assertEqual(self.acp_calls[0][1], frozenset({"web", "im", "cron"}))

    async def test_same_visible_ids_are_filtered_per_agent(self):
        self.active["a"] = {"team-member"}
        self.active["b"] = {"team-member"}
        rows = await self.get([self.row("a"), self.row("b")])
        self.assertEqual([r["working_count"] for r in rows], [0, 1])
        self.assertEqual(self.reads, [1], "one identity query for the whole agent list")

    async def test_older_existing_acp_service_does_not_invent_idle(self):
        self.acp["a"] = None
        self.assertEqual((await self.get())[0]["work_status"], "unknown")

    async def test_acp_pending_counts_once_with_hitl(self):
        self.pause("web")
        self.acp["a"] = {"working_thread_ids": set(), "waiting_thread_ids": {"web"}}
        self.assertEqual((await self.get())[0]["waiting_count"], 1)

    async def test_explicit_acp_execution_can_coexist_with_waiting_on_same_thread(self):
        self.pause("web")
        self.acp["a"] = {"working_thread_ids": {"web"}, "waiting_thread_ids": {"web"}}
        row = (await self.get())[0]
        self.assertEqual(
            (row["work_status"], row["working_count"], row["waiting_count"]), ("working", 1, 1)
        )

    async def test_lifecycle_is_not_reported_idle_or_busy(self):
        self.active["a"] = {"web"}
        self.pause("web")
        for state in ("stopped", "starting", "stopping", "failed", "unknown"):
            row = (await self.get([self.row(state=state)]))[0]
            self.assertEqual(row["work_status"], state)
            self.assertEqual((row["working_count"], row["waiting_count"]), (0, 0))
        self.assertEqual(self.reads, [])

    async def test_legacy_fake_registry_and_missing_repositories_are_unknown(self):
        self.server.app_runtime.agent_registry = NS()
        row = (await self.get())[0]
        self.assertEqual(row["work_status"], "unknown")
        self.assertEqual(self.reads, [])
        self.server.app_runtime.agent_registry = self.registry
        self.server.services = NS()
        self.assertEqual((await self.get())[0]["work_status"], "unknown")

    async def test_real_thread_repository_is_safe_from_worker_and_scopes_users(self):
        from octop.infra.db.migrate import run_migrations
        from octop.infra.db.pool import SqlitePool
        from octop.infra.db.repos.threads import ThreadRepo

        with TemporaryDirectory(prefix="octop-work-status-") as temporary:
            pool = SqlitePool(Path(temporary) / "control.sqlite3")
            try:
                run_migrations(pool)
                with pool.connect() as connection:
                    for uid in (1, 2):
                        connection.execute(
                            "INSERT INTO users(id,username,role,created_at) VALUES (?,?,?,1)",
                            (uid, f"fake-{uid}", "user"),
                        )
                    connection.execute(
                        "INSERT INTO agents(agent_id,user_id,name,created_at,updated_at) VALUES ('a',1,'a',1,1)"
                    )
                repo = ThreadRepo(pool)
                for uid, tid in ((1, "web"), (2, "private-other")):
                    repo.insert(
                        thread_id=tid,
                        agent_id="a",
                        user_id=uid,
                        channel_type="dashboard",
                        session_key=f"fake:{uid}",
                    )
                self.server.services.thread_repo = repo
                self.active["a"] = {"web", "private-other"}
                row = (await self.get())[0]
                self.assertEqual((row["work_status"], row["working_count"]), ("working", 1))
            finally:
                pool.close()

    async def test_existing_agent_list_route_attaches_summary(self):
        from octop.api.routers import agents as api

        self.registry.list_agents = lambda uid: [NS(agent_id="a", user_id=uid, state="running")]
        self.registry.is_bootstrapped = lambda aid: True
        self.server.services.agent_repo = NS(
            list_shared=lambda **kwargs: [NS(agent_id="b", user_id=2, state="running")]
        )
        self.server.services.user_repo = NS(get=lambda uid: NS(username=f"u{uid}"))
        self.server.services.session_repo = NS(unread_totals_by_agent=lambda uid, aids: {"a": 2})
        self.active["a"] = {"web"}
        self.pause("team-member", aid="b")
        with patch.object(
            api, "_row_dict", side_effect=lambda row, **kwargs: self.row(row.agent_id, row.state)
        ):
            payloads = await api.list_agents(
                user=NS(id=1, is_admin=False), server=self.server, scope="mine"
            )
        by_id = {row["agent_id"]: row for row in payloads}
        self.assertEqual(
            (by_id["a"]["work_status"], by_id["a"]["working_count"], by_id["a"]["unread_count"]),
            ("working", 1, 2),
        )
        self.assertEqual((by_id["b"]["work_status"], by_id["b"]["waiting_count"]), ("waiting", 1))
        self.assertEqual(self.reads, [1])


class InvocationTrackingTests(unittest.IsolatedAsyncioTestCase):
    def manager(self):
        manager = AgentManager.__new__(AgentManager)
        manager._active_invocations = {}
        manager._invocation_waiters = {}
        manager._history_backfills = {}
        manager._reclaim_holds = {}
        manager._reclaim_pending = set()
        manager._thread_execution_locks = {}
        return manager

    async def test_nested_counts_keep_thread_until_last_invocation_exits(self):
        manager = self.manager()
        async with manager._track_invocation("a", "t"):
            async with manager._track_invocation("a", "t"):
                self.assertEqual(manager.active_thread_ids("a"), frozenset({"t"}))
            self.assertTrue(manager.is_agent_active("a"))
            self.assertEqual(manager.active_thread_ids("a"), frozenset({"t"}))
        self.assertFalse(manager.is_agent_active("a"))
        self.assertEqual(manager.active_thread_ids("a"), frozenset())

    async def test_unknown_thread_is_not_attributed_to_any_viewer(self):
        manager = self.manager()
        async with manager._track_invocation("a"):
            self.assertTrue(manager.is_agent_active("a"))
            self.assertEqual(manager.active_thread_ids("a"), frozenset())

    async def test_cancellation_cleans_existing_and_new_counters(self):
        manager = self.manager()
        started = asyncio.Event()

        async def run():
            async with manager._track_invocation("a", "t"):
                started.set()
                await asyncio.Event().wait()

        task = asyncio.create_task(run())
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(manager.is_agent_active("a"))
        self.assertEqual(manager.active_thread_ids("a"), frozenset())

    async def test_stream_call_and_resume_track_bound_thread(self):
        manager = self.manager()
        seen = []

        async def stream(aid, request):
            seen.append(manager.active_thread_ids(aid))
            yield {"type": "done"}

        async def call(aid, request):
            seen.append(manager.active_thread_ids(aid))
            return {"ok": True}

        async def resume(aid, tid, decisions, **kwargs):
            seen.append(manager.active_thread_ids(aid))
            yield {"type": "done"}

        manager._harness_manager = NS(stream=stream, call=call, resume_hitl=resume)
        manager._apply_pending_bootstrap_graph_refresh = lambda aid: None
        manager._prepare_stream_request = lambda aid, request: request
        manager._stream_model_label = lambda *args: "test"
        manager._thread_project_config = lambda *args: {}
        self.assertEqual(
            [c async for c in manager.stream("a", {"thread_id": "web"})], [{"type": "done"}]
        )
        await manager.call("a", {"configurable": {"thread_id": "im"}})
        self.assertEqual(
            [c async for c in manager.resume_hitl("a", "cron", [])], [{"type": "done"}]
        )
        self.assertEqual(seen, [frozenset({"web"}), frozenset({"im"}), frozenset({"cron"})])
        self.assertEqual(manager.active_thread_ids("a"), frozenset())

    async def test_busy_acp_handshake_is_bounded_without_cancelling_work(self):
        manager = self.manager()
        manager._harness_manager = NS(get_agent=lambda aid: NS(agent=NS(_workspace_path=aid)))
        snapshot_started = asyncio.Event()

        class ObservedService(ACPService):
            async def activity_snapshot(self, *, thread_ids):
                snapshot_started.set()
                return await super().activity_snapshot(thread_ids=thread_ids)

        blocked = ObservedService(config=ACPConfig())
        ready = ACPService(config=ACPConfig())
        held, release = asyncio.Event(), asyncio.Event()

        async def handshake():
            async with blocked._lock:
                held.set()
                await release.wait()

        startup = asyncio.create_task(handshake())
        await held.wait()
        server = NS(
            services=NS(thread_repo=NS(list_for_user=lambda uid: [("a", "web"), ("b", "cron")])),
            app_runtime=NS(
                agent_registry=manager,
                gateway=NS(
                    ws_hub=NS(is_turn_active=lambda tid: False),
                    processor=NS(hitl_coordinator=NS(store=HitlPendingStore())),
                ),
            ),
        )
        try:
            with patch(
                "octop_harness.acp.service.get_acp_service",
                side_effect=lambda key: {"a": blocked, "b": ready}[key],
            ):
                async with (
                    manager._track_invocation("a", "web"),
                    manager._track_invocation("b", "cron"),
                ):
                    rows = await asyncio.wait_for(
                        attach_expert_work_status(
                            server,
                            1,
                            [
                                {"agent_id": "a", "state": "running"},
                                {"agent_id": "b", "state": "running"},
                            ],
                        ),
                        timeout=2,
                    )
                    self.assertTrue(snapshot_started.is_set())
                    self.assertEqual(rows[0]["work_status"], "unknown")
                    self.assertEqual(
                        (rows[1]["work_status"], rows[1]["working_count"]), ("working", 1)
                    )
                    self.assertFalse(
                        startup.done(), "the read-only timeout must not cancel the actual handshake"
                    )
                    self.assertTrue(manager.is_agent_active("a"))
        finally:
            release.set()
            await startup
        self.assertFalse(manager.is_agent_active("a"))

    async def test_acp_snapshot_does_not_initialize_an_unused_service(self):
        manager = self.manager()
        manager._harness_manager = NS(
            get_agent=lambda aid: NS(agent=NS(_workspace_path="fake-key"))
        )
        with (
            patch("octop_harness.acp.service.get_acp_service", return_value=None) as getter,
            patch("octop_harness.acp.service.init_acp_service") as initialize,
        ):
            result = await manager.acp_activity_snapshot("a", frozenset({"web"}))
        self.assertEqual(
            result, {"working_thread_ids": frozenset(), "waiting_thread_ids": frozenset()}
        )
        getter.assert_called_once_with("fake-key")
        initialize.assert_not_called()


class AcpActivityTests(unittest.IsolatedAsyncioTestCase):
    def conversation(self, *, done=False, permission=None, exited=False):
        return NS(
            process=NS(returncode=0 if exited else None),
            prompt_task=None if done else NS(done=lambda: False),
            client=NS(pending_permission=permission),
        )

    async def test_only_unfinished_visible_tasks_count_not_open_processes(self):
        service = ACPService(config=ACPConfig())
        service._sessions = {
            ("web", "idle"): self.conversation(done=True),
            ("web", "running"): self.conversation(),
            ("web", "waiting"): self.conversation(permission=object()),
            ("other-user", "running"): self.conversation(),
            ("exited", "dead"): self.conversation(exited=True),
        }
        result = await service.activity_snapshot(thread_ids={"web", "exited"})
        self.assertEqual(
            result,
            {"working_thread_ids": frozenset({"web"}), "waiting_thread_ids": frozenset({"web"})},
        )

    async def test_completed_task_with_stale_permission_is_not_pending_work(self):
        service = ACPService(config=ACPConfig())
        completed = self.conversation(permission=object())
        completed.prompt_task.done = lambda: True
        service._sessions[("web", "runner")] = completed
        self.assertEqual(
            await service.activity_snapshot(thread_ids={"web"}),
            {"working_thread_ids": frozenset(), "waiting_thread_ids": frozenset()},
        )


if __name__ == "__main__":
    unittest.main()
