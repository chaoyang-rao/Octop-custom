"""Freeze safety checks using synthetic files; never touch a live Octop home."""

import hashlib
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


source_freeze = load_script("sync_octop_source")
dashboard_freeze = load_script("sync_dashboard")
posix_only = unittest.skipUnless(os.name == "posix", "symlink fixtures require POSIX")


class SourcePathSafetyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "src/octop"
        self.target = self.root / "customization/packages/octop"
        self.source.mkdir(parents=True)
        self.target.mkdir(parents=True)
        lock = self.root / "scripts/custom/upstream-lock.json"
        lock.parent.mkdir(parents=True)
        lock.write_text(json.dumps({"custom_version": "test-release"}))
        self.manifest({})

    def manifest(self, rows):
        path = self.root / "customization/tracked-program-manifest.json"
        path.write_text(
            json.dumps(
                {
                    "files": [
                        {"path": "octop/" + name, "sha256": hashlib.sha256(data).hexdigest()}
                        for name, data in rows.items()
                    ]
                }
            )
        )

    @posix_only
    def test_internal_skill_directory_alias_is_dereferenced_to_ordinary_files(self):
        skill = self.source / "builtin/skills/shared/skills/shared"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("packaged skill")
        alias = self.source / "builtin/skills/cluster/skills/shared"
        alias.parent.mkdir(parents=True)
        alias.symlink_to("../../shared/skills/shared", target_is_directory=True)
        (self.source / "dashboard").mkdir()
        (self.source / "dashboard/index.html").write_text("separate frontend build")

        result = source_freeze.sync(self.root, apply=True)

        self.assertEqual(result, {"source_files": 2, "changed": 2, "obsolete": 0})
        for relative in (
            "builtin/skills/shared/skills/shared/SKILL.md",
            "builtin/skills/cluster/skills/shared/SKILL.md",
        ):
            self.assertEqual((self.target / relative).read_text(), "packaged skill")
            self.assertFalse((self.target / relative).is_symlink())
        self.assertFalse((self.target / alias.relative_to(self.source)).is_symlink())
        self.assertFalse((self.target / "dashboard").exists())

    @posix_only
    def test_source_alias_escape_is_refused_before_copy(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "program.py").write_text("outside program")
        (self.source / "alias").symlink_to(outside, target_is_directory=True)
        (self.source / "new.py").write_text("new program")

        with self.assertRaisesRegex(ValueError, "escapes"):
            source_freeze.sync(self.root, apply=True)

        self.assertEqual(list(self.target.iterdir()), [])
        self.assertEqual((outside / "program.py").read_text(), "outside program")

    @posix_only
    def test_source_directory_cycle_is_refused_before_copy(self):
        folder = self.source / "package"
        folder.mkdir()
        (folder / "loop").symlink_to(self.source, target_is_directory=True)
        (self.source / "new.py").write_text("new program")

        with self.assertRaisesRegex(ValueError, "cycle"):
            source_freeze.sync(self.root, apply=True)

        self.assertEqual(list(self.target.iterdir()), [])

    @posix_only
    def test_target_root_symlink_cannot_redirect_a_managed_write(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "program.py").write_bytes(b"old program")
        (self.source / "program.py").write_bytes(b"new program")
        self.manifest({"program.py": b"old program"})
        self.target.rmdir()
        self.target.symlink_to(outside, target_is_directory=True)

        with self.assertRaisesRegex(ValueError, "symlink|escape"):
            source_freeze.sync(self.root, apply=True)

        self.assertEqual((outside / "program.py").read_bytes(), b"old program")

    @posix_only
    def test_target_parent_symlink_cannot_redirect_a_managed_write(self):
        outside = self.root / "outside"
        (outside / "octop").mkdir(parents=True)
        (outside / "octop/program.py").write_bytes(b"old program")
        (self.source / "program.py").write_bytes(b"new program")
        self.manifest({"program.py": b"old program"})
        self.target.rmdir()
        self.target.parent.rmdir()
        self.target.parent.symlink_to(outside, target_is_directory=True)

        with self.assertRaisesRegex(ValueError, "symlink|escape"):
            source_freeze.sync(self.root, apply=True)

        self.assertEqual((outside / "octop/program.py").read_bytes(), b"old program")

    @posix_only
    def test_private_target_cannot_be_reintroduced_through_a_harmless_alias(self):
        dashboard = self.source / "dashboard"
        dashboard.mkdir()
        (dashboard / ".env").write_text("synthetic private marker")
        (self.source / "safe.py").symlink_to("dashboard/.env")

        with self.assertRaisesRegex(ValueError, "Private|excluded|symlink"):
            source_freeze.sync(self.root, apply=True)

        self.assertEqual(list(self.target.iterdir()), [])


class DashboardAssetSafetyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.dashboard = self.root / "dashboard"
        (self.dashboard / "assets").mkdir(parents=True)
        self.index = self.dashboard / "index.html"
        self.main = self.dashboard / "assets/app-12345678.js"
        self.index.write_text('<script type="module" src="/assets/app-12345678.js"></script>')
        self.main.write_text("export {};")

    def test_complete_local_graph_and_external_resources_are_accepted(self):
        self.main.write_text(
            'import { value } from "./shared-12345678.js"; '
            'import("./lazy-12345678.js"); console.log(value);'
        )
        (self.dashboard / "assets/shared-12345678.js").write_text("export const value = 1;")
        (self.dashboard / "assets/lazy-12345678.js").write_text("export {};")
        (self.dashboard / "assets/style-12345678.css").write_text(
            'body { background: url("./photo.png"); } '
            '.external { background: url("https://example.com/photo.png"); } '
            '.inline { background: url("data:image/png;base64,AAAA"); }'
        )
        (self.dashboard / "assets/photo.png").write_bytes(b"synthetic image")
        self.index.write_text(
            self.index.read_text() + '<link rel="stylesheet" href="/assets/style-12345678.css">'
        )

        result = dashboard_freeze.verify(self.dashboard)

        self.assertEqual(len(result), 6)
        self.assertEqual(result["assets/photo.png"], hashlib.sha256(b"synthetic image").hexdigest())

    def test_missing_html_resource_is_refused(self):
        self.main.unlink()
        with self.assertRaisesRegex(ValueError, "Missing local dashboard resource"):
            dashboard_freeze.verify(self.dashboard)

    def test_missing_named_import_is_refused(self):
        self.main.write_text('import { value } from "./missing-12345678.js";')
        with self.assertRaisesRegex(ValueError, "Missing local dashboard resource"):
            dashboard_freeze.verify(self.dashboard)

    def test_missing_dynamic_import_is_refused(self):
        self.main.write_text('import("./missing-12345678.js");')
        with self.assertRaisesRegex(ValueError, "Missing local dashboard resource"):
            dashboard_freeze.verify(self.dashboard)

    def test_missing_side_effect_import_is_refused(self):
        self.main.write_text('import "./missing-12345678.js";')
        with self.assertRaisesRegex(ValueError, "Missing local dashboard resource"):
            dashboard_freeze.verify(self.dashboard)

    def test_parent_relative_module_escape_is_refused(self):
        (self.root / "outside-12345678.js").write_text("export {};")
        self.main.write_text('import("../../outside-12345678.js");')
        with self.assertRaisesRegex(ValueError, "Missing local dashboard resource|escape"):
            dashboard_freeze.verify(self.dashboard)

    def test_missing_css_resource_is_refused(self):
        (self.dashboard / "assets/style-12345678.css").write_text(
            'body { background: url("./missing.png"); }'
        )
        with self.assertRaisesRegex(ValueError, "Missing local dashboard resource"):
            dashboard_freeze.verify(self.dashboard)

    def test_url_encoded_local_escape_is_refused(self):
        (self.root / "outside.png").write_bytes(b"outside image")
        (self.dashboard / "assets/style-12345678.css").write_text(
            'body { background: url("%2e%2e/%2e%2e/outside.png"); }'
        )
        with self.assertRaisesRegex(ValueError, "Missing local dashboard resource|escape"):
            dashboard_freeze.verify(self.dashboard)

    @posix_only
    def test_unreferenced_external_file_symlink_is_refused(self):
        outside = self.root / "outside.txt"
        outside.write_text("outside marker")
        (self.dashboard / "unreferenced.txt").symlink_to(outside)

        with self.assertRaisesRegex(ValueError, "symlink|escape"):
            dashboard_freeze.verify(self.dashboard)

    @posix_only
    def test_unreferenced_external_directory_symlink_is_refused(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "unreferenced.txt").write_text("outside marker")
        (self.dashboard / "unreferenced").symlink_to(outside, target_is_directory=True)

        with self.assertRaisesRegex(ValueError, "symlink|escape"):
            dashboard_freeze.verify(self.dashboard)


if __name__ == "__main__":
    unittest.main()
