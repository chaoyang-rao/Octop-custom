"""An in-place upgrade must retain identity without reverting new program fields."""

import importlib.util
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "prepare_macos_identity", Path(__file__).with_name("prepare_macos_identity.py")
)
assert SPEC and SPEC.loader
identity = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(identity)


class MacIdentityTests(unittest.TestCase):
    def test_existing_identity_and_new_executable_version_are_kept(self):
        old = {
            "CFBundleIdentifier": "com.tencent.octop",
            "CFBundleName": "Octop",
            "CFBundleExecutable": "Octop",
            "CFBundleVersion": "old",
        }
        new = {
            "CFBundleIdentifier": "com.chaoyangrao.octopcustom",
            "CFBundleName": "OctopCustom",
            "CFBundleExecutable": "OctopCustom",
            "CFBundleVersion": "new",
            "NSMicrophoneUsageDescription": "voice input",
        }
        result = identity.update_identity(new, old)
        self.assertEqual(result["CFBundleIdentifier"], old["CFBundleIdentifier"])
        self.assertEqual(result["CFBundleName"], old["CFBundleName"])
        self.assertEqual(result["CFBundleExecutable"], new["CFBundleExecutable"])
        self.assertEqual(result["CFBundleVersion"], "new")
        self.assertEqual(result["NSMicrophoneUsageDescription"], "voice input")
        self.assertEqual(new["CFBundleIdentifier"], "com.chaoyangrao.octopcustom")

    def test_missing_identity_is_refused(self):
        with self.assertRaises(ValueError):
            identity.update_identity({"CFBundleExecutable": "new"}, {})


if __name__ == "__main__":
    unittest.main()
