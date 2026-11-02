"""Protect the current graph and build inputs when pruning generated releases."""

import tempfile
import unittest
from pathlib import Path

from prune_assets import obsolete_assets, prune_assets


class PruneAssetsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dashboard = Path(self.temp.name)
        self.assets = self.dashboard / "assets"
        self.assets.mkdir()
        (self.dashboard / "index.html").write_text('<script src="/assets/main.avatars-v60.js"></script>')
        self.write("main.avatars-v60.js", 'import "./lazy.avatars-v60.js";')
        self.write("lazy.avatars-v60.js", "export const value=1;")
        self.manifest = {"release": "avatars-v60", "assets": ["main.avatars-v60.js"]}

    def write(self, name, content=""):
        (self.assets / name).write_text(content)

    def test_preview_and_apply_preserve_lazy_dependencies_and_build_inputs(self):
        self.write("main.avatars-v59.js")
        self.write("styles.0123456789.css")
        for name in ("expert-avatars.js", "source.css", "font.woff2", "image.png"):
            self.write(name)
        self.assertEqual(prune_assets(self.dashboard, self.manifest), 2)
        self.assertTrue((self.assets / "main.avatars-v59.js").exists())
        self.assertEqual(prune_assets(self.dashboard, self.manifest, apply=True), 2)
        self.assertEqual(prune_assets(self.dashboard, self.manifest, apply=True), 0)
        for name in ("main.avatars-v60.js", "lazy.avatars-v60.js", "expert-avatars.js", "source.css", "font.woff2", "image.png"):
            self.assertTrue((self.assets / name).exists(), name)

    def test_current_graph_old_release_reference_refuses_removal(self):
        self.write("lazy.avatars-v60.js", 'import "./old.avatars-v59.js";')
        self.write("old.avatars-v59.js")
        with self.assertRaisesRegex(ValueError, "old release"):
            prune_assets(self.dashboard, self.manifest, apply=True)
        self.assertTrue((self.assets / "old.avatars-v59.js").exists())

    def test_missing_lazy_asset_refuses_removal(self):
        (self.assets / "lazy.avatars-v60.js").unlink()
        with self.assertRaisesRegex(ValueError, "missing"):
            obsolete_assets(self.dashboard, self.manifest)

    def test_missing_manifest_asset_refuses_removal(self):
        self.manifest["assets"] = ["missing.avatars-v60.js"]
        with self.assertRaisesRegex(ValueError, "missing"):
            obsolete_assets(self.dashboard, self.manifest)

    def test_path_traversal_manifest_refuses_removal(self):
        self.manifest["assets"] = ["../outside.js"]
        with self.assertRaisesRegex(ValueError, "inside"):
            obsolete_assets(self.dashboard, self.manifest)

    def test_manifest_must_identify_a_nonempty_current_release(self):
        for manifest in ({"release": "", "assets": []}, {"release": "avatars-v60", "assets": []}, {"release": "avatars-v60", "assets": ["old.avatars-v59.js"]}):
            with self.subTest(manifest=manifest), self.assertRaises(ValueError):
                obsolete_assets(self.dashboard, manifest)


if __name__ == "__main__":
    unittest.main()
