"""Geometric avatar API regressions using only a temporary control-plane DB."""
from __future__ import annotations
import asyncio
import json
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from pydantic import ValidationError

from octop.api.deps import current_user, get_server
from octop.api.common.agent_avatar import avatar_option_from_body
from octop.api.routers.agents import router, AgentCreateBody, AgentPatchBody
from octop.api.routers.experts import FromExpertBody, InstallPublishedExpertBody, _summary_dict
from octop.infra.agents.experts.catalog import Expert, ExpertSummary, build_create_spec_from_expert
from octop.infra.agents.experts.publish import PublishedExpertSnapshotMeta, _manifest_from_metadata
from octop.infra.agents.experts.published_creation import (
    PublishedExpertInstallOptions, install_published_expert, _snapshot_meta,
)
from octop.infra.agents.settings.geometric_avatar import AVATAR_SHAPES, AVATAR_COLORS, avatar_response, is_generated_avatar_icon_url
from octop.infra.agents.settings.profile import parse_config_json
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.repos.agents import AgentRepo
from octop.infra.errors import OctopError


class AvatarApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(prefix="octop-avatar-tests-")
        self.root = Path(self.tmp.name)
        self.db = SqlitePool(self.root/"control.sqlite3")
        run_migrations(self.db)
        with self.db.connect() as c:
            for uid in (1, 2):
                c.execute("INSERT INTO users(id,username,role,created_at) VALUES (?,?,?,1)",
                          (uid, f"u{uid}", "user"))
        self.repo = AgentRepo(self.db)
        self.original = {"backend": {"type": "local_shell", "root_dir": "/"},
                         "plugins": {"enabled": ["keep"]}, "memory": {"enabled": False},
                         "custom_existing_setting": {"nested": [1, 2]}}
        self.image = self.root/"uploaded-avatar.png"
        self.image.write_bytes(b"existing private image bytes")
        self.repo.create(agent_id="expert", user_id=1, name="Expert",
                         config_json=json.dumps(self.original), color="#aabbcc",
                         icon_url="/api/agents/expert/avatar")
        self.user = NS(id=1, username="u1", is_admin=False, permissions=[])
        self.update_calls = []
        self.create_specs = []
        async def update(aid, **kwargs):
            self.update_calls.append(kwargs)
            self.repo.update_config(aid, **kwargs)
            return self.repo.get(aid)
        async def create(spec, **kwargs):
            self.create_specs.append(spec)
            aid = spec.agent_id or f"created-{len(self.create_specs)}"
            self.repo.create(agent_id=aid, user_id=spec.user_id, name=spec.name,
                             config_json=json.dumps(spec.config), icon_url=spec.icon_url,
                             color=spec.color)
            return self.repo.get(aid)
        registry = NS(get_row=lambda aid: self.repo.get(aid), update=update, create=create,
                      is_bootstrapped=lambda aid: True,
                      list_agents=lambda uid: self.repo.list_by_user(uid),
                      validate_knowledge_base_ids=lambda uid, ids: ids,
                      validate_mcp_servers=lambda uid, ids: ids)
        self.server = NS(app_runtime=NS(agent_registry=registry),
                         services=NS(agent_repo=self.repo,
                           user_repo=NS(get=lambda uid: NS(username=f"u{uid}")),
                           user_policy_repo=NS(get=lambda *a: None),
                           session_repo=NS(unread_totals_by_agent=lambda *a: {})))
        app = FastAPI()
        app.include_router(router, prefix="/api/agents")
        app.dependency_overrides[current_user] = lambda: self.user
        app.dependency_overrides[get_server] = lambda: self.server
        @app.exception_handler(OctopError)
        async def on_error(request, error):
            return JSONResponse(error.to_envelope(), status_code=error.status)
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.db.close()
        self.tmp.cleanup()

    def test_all_49_choices_are_independent_and_preserve_real_image_and_card_color(self):
        for shape in AVATAR_SHAPES:
            for color in AVATAR_COLORS:
                result = self.client.patch("/api/agents/expert", json={
                    "avatar_shape": shape, "avatar_color": color})
                self.assertEqual(result.status_code, 200, result.text)
                out = result.json()
                self.assertEqual(out["icon_url"], f"/expert-avatars/v2/{shape}-{color}.svg")
                self.assertTrue(out["uploaded_icon_url"].startswith("/api/agents/expert/avatar"))
                self.assertEqual(out["color"], "#aabbcc")
                row = self.repo.get("expert")
                self.assertEqual(row.icon_url, "/api/agents/expert/avatar")
                config = parse_config_json(row.config_json)
                self.assertEqual(config["avatar"], {"shape": shape, "color": color})
                for key, value in self.original.items():
                    self.assertEqual(config[key], value)
        self.assertEqual(self.update_calls, [], "display-only saves must not reload the harness")
        self.assertEqual(self.image.read_bytes(), b"existing private image bytes")

    def test_partial_choice_changes_and_explicit_disable_restore_old_image(self):
        self.client.patch("/api/agents/expert", json={"avatar_shape": "star", "avatar_color": "jade"})
        color_only = self.client.patch("/api/agents/expert", json={"avatar_color": "ink"}).json()
        self.assertEqual(color_only["avatar_shape"], "star")
        self.assertEqual(color_only["icon_url"], "/expert-avatars/v2/star-ink.svg")
        shape_only = self.client.patch("/api/agents/expert", json={"avatar_shape": "cloud"}).json()
        self.assertEqual(shape_only["avatar_color"], "ink")
        disabled = self.client.patch("/api/agents/expert", json={"avatar_shape": None}).json()
        self.assertIsNone(disabled["avatar_shape"])
        self.assertEqual(disabled["icon_url"], disabled["uploaded_icon_url"])
        self.assertTrue(self.image.exists())

    def test_save_readback_after_reopen_and_full_config_edits_keep_metadata(self):
        self.client.patch("/api/agents/expert", json={"avatar_shape": "droplet", "avatar_color": "rose"})
        self.db.close()
        self.db = SqlitePool(self.root/"control.sqlite3")
        self.repo = AgentRepo(self.db)
        self.server.services.agent_repo = self.repo
        result = self.client.get("/api/agents/expert").json()
        self.assertEqual((result["avatar_shape"], result["avatar_color"]), ("droplet", "rose"))
        result = self.client.patch("/api/agents/expert", json={"config": {"heartbeat": {"enabled": False}}})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["avatar_shape"], "droplet")
        self.assertEqual(result.json()["config"]["heartbeat"], {"enabled": False})
        listed = self.client.get("/api/agents").json()
        self.assertEqual(listed[0]["icon_url"], "/expert-avatars/v2/droplet-rose.svg")

    def test_invalid_ids_and_nested_config_cannot_bypass_validation(self):
        for body in ({"avatar_shape": "../../image"}, {"avatar_color": "#ff0000"},
                     {"config": {"avatar": {"shape": "invalid", "color": "ink"}}},
                     {"config": {"avatar": {"shape": "blob", "color": []}}}):
            result = self.client.patch("/api/agents/expert", json=body)
            self.assertEqual(result.status_code, 422, result.text)
        self.assertNotIn("avatar", parse_config_json(self.repo.get("expert").config_json))
        for model in (AgentCreateBody, AgentPatchBody, FromExpertBody, InstallPublishedExpertBody):
            kwargs = {"name": "new", "avatar_shape": "pentagon"}
            with self.assertRaises(ValidationError):
                model(**kwargs)

    def test_permission_isolation_and_no_metadata_mutation_for_other_owner(self):
        self.user = NS(id=2, username="u2", is_admin=False, permissions=[])
        result = self.client.patch("/api/agents/expert", json={"avatar_shape": "blob"})
        self.assertEqual(result.status_code, 403)
        self.assertEqual(self.client.get("/api/agents/expert").status_code, 403)
        self.assertNotIn("avatar", parse_config_json(self.repo.get("expert").config_json))
        self.user.is_admin = True
        self.assertEqual(self.client.patch("/api/agents/expert", json={"avatar_shape": "blob"}).status_code, 200)

    def test_create_body_writes_valid_metadata_and_preserves_config(self):
        result = self.client.post("/api/agents", json={"name": "New", "config": self.original,
                                  "avatar_shape": "triangle", "avatar_color": "coral"})
        self.assertEqual(result.status_code, 201, result.text)
        out = result.json()
        self.assertEqual(out["icon_url"], "/expert-avatars/v2/triangle-coral.svg")
        spec = self.create_specs[-1]
        self.assertEqual(spec.config["custom_existing_setting"], self.original["custom_existing_setting"])
        self.assertEqual(spec.config["avatar"], {"shape": "triangle", "color": "coral"})

    def test_legacy_image_and_missing_color_have_safe_defaults(self):
        result = self.client.get("/api/agents/expert").json()
        self.assertIsNone(result["avatar_shape"])
        self.assertTrue(result["icon_url"].startswith("/api/agents/expert/avatar"))
        active = self.client.patch("/api/agents/expert", json={"avatar_shape": "pebble"}).json()
        self.assertEqual(active["icon_url"], "/expert-avatars/v2/pebble-ink.svg")
        self.assertEqual(avatar_response({"avatar": {"shape": "<bad>"}}, "/image.png")["icon_url"], "/image.png")

    def test_old_editor_projection_echo_does_not_replace_uploaded_image(self):
        self.client.patch("/api/agents/expert", json={"avatar_shape": "star", "avatar_color": "blue"})
        projected = self.client.get("/api/agents/expert").json()["icon_url"]
        echoed = self.client.patch("/api/agents/expert", json={
            "name": "Renamed", "icon_url": projected + "?v=123&cache=refresh",
        })
        self.assertEqual(echoed.status_code, 200, echoed.text)
        self.assertEqual(self.repo.get("expert").name, "Renamed")
        self.assertEqual(self.repo.get("expert").icon_url, "/api/agents/expert/avatar")
        self.assertNotIn("icon_url", self.update_calls[-1])
        restored = self.client.patch("/api/agents/expert", json={"avatar_shape": None}).json()
        self.assertIsNone(restored["avatar_shape"])
        self.assertTrue(restored["icon_url"].startswith("/api/agents/expert/avatar"))
        self.assertEqual(restored["icon_url"], restored["uploaded_icon_url"])

    def test_nested_projection_echo_is_removed_before_profile_lifting(self):
        self.client.patch("/api/agents/expert", json={"avatar_shape": "blob", "avatar_color": "jade"})
        projected = self.client.get("/api/agents/expert").json()["icon_url"]
        echoed = self.client.patch("/api/agents/expert", json={
            "config": {"icon_url": projected + "?v=1", "heartbeat": {"enabled": False}},
        })
        self.assertEqual(echoed.status_code, 200, echoed.text)
        self.assertNotIn("icon_url", json.loads(self.update_calls[-1]["config_json"]))
        self.assertEqual(self.repo.get("expert").icon_url, "/api/agents/expert/avatar")
        self.assertEqual(echoed.json()["avatar_shape"], "blob")

    def test_only_valid_reserved_projections_are_filtered_on_patch(self):
        for version in ("v1", "v2"):
            for shape in AVATAR_SHAPES:
                for color in AVATAR_COLORS:
                    for suffix in ("", "?v=1", "#preview", "?cache=1#preview"):
                        self.assertTrue(is_generated_avatar_icon_url(f"/expert-avatars/{version}/{shape}-{color}.svg{suffix}"))
        for url in ("/expert-avatars/v2/pentagon-ink.svg", "/expert-avatars/v1/blob-red.svg",
                    "/expert-avatars/v3/blob-ink.svg",
                    "https://external.example/expert-avatars/v1/blob-ink.svg",
                    "https://external.example/expert-avatars/v2/blob-ink.svg", "/other-image.svg"):
            self.assertFalse(is_generated_avatar_icon_url(url))
            result = self.client.patch("/api/agents/expert", json={"icon_url": url})
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(self.repo.get("expert").icon_url, url)

    def test_both_projection_versions_can_be_echoed_when_restoring_the_uploaded_image(self):
        for version in ("v1", "v2"):
            for suffix in ("?v=old-tab", "#cached-preview"):
                with self.subTest(version=version, suffix=suffix):
                    self.client.patch("/api/agents/expert", json={"avatar_shape": "star", "avatar_color": "blue"})
                    response = self.client.patch("/api/agents/expert", json={
                        "avatar_shape": None,
                        "icon_url": f"/expert-avatars/{version}/star-blue.svg{suffix}",
                    })
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertIsNone(response.json()["avatar_shape"])
                    self.assertTrue(response.json()["icon_url"].startswith("/api/agents/expert/avatar"))
                    self.assertEqual(self.repo.get("expert").icon_url, "/api/agents/expert/avatar")
                    self.assertEqual(self.image.read_bytes(), b"existing private image bytes")

    def test_palette_ids_and_hex_values_match_the_frontend_library(self):
        expected = {
            "ink": "#252830", "jade": "#19B7A2", "blue": "#486BCD", "violet": "#825DC5",
            "rose": "#DB779A", "amber": "#DCAA46", "coral": "#E5805D",
        }
        self.assertEqual(AVATAR_COLORS, expected)
        source = (Path(__file__).resolve().parents[1] / "packages/octop/dashboard/assets/expert-avatars.js").read_text()
        frontend = dict(re.findall(r"id:\s*['\"]([a-z]+)['\"][^\n}]*?hex:\s*['\"](#[0-9A-Fa-f]{6})['\"]", source))
        self.assertEqual({key: value.upper() for key, value in frontend.items()}, expected)

    def test_top_level_selection_wins_over_stale_form_config_and_upload_switches_to_image(self):
        self.client.patch("/api/agents/expert", json={"avatar_shape": "blob", "avatar_color": "blue"})
        stale = parse_config_json(self.repo.get("expert").config_json)
        result = self.client.patch("/api/agents/expert", json={"config": stale,
                                  "avatar_shape": "star", "avatar_color": "jade"})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["icon_url"], "/expert-avatars/v2/star-jade.svg")
        def set_icon(aid, url):
            self.repo.update_config(aid, icon_url=url)
            return self.repo.get(aid)
        self.server.app_runtime.agent_registry.set_icon_url = set_icon
        with patch("octop.api.routers.agents.require_agent_workspace", new=AsyncMock(return_value=object())), \
             patch("octop.api.routers.agents.write_workspace_avatar", new=AsyncMock()) as writer:
            uploaded = self.client.post("/api/agents/expert/avatar", files={
                "file": ("new.png", b"boundary-mocked-image", "image/png")})
        self.assertEqual(uploaded.status_code, 201, uploaded.text)
        self.assertIsNone(uploaded.json()["avatar_shape"])
        self.assertEqual(uploaded.json()["avatar_color"], "jade")
        self.assertEqual(uploaded.json()["icon_url"], uploaded.json()["uploaded_icon_url"])
        self.assertEqual(writer.await_count, 1)

    def test_template_snapshot_export_catalog_import_and_published_install_roundtrip(self):
        self.client.patch("/api/agents/expert", json={"avatar_shape": "squircle", "avatar_color": "violet"})
        source = self.repo.get("expert")
        meta = _snapshot_meta(source, name="Template", description="description", color=source.color)
        manifest = json.loads(_manifest_from_metadata(meta, manifest_id="template"))
        self.assertEqual(manifest["avatar"], {"shape": "squircle", "color": "violet"})
        summary = ExpertSummary(id="template", label_zh="Template", label_en="Template",
                    description_zh="", description_en="", avatar=manifest["avatar"])
        summary_out = _summary_dict(summary)
        self.assertEqual(summary_out["icon_url"], "/expert-avatars/v2/squircle-violet.svg")
        spec = build_create_spec_from_expert(expert_id="template", expert=Expert(summary), user_id=1)
        self.assertEqual(spec.config["avatar"], manifest["avatar"])
        snapshot_root = self.root/"snapshots"
        snapshot = snapshot_root/"published1"
        snapshot.mkdir(parents=True)
        (snapshot/"manifest.json").write_text(json.dumps(manifest))
        published = NS(id="published1", name="Template", description="desc", icon_name=None, color=None)
        services = NS(paths=NS(published_experts_dir=snapshot_root))
        created = self.repo.get("expert")
        registry = NS(create=AsyncMock(return_value=created), is_bootstrapped=lambda aid: True)
        with patch("octop.infra.agents.experts.published_creation.require_published_expert", return_value=published):
            asyncio.run(install_published_expert(services=services, registry=registry, user=self.user,
                        expert_id="published1", options=PublishedExpertInstallOptions(name="Installed")))
        installed_spec = registry.create.await_args.args[0]
        self.assertEqual(installed_spec.config["avatar"], manifest["avatar"])
        # Explicit null shape disables inherited geometry without deleting a snapshot image.
        registry.create.reset_mock()
        with patch("octop.infra.agents.experts.published_creation.require_published_expert", return_value=published):
            asyncio.run(install_published_expert(services=services, registry=registry, user=self.user,
                        expert_id="published1", options=PublishedExpertInstallOptions(
                            name="Installed", avatar={"shape": None, "color": "ink"})))
        self.assertIsNone(registry.create.await_args.args[0].config["avatar"]["shape"])

    def test_template_partial_overrides_preserve_omitted_shape_or_color(self):
        inherited = {"shape": "squircle", "color": "violet"}
        summary = ExpertSummary(id="template", label_zh="Template", label_en="Template",
                                description_zh="", description_en="", avatar=inherited)
        snapshot_root = self.root/"partial-snapshots"
        snapshot = snapshot_root/"published1"
        snapshot.mkdir(parents=True)
        (snapshot/"manifest.json").write_text(json.dumps({"avatar": inherited}))
        published = NS(id="published1", name="Template", description="desc", icon_name=None, color=None)
        services = NS(paths=NS(published_experts_dir=snapshot_root))
        created = self.repo.get("expert")
        registry = NS(create=AsyncMock(return_value=created), is_bootstrapped=lambda aid: True)
        cases = (
            ({"avatar_color": "jade"}, {"shape": "squircle", "color": "jade"}),
            ({"avatar_shape": "triangle"}, {"shape": "triangle", "color": "violet"}),
            ({"avatar_shape": None}, {"shape": None, "color": "violet"}),
            ({"avatar_color": None}, {"shape": "squircle", "color": None}),
            ({}, inherited),
        )
        for fields, expected in cases:
            with self.subTest(fields=fields):
                body = FromExpertBody(**fields)
                option = avatar_option_from_body(body)
                config_extra = {"avatar": option} if option is not None else None
                spec = build_create_spec_from_expert(
                    expert_id="template", expert=Expert(summary), user_id=1,
                    config_extra=config_extra,
                )
                self.assertEqual(spec.config["avatar"], expected)
                published_option = avatar_option_from_body(InstallPublishedExpertBody(name="Installed", **fields))
                registry.create.reset_mock()
                with patch("octop.infra.agents.experts.published_creation.require_published_expert", return_value=published):
                    asyncio.run(install_published_expert(
                        services=services, registry=registry, user=self.user, expert_id="published1",
                        options=PublishedExpertInstallOptions(name="Installed", avatar=published_option),
                    ))
                self.assertEqual(registry.create.await_args.args[0].config["avatar"], expected)


if __name__ == "__main__":
    unittest.main()
