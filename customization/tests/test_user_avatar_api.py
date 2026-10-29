"""Account avatar selection regressions using temporary files and SQLite only."""
from __future__ import annotations

import base64
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from octop.api.deps import current_user, get_server
from octop.api.routers.auth import router as auth_router
from octop.api.routers.users import router as users_router
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.repos.users import UserRepo
from octop.infra.errors import OctopError
from octop.infra.users.profile_avatar import write_profile_avatar as real_write_profile_avatar

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a5VkAAAAASUVORK5CYII="
)


class UserAvatarApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(prefix="octop-user-avatar-tests-")
        self.root = Path(self.tmp.name)
        self.images = self.root / "private-user-avatars"
        self.db = SqlitePool(self.root / "control.sqlite3")
        run_migrations(self.db)
        self.repo = UserRepo(self.db)
        self.uid = self.repo.create(username="owner", role="user", display_name="饶朝洋")
        self.other = self.repo.create(username="other", role="user", display_name="Other User")
        self.actor_id = self.uid

        def as_user(row):
            return NS(id=row.id, username=row.username, role=row.role,
                      display_name=row.display_name, locale=row.locale,
                      is_admin=False, permissions=row.permissions)

        manager = NS(get_row=lambda uid: self.repo.get(uid),
                     get=lambda username: as_user(self.repo.get_by_username(username)),
                     list_sso_identities=lambda uid: [])
        self.server = NS(user_manager=manager, services=NS(
            user_repo=self.repo, paths=NS(user_avatars_dir=self.images)))
        app = FastAPI()
        app.include_router(auth_router, prefix="/api/auth")
        app.include_router(users_router, prefix="/api/users")
        app.dependency_overrides[current_user] = lambda: as_user(self.repo.get(self.actor_id))
        app.dependency_overrides[get_server] = lambda: self.server

        @app.exception_handler(OctopError)
        async def on_error(request, error):
            return JSONResponse(error.to_envelope(), status_code=error.status)

        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.db.close()
        self.tmp.cleanup()

    def upload(self, data=PNG):
        return self.client.post("/api/auth/me/avatar", files={"file": ("avatar.png", data, "image/png")})

    def archives(self, uid=None):
        directory = self.images / ".previous" / str(uid if uid is not None else self.uid)
        return sorted(directory.glob("*")) if directory.exists() else []

    def test_new_user_defaults_are_null_without_forcing_a_picture_choice(self):
        result = self.client.get("/api/auth/me")
        self.assertEqual(result.status_code, 200, result.text)
        self.assertIsNone(result.json()["avatar_url"])
        self.assertIsNone(result.json()["avatar_icon"])
        self.assertIsNone(self.repo.get(self.uid).avatar_icon)
        self.assertFalse(self.images.exists())

    def test_upload_response_and_readback_keep_the_explicit_picture(self):
        result = self.upload()
        self.assertEqual(result.status_code, 201, result.text)
        self.assertTrue(result.json()["avatar_url"].startswith(f"/api/users/{self.uid}/avatar?v="))
        for _ in range(2):
            me = self.client.get("/api/auth/me").json()
            self.assertEqual(me["avatar_url"], result.json()["avatar_url"])
            image = self.client.get(me["avatar_url"])
            self.assertEqual(image.status_code, 200)
            self.assertEqual(image.content, PNG)
        self.assertEqual(self.archives(), [])

    def test_replacing_images_within_one_second_changes_the_cache_version(self):
        # Force distinct mtimes inside the same second so this is deterministic
        # and catches the previous seconds-only cache key.
        stamps = iter((1_700_000_000_000_000_100, 1_700_000_000_000_000_200))

        def write_with_precise_mtime(directory, key, data, **kwargs):
            real_write_profile_avatar(directory, key, data, **kwargs)
            stamp = next(stamps)
            os.utime(directory / f"{key}.png", ns=(stamp, stamp))

        with patch("octop.infra.users.profile_avatar.write_profile_avatar", side_effect=write_with_precise_mtime):
            first = self.upload(PNG)
            second = self.upload(PNG + b"replacement")
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(second.status_code, 201, second.text)
        self.assertNotEqual(first.json()["avatar_url"], second.json()["avatar_url"])
        self.assertEqual(self.client.get("/api/auth/me").json()["avatar_url"], second.json()["avatar_url"])
        self.assertEqual((self.images / f"{self.uid}.png").read_bytes(), PNG + b"replacement")
        self.assertEqual(self.archives()[0].read_bytes(), PNG)

    def test_null_selection_clears_both_projections_but_archives_the_picture(self):
        self.repo.set_avatar_icon(self.uid, "staff")
        self.upload()
        result = self.client.patch("/api/auth/me", json={"avatar_icon": None})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertIsNone(result.json()["avatar_icon"])
        self.assertIsNone(result.json()["avatar_url"])
        self.assertFalse((self.images / f"{self.uid}.png").exists())
        self.assertEqual(len(self.archives()), 1)
        self.assertEqual(self.archives()[0].read_bytes(), PNG)
        self.assertEqual(self.client.get(f"/api/users/{self.uid}/avatar").status_code, 404)
        self.assertEqual(self.client.get("/api/auth/me").json()["avatar_icon"], None)

    def test_builtin_selection_is_persisted_without_erasing_the_picture(self):
        self.upload()
        result = self.client.patch("/api/auth/me", json={"avatar_icon": "doctor"})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["avatar_icon"], "doctor")
        self.assertIsNone(result.json()["avatar_url"])
        self.assertEqual(self.archives()[0].read_bytes(), PNG)
        self.db.close()
        self.db = SqlitePool(self.root / "control.sqlite3")
        self.repo = UserRepo(self.db)
        self.server.services.user_repo = self.repo
        self.assertEqual(self.client.get("/api/auth/me").json()["avatar_icon"], "doctor")

    def test_upload_replacement_and_repeated_selections_never_overwrite_archives(self):
        first, second, third = PNG, PNG + b"second", PNG + b"third"
        self.upload(first)
        self.upload(second)
        self.assertEqual([path.read_bytes() for path in self.archives()], [first])
        self.client.patch("/api/auth/me", json={"avatar_icon": None})
        self.client.patch("/api/auth/me", json={"avatar_icon": None})
        self.upload(third)
        self.client.patch("/api/auth/me", json={"avatar_icon": "teacher"})
        archived = self.archives()
        self.assertEqual(len(archived), 3)
        self.assertEqual(len({path.name for path in archived}), 3)
        self.assertCountEqual([path.read_bytes() for path in archived], [first, second, third])

    def test_delete_current_picture_uses_the_same_private_archive(self):
        self.upload()
        result = self.client.delete("/api/auth/me/avatar")
        self.assertEqual(result.status_code, 204)
        self.assertIsNone(self.client.get("/api/auth/me").json()["avatar_url"])
        self.assertEqual(self.archives()[0].read_bytes(), PNG)

    def test_selection_and_read_access_are_isolated_to_the_current_user(self):
        self.actor_id = self.other
        self.upload(PNG + b"other-user")
        self.repo.set_avatar_icon(self.other, "staff")
        self.actor_id = self.uid
        self.upload()
        result = self.client.patch("/api/auth/me", json={"avatar_icon": None, "user_id": self.other})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["id"], self.uid)
        self.assertEqual((self.images / f"{self.other}.png").read_bytes(), PNG + b"other-user")
        self.assertEqual(self.repo.get(self.other).avatar_icon, "staff")
        self.assertEqual(self.archives(self.other), [])
        self.assertEqual(self.client.get(f"/api/users/{self.other}/avatar").status_code, 403)

    def test_invalid_choice_or_upload_does_not_remove_the_current_image(self):
        self.upload()
        bad_icon = self.client.patch("/api/auth/me", json={"avatar_icon": "../bad"})
        self.assertGreaterEqual(bad_icon.status_code, 400)
        bad_upload = self.upload(b"not an image")
        self.assertGreaterEqual(bad_upload.status_code, 400)
        self.assertEqual((self.images / f"{self.uid}.png").read_bytes(), PNG)
        self.assertEqual(self.archives(), [])


if __name__ == "__main__":
    unittest.main()
