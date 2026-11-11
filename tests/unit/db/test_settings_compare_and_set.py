"""Atomic settings updates preserve concurrent writers on SQLite and SQL adapters."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.repos.settings import SettingsRepo


@pytest.fixture
def settings(tmp_path: Path):
    pool = SqlitePool(tmp_path / "settings.db")
    run_migrations(pool)
    yield SettingsRepo(pool)
    pool.close()


def test_insert_update_and_stale_compare_do_not_overwrite(settings):
    assert settings.compare_and_set("catalog", None, "v1") is True
    assert settings.compare_and_set("catalog", None, "other") is False
    assert settings.compare_and_set("catalog", "wrong", "other") is False
    assert settings.compare_and_set("catalog", "v1", "v2") is True
    assert settings.get("catalog") == "v2"
    assert settings.compare_and_set("absent", "v1", "v2") is False
    assert settings.get("absent") is None


@pytest.mark.parametrize("initial", [None, "initial"])
def test_two_database_connections_have_only_one_cas_winner(tmp_path: Path, initial):
    path = tmp_path / "shared.db"
    first = SqlitePool(path)
    run_migrations(first)
    second = SqlitePool(path)
    try:
        repos = [SettingsRepo(first), SettingsRepo(second)]
        if initial is not None:
            repos[0].set("catalog", initial)
        barrier = Barrier(2)

        def write(index):
            barrier.wait(timeout=5)
            return repos[index].compare_and_set("catalog", initial, f"writer-{index}")

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(write, [0, 1]))
        assert sum(results) == 1
        assert repos[0].get("catalog") == f"writer-{results.index(True)}"
    finally:
        first.close()
        second.close()
