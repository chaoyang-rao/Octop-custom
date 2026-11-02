"""The source freeze must not discard independent program edits or runtime data."""

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "sync_octop_source", Path(__file__).with_name("sync_octop_source.py")
)
assert SPEC and SPEC.loader
freeze = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(freeze)


class SourceFreezeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = self.root / "customization/packages/octop"
        self.target.mkdir(parents=True)
        (self.root / "src/octop").mkdir(parents=True)

    def manifest(self, rows):
        (self.root / "customization/tracked-program-manifest.json").write_text(
            json.dumps(
                {
                    "files": [
                        {"path": "octop/" + name, "sha256": hashlib.sha256(data).hexdigest()}
                        for name, data in rows.items()
                    ]
                }
            )
        )

    def test_unknown_edit_refuses_before_any_copy(self):
        (self.target / "program.py").write_bytes(b"independent edit")
        self.manifest({"program.py": b"previous managed source"})
        with (
            patch.object(
                freeze, "source_files", return_value={"program.py": b"new source", "new.py": b"new"}
            ),
            self.assertRaisesRegex(ValueError, "Independent"),
        ):
            freeze.sync(self.root, apply=True)
        self.assertEqual((self.target / "program.py").read_bytes(), b"independent edit")
        self.assertFalse((self.target / "new.py").exists())

    def test_checked_rebuild_removes_only_obsolete_backend_programs(self):
        (self.target / "old.py").write_bytes(b"old")
        for area in ("dashboard", "_vendor"):
            (self.target / area).mkdir()
            (self.target / area / "preserved").write_bytes(b"keep")
        (self.root / "src/octop/new.py").write_bytes(b"new")
        self.manifest({"old.py": b"old"})
        with patch.object(freeze, "source_files", return_value={"new.py": b"new"}):
            preview = freeze.sync(self.root, apply=False)
            self.assertEqual(preview, {"source_files": 1, "changed": 1, "obsolete": 1})
            self.assertTrue((self.target / "old.py").exists())
            freeze.sync(self.root, apply=True)
            self.assertEqual(freeze.sync(self.root, apply=False)["changed"], 0)
        self.assertFalse((self.target / "old.py").exists())
        self.assertEqual((self.target / "new.py").read_bytes(), b"new")
        for area in ("dashboard", "_vendor"):
            self.assertEqual((self.target / area / "preserved").read_bytes(), b"keep")


if __name__ == "__main__":
    unittest.main()
