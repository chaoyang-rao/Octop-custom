"""Portraits stored in the shared database, adopted from disk once."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import build_shared_services
from octop.infra.users.profile_avatar import (
    KIND_ROLE,
    KIND_USER,
    AvatarNamespace,
    adopt_local_avatars,
)
from octop.infra.utils.paths import PathLayout

posix_only = pytest.mark.skipif(os.name != "posix", reason="POSIX symlinks")

_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
    b"\x00\x00\x00\x03\x00\x01\x00\x05\xfe\xd4\xef\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _services(tmp_path: Path):
    from octop.config import OctopConfig

    db = SqlitePool(tmp_path / "octop.db")
    run_migrations(db)
    return build_shared_services(db=db, paths=PathLayout(tmp_path), config=OctopConfig())


def test_avatar_roundtrip_uses_database(tmp_path: Path) -> None:
    services = _services(tmp_path)
    store = AvatarNamespace(services.profile_avatar_repo, KIND_USER)
    store.write("7", _PNG)
    found = store.read("7")
    assert found is not None
    assert found[0] == _PNG
    assert store.url("7", "/api/users/7/avatar").startswith("/api/users/7/avatar?v=")
    store.delete("7")
    assert store.read("7") is None


def test_user_portrait_replacement_and_clear_keep_private_previous_bytes(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from octop.infra.errors import OctopError
    from octop.infra.users import profile_avatar

    services = _services(tmp_path)
    store = services.avatars(KIND_USER)
    store.write("7", _PNG)
    identities = iter(("first", "second"))
    monkeypatch.setattr(profile_avatar, "uuid4", lambda: SimpleNamespace(hex=next(identities)))
    with pytest.raises(OctopError):
        profile_avatar.write_profile_avatar(store, "7", b"invalid", preserve_previous=True)
    assert store.read("7")[0] == _PNG
    profile_avatar.write_profile_avatar(store, "7", _PNG, preserve_previous=True)
    assert services.profile_avatar_repo.get("user.previous", "7-first").content == _PNG
    profile_avatar.archive_profile_avatar(store, "7")
    assert store.read("7") is None
    assert store.read("7-first") is None
    assert services.profile_avatar_repo.get("user.previous", "7-second").content == _PNG


def test_same_second_portrait_replacements_change_cache_url(tmp_path, monkeypatch):
    monkeypatch.setattr("octop.infra.db.repos.profile_avatars.now_ts", lambda: 42)
    store = _services(tmp_path).avatars(KIND_USER)
    store.write("7", _PNG)
    first = store.url("7", "/api/users/7/avatar")
    store.write("7", _PNG + b"new-image")
    assert store.url("7", "/api/users/7/avatar") != first


def test_adopt_skips_rows_already_stored_and_closes(tmp_path: Path) -> None:
    services = _services(tmp_path)
    avatar_dir = services.paths.user_avatars_dir
    avatar_dir.mkdir(parents=True)
    (avatar_dir / "7.png").write_bytes(_PNG)
    services.profile_avatar_repo.put(KIND_USER, "7", b"kept", "image/png")

    adopt_local_avatars(services.profile_avatar_repo, services.settings_repo, services.paths)

    stored = services.profile_avatar_repo.get(KIND_USER, "7")
    assert stored is not None
    assert stored.content == b"kept"

    (avatar_dir / "8.png").write_bytes(_PNG)
    adopt_local_avatars(services.profile_avatar_repo, services.settings_repo, services.paths)
    assert services.profile_avatar_repo.get(KIND_USER, "8") is None


def test_adopt_copies_missing_portraits_once(tmp_path: Path) -> None:
    services = _services(tmp_path)
    user_dir = services.paths.user_avatars_dir
    role_dir = services.paths.role_avatars_dir
    user_dir.mkdir(parents=True)
    role_dir.mkdir(parents=True)
    (user_dir / "9.png").write_bytes(_PNG)
    (role_dir / "admin.png").write_bytes(_PNG)
    (user_dir / "notes.txt").write_bytes(b"not an image")

    adopt_local_avatars(services.profile_avatar_repo, services.settings_repo, services.paths)

    user = services.profile_avatar_repo.get(KIND_USER, "9")
    role = services.profile_avatar_repo.get(KIND_ROLE, "admin")
    assert user is not None and user.content == _PNG
    assert role is not None and role.content == _PNG
    assert services.profile_avatar_repo.get(KIND_USER, "notes") is None


@posix_only
def test_adopt_skips_symlink(tmp_path: Path) -> None:
    services = _services(tmp_path)
    avatar_dir = services.paths.user_avatars_dir
    avatar_dir.mkdir(parents=True)
    target = tmp_path / "real.png"
    target.write_bytes(_PNG)
    (avatar_dir / "link.png").symlink_to(target)

    adopt_local_avatars(services.profile_avatar_repo, services.settings_repo, services.paths)

    assert services.profile_avatar_repo.get(KIND_USER, "link") is None
