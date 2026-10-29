"""Offline restoration checks using temporary programs and SQLite only."""

from __future__ import annotations

import hashlib
import importlib.util
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "restore_customization", Path(__file__).with_name("restore_customization.py")
)
assert SPEC and SPEC.loader
recovery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recovery)


class RestoreCustomizationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="octop-recovery-test-")
        self.root = Path(self.temporary.name)
        self.repo, self.home = self.root / "repo", self.root / "home"
        self.packages = self.root / "portable" / "packages"
        self.source = self.repo / "customization" / "packages"
        self.baseline = self.repo / "customization" / "baselines" / "original"
        for package in recovery.PACKAGE_NAMES:
            for base in (self.source, self.baseline, self.packages):
                (base / package).mkdir(parents=True)
        self.before = self.packages / "octop" / "program.py"
        for base in (self.baseline, self.packages):
            (base / "octop" / "program.py").write_bytes(b"original program")
        (self.source / "octop" / "program.py").write_bytes(b"reviewed customization")
        (self.source / "octop_harness" / "new.py").write_bytes(b"new project feature")
        for base in (self.source, self.baseline):
            (base / "octop" / "unchanged.py").write_bytes(b"unchanged baseline")
        (self.packages / "octop" / "unchanged.py").write_bytes(b"unrelated local edit")
        self.metadata = self.packages / "octop-1.0.2.dist-info" / "METADATA"
        self.metadata.parent.mkdir()
        self.metadata.write_text("Name: octop\nVersion: 1.0.2\n", encoding="utf-8")
        self.database = self.home / ".octop" / "octop.db"

    def tearDown(self):
        self.temporary.cleanup()

    def restore(self, apply=False):
        return recovery.restore(self.packages, apply=apply, repo=self.repo, home=self.home)

    def test_check_is_read_only_and_only_manages_program_differences(self):
        result = self.restore()
        self.assertEqual(result["mode"], "check")
        self.assertEqual(result["pending_files"], 3)
        self.assertEqual(self.before.read_bytes(), b"original program")
        self.assertFalse((self.packages.parent / "customization-backups").exists())
        self.assertFalse((self.packages / recovery.MARKER).exists())

    def test_new_upstream_metadata_is_refused_even_when_version_txt_claims_compatibility(self):
        self.metadata.write_text("Name: octop\nVersion: 1.0.3\n", encoding="utf-8")
        (self.packages.parent / "VERSION.txt").write_text("octop_version=1.0.2", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "METADATA"):
            self.restore(True)
        self.assertEqual(self.before.read_bytes(), b"original program")

    def test_independent_program_drift_is_refused_without_any_mutation(self):
        self.before.write_bytes(b"third-party customization")
        with self.assertRaisesRegex(ValueError, "Independent"):
            self.restore(True)
        self.assertEqual(self.before.read_bytes(), b"third-party customization")
        self.assertFalse((self.packages.parent / "customization-backups").exists())

    def test_added_file_must_be_missing_or_match_current_repository(self):
        path = self.packages / "octop_harness" / "new.py"
        path.write_bytes(b"unreviewed file at added path")
        with self.assertRaisesRegex(ValueError, "Independent"):
            self.restore(True)
        self.assertEqual(path.read_bytes(), b"unreviewed file at added path")

    def test_apply_is_idempotent_and_adds_update_guard_marker(self):
        first = self.restore(True)
        backup = Path(first["backup"])
        self.assertTrue((self.packages / recovery.MARKER).is_file())
        self.assertEqual(self.before.read_bytes(), b"reviewed customization")
        self.assertEqual(
            (self.packages / "octop_harness" / "new.py").read_bytes(), b"new project feature"
        )
        self.assertEqual(
            (self.packages / "octop" / "unchanged.py").read_bytes(), b"unrelated local edit"
        )
        second = self.restore(True)
        self.assertEqual(second["pending_files"], 0)
        self.assertNotIn("backup", second)
        self.assertEqual(list(backup.parent.iterdir()), [backup])
        if os.name == "posix":
            self.assertEqual(backup.stat().st_mode & 0o777, 0o700)
            self.assertEqual((backup / "manifest.json").stat().st_mode & 0o777, 0o600)

    def test_known_previous_program_and_manifest_are_restored_on_rollback(self):
        self.before.write_bytes(b"previous reviewed customization")
        state = self.packages.parent / recovery.INSTALL_MANIFEST
        previous = recovery.json_bytes(
            {
                "upstream_version": "1.0.2",
                "package_file_sha256": {
                    "octop/program.py": hashlib.sha256(self.before.read_bytes()).hexdigest()
                },
            }
        )
        state.write_bytes(previous)
        result = self.restore(True)
        recovery.rollback(self.packages, Path(result["backup"]), apply=True)
        self.assertEqual(self.before.read_bytes(), b"previous reviewed customization")
        self.assertEqual(state.read_bytes(), previous)
        self.assertFalse((self.packages / "octop_harness" / "new.py").exists())

    def test_verified_portable_manifest_is_accepted_and_existing_marker_is_preserved(self):
        self.before.write_bytes(b"previous portable customization")
        added = self.packages / "octop_harness" / "new.py"
        added.write_bytes(b"previous portable project feature")
        manifest = recovery.json_bytes(
            {
                "upstream_version": "1.0.2",
                "package_file_sha256": {
                    "packages/octop/program.py": hashlib.sha256(
                        self.before.read_bytes()
                    ).hexdigest(),
                    "packages/octop_harness/new.py": hashlib.sha256(added.read_bytes()).hexdigest(),
                },
            }
        )
        (self.packages.parent / "custom-release-manifest.json").write_bytes(manifest)
        marker = recovery.json_bytes(
            {
                "upstream_version": "1.0.2",
                "manifest": "custom-release-manifest.json",
                "manifest_sha256": hashlib.sha256(manifest).hexdigest(),
            }
        )
        (self.packages / recovery.MARKER).write_bytes(marker)
        result = self.restore(True)
        self.assertEqual(self.before.read_bytes(), b"reviewed customization")
        self.assertEqual(added.read_bytes(), b"new project feature")
        self.assertEqual((self.packages / recovery.MARKER).read_bytes(), marker)
        recovery.rollback(self.packages, Path(result["backup"]), apply=True)
        self.assertEqual(self.before.read_bytes(), b"previous portable customization")
        self.assertEqual(added.read_bytes(), b"previous portable project feature")
        self.assertEqual((self.packages / recovery.MARKER).read_bytes(), marker)

    def test_local_restore_manifest_accepts_previously_added_custom_file(self):
        added = self.packages / "octop_harness" / "new.py"
        added.write_bytes(b"previous local project feature")
        state = self.packages.parent / recovery.INSTALL_MANIFEST
        previous = recovery.json_bytes(
            {
                "upstream_version": "1.0.2",
                "package_file_sha256": {
                    "octop_harness/new.py": hashlib.sha256(added.read_bytes()).hexdigest()
                },
            }
        )
        state.write_bytes(previous)
        result = self.restore(True)
        self.assertEqual(added.read_bytes(), b"new project feature")
        recovery.rollback(self.packages, Path(result["backup"]), apply=True)
        self.assertEqual(added.read_bytes(), b"previous local project feature")
        self.assertEqual(state.read_bytes(), previous)

    def test_verified_portable_manifest_does_not_allow_unknown_added_file_drift(self):
        added = self.packages / "octop_harness" / "new.py"
        manifest = recovery.json_bytes(
            {
                "upstream_version": "1.0.2",
                "package_file_sha256": {
                    "packages/octop_harness/new.py": hashlib.sha256(
                        b"previous reviewed feature"
                    ).hexdigest()
                },
            }
        )
        (self.packages.parent / "custom-release-manifest.json").write_bytes(manifest)
        (self.packages / recovery.MARKER).write_bytes(
            recovery.json_bytes({"manifest_sha256": hashlib.sha256(manifest).hexdigest()})
        )
        added.write_bytes(b"unreviewed independent edit")
        with self.assertRaisesRegex(ValueError, "Independent"):
            self.restore(True)
        self.assertEqual(added.read_bytes(), b"unreviewed independent edit")
        self.assertEqual(self.before.read_bytes(), b"original program")
        self.assertFalse((self.packages.parent / "customization-backups").exists())

    def test_sqlite_backup_includes_wal_and_rollback_never_reverts_new_chats(self):
        self.database.parent.mkdir(parents=True)
        with closing(sqlite3.connect(self.database)) as live:
            live.execute("PRAGMA journal_mode=WAL")
            live.execute("CREATE TABLE messages (content TEXT)")
            live.execute("INSERT INTO messages VALUES ('existing chat')")
            live.commit()
            result = self.restore(True)
            backup = Path(result["backup"])
            with closing(sqlite3.connect(backup / "octop.db")) as saved:
                self.assertEqual(
                    saved.execute("SELECT content FROM messages").fetchall(), [("existing chat",)]
                )
            live.execute("INSERT INTO messages VALUES ('new chat after installation')")
            live.commit()
            preview = recovery.rollback(self.packages, backup)
            self.assertEqual(preview["mode"], "check-rollback")
            self.assertEqual(self.before.read_bytes(), b"reviewed customization")
            result = recovery.rollback(self.packages, backup, apply=True)
            self.assertFalse(result["database_restored"])
            self.assertEqual(live.execute("SELECT count(*) FROM messages").fetchone()[0], 2)
        self.assertEqual(self.before.read_bytes(), b"original program")
        self.assertFalse((self.packages / recovery.MARKER).exists())

    def test_rollback_refuses_drift_before_changing_any_program(self):
        result = self.restore(True)
        self.before.write_bytes(b"later independent program edit")
        with self.assertRaisesRegex(ValueError, "changed since"):
            recovery.rollback(self.packages, Path(result["backup"]), apply=True)
        self.assertEqual(self.before.read_bytes(), b"later independent program edit")
        self.assertTrue((self.packages / "octop_harness" / "new.py").exists())

    def test_default_packages_prefers_independent_custom_runtime(self):
        official = self.home / ".octop" / "portable" / "packages"
        self.assertEqual(recovery.default_packages(self.home), official)
        custom = self.home / ".octop" / "custom-runtime" / "portable" / "packages"
        custom.mkdir(parents=True)
        self.assertEqual(recovery.default_packages(self.home), custom)


if __name__ == "__main__":
    unittest.main()
