"""Small, offline integrity tests for the stdlib-only custom portable builder."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

SPEC = importlib.util.spec_from_file_location(
    "build_portable", Path(__file__).with_name("build_portable.py")
)
assert SPEC and SPEC.loader
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def macho(arm: bool = True) -> bytes:
    return b"\xcf\xfa\xed\xfe" + struct.pack("<I", 0x0100000C if arm else 0x01000007) + bytes(24)


def pe(machine: int = 0x8664) -> bytes:
    binary = bytearray(128)
    binary[:2] = b"MZ"
    struct.pack_into("<I", binary, 0x3C, 64)
    binary[64:68] = b"PE\0\0"
    struct.pack_into("<H", binary, 68, machine)
    return bytes(binary)


class PortableBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.overlay = self.root / "customization" / "packages"
        for name in builder.PACKAGE_NAMES:
            package = self.overlay / name
            package.mkdir(parents=True)
            (package / "__init__.py").write_text(f'PACKAGE = "{name}"\n', encoding="utf-8")
        self.platform = "darwin-arm64"
        self.source = self.root / "official.zip"
        self.destination = self.root / "dist" / "custom.zip"

    def fixture(
        self,
        platform: str = "darwin-arm64",
        version: str = "1.0.2",
        binary: bytes | None = None,
        extra_name: str | None = None,
    ) -> dict:
        self.platform = platform
        root = f"Octop-{platform}"
        with zipfile.ZipFile(self.source, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.comment = b"original archive comment"
            archive.writestr(
                f"{root}/VERSION.txt", f"platform={platform}\noctop_version={version}\n"
            )
            archive.writestr(
                f"{root}/launch.py",
                'import os\nimport runpy\n\ndef main() -> None:\n    runpy.run_module("octop", run_name="__main__")\n'.replace(
                    "\n", "\r\n" if platform == "windows-amd64" else "\n"
                ),
            )
            launcher = zipfile.ZipInfo(f"{root}/start.sh", date_time=(2026, 1, 2, 3, 4, 6))
            launcher.create_system = 3
            launcher.external_attr = (stat.S_IFREG | 0o755) << 16
            launcher.extra = b"\xfe\xca\x02\x00OK"
            launcher.comment = b"executable metadata"
            archive.writestr(launcher, b"#!/bin/sh\necho launch\n")
            if platform.startswith("darwin-"):
                python_name = f"{root}/runtime/bin/python3.12"
                archive.writestr(python_name, binary or macho(platform.endswith("arm64")))
                symlink = zipfile.ZipInfo(f"{root}/runtime/bin/python3")
                symlink.create_system = 3
                symlink.external_attr = (stat.S_IFLNK | 0o755) << 16
                archive.writestr(symlink, "python3.12")
            else:
                archive.writestr(f"{root}/runtime/python.exe", binary or pe())
            archive.writestr(f"{root}/packages/dependency/native.so", b"original native dependency")
            for package in builder.PACKAGE_NAMES:
                archive.writestr(f"{root}/packages/{package}/", b"")
                archive.writestr(f"{root}/packages/{package}/old.py", b"obsolete upstream code")
                archive.writestr(f"{root}/packages/{package}/__pycache__/old.pyc", b"old bytecode")
            if extra_name:
                archive.writestr(extra_name, "invalid path")
        return {
            "upstream_version": "1.0.2",
            "custom_version": "1.0.2.post20261102",
            "upstream_commit": "upstream-commit",
            "assets": {
                platform: {
                    "size": self.source.stat().st_size,
                    "sha256": builder.sha256_file(self.source),
                }
            },
        }

    def build(self, lock: dict) -> dict:
        return builder.build_archive(
            self.source, self.destination, self.platform, self.overlay, lock, "custom-commit"
        )

    def test_full_overlay_metadata_symlinks_and_no_user_data(self) -> None:
        lock = self.fixture()
        package = self.overlay / "octop"
        (package / "dashboard" / "archive-v1").mkdir(parents=True)
        archived = package / "dashboard" / "archive-v1" / "old-assets.js"
        archived.write_bytes(b"retain old dashboard assets")
        (package / "__pycache__").mkdir()
        (package / "__pycache__" / "init.pyc").write_bytes(b"cache")
        (package / "ignored.pyc").write_bytes(b"bytecode")
        (package / ".DS_Store").write_bytes(b"macOS metadata")
        personal = self.root / ".octop"
        personal.mkdir()
        (personal / "config.json").write_text('{"secret":"must not ship"}', encoding="utf-8")
        unrelated = self.overlay / "userdata"
        unrelated.mkdir()
        (unrelated / "database.sqlite").write_bytes(b"private data")
        report = self.build(lock)
        root = f"Octop-{self.platform}"
        with zipfile.ZipFile(self.destination) as result, zipfile.ZipFile(self.source) as original:
            names = result.namelist()
            self.assertEqual(result.comment, original.comment)
            self.assertIsNone(result.testzip())
            self.assertFalse(any("old.py" in name or "__pycache__" in name for name in names))
            self.assertFalse(any(".pyc" in name or ".DS_Store" in name for name in names))
            self.assertFalse(any("userdata" in name or "config.json" in name for name in names))
            self.assertEqual(
                result.read(f"{root}/packages/octop/dashboard/archive-v1/old-assets.js"),
                archived.read_bytes(),
            )
            self.assertEqual(result.read(f"{root}/runtime/bin/python3"), b"python3.12")
            for member in ("start.sh", "runtime/bin/python3", "packages/dependency/native.so"):
                before = original.getinfo(f"{root}/{member}")
                after = result.getinfo(f"{root}/{member}")
                self.assertEqual(result.read(after), original.read(before))
                for attribute in (
                    "external_attr",
                    "create_system",
                    "date_time",
                    "extra",
                    "comment",
                ):
                    self.assertEqual(getattr(after, attribute), getattr(before, attribute))
            version = result.read(f"{root}/VERSION.txt").decode()
            self.assertIn("octop_version=1.0.2.post20261102", version)
            launch = result.read(f"{root}/launch.py")
            expected_launch = original.read(f"{root}/launch.py").replace(
                b"def main() -> None:\n",
                b'def main() -> None:\n    os.environ["OCTOP_CUSTOM_BUILD"] = "1"\n',
            )
            self.assertEqual(launch, expected_launch)
            manifest_data = result.read(f"{root}/custom-release-manifest.json")
            manifest = json.loads(manifest_data)
            marker = json.loads(result.read(f"{root}/packages/octop-custom-release.json"))
            self.assertEqual(marker["manifest_sha256"], hashlib.sha256(manifest_data).hexdigest())
            self.assertEqual(manifest["git_commit"], "custom-commit")
            self.assertEqual(len(manifest["package_file_sha256"]), 4)
            for name, digest in manifest["package_file_sha256"].items():
                self.assertEqual(hashlib.sha256(result.read(f"{root}/{name}")).hexdigest(), digest)
        self.assertEqual(report["sha256"], builder.sha256_file(self.destination))
        self.assertEqual(report["verification"]["overlay_files_verified"], 4)
        self.assertEqual(json.loads(self.destination.with_suffix(".json").read_text()), report)

    def test_sha256_mismatch_refuses_build(self) -> None:
        lock = self.fixture()
        lock["assets"][self.platform]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
            self.build(lock)
        self.assertFalse(self.destination.exists())

    def test_size_mismatch_refuses_build(self) -> None:
        lock = self.fixture()
        lock["assets"][self.platform]["size"] += 1
        with self.assertRaisesRegex(ValueError, "size mismatch"):
            self.build(lock)

    def test_rejects_unsafe_paths(self) -> None:
        for name in (
            "../root/file",
            "/root/file",
            "root/../file",
            "root//file",
            "root/./file",
            "root\\file",
            "root/C:/file",
            "other/file",
        ):
            with self.subTest(name=name), self.assertRaises(ValueError):
                builder.safe_archive_name(name, "root")
        self.assertEqual(builder.safe_archive_name("root/directory/", "root"), "root/directory/")

    def test_unsafe_official_zip_member_refuses_build(self) -> None:
        lock = self.fixture(extra_name="Octop-darwin-arm64/../escape")
        with self.assertRaisesRegex(ValueError, "Unsafe archive member"):
            self.build(lock)

    def test_version_mismatch_refuses_build(self) -> None:
        lock = self.fixture(version="1.0.1")
        with self.assertRaisesRegex(ValueError, "VERSION.txt"):
            self.build(lock)

    def test_runtime_architecture_mismatch_refuses_build(self) -> None:
        lock = self.fixture(binary=macho(arm=False))
        with self.assertRaisesRegex(ValueError, "architecture mismatch"):
            self.build(lock)

    def test_all_platform_architectures(self) -> None:
        for platform, binary in (
            ("darwin-arm64", macho()),
            ("darwin-amd64", macho(False)),
            ("windows-amd64", pe()),
        ):
            with self.subTest(platform=platform):
                self.assertEqual(builder.binary_architecture(binary), platform)
                lock = self.fixture(platform=platform)
                report = self.build(lock)
                self.assertEqual(report["verification"]["runtime_architecture"], platform)
                with zipfile.ZipFile(self.destination) as result:
                    launch = result.read(f"Octop-{platform}/launch.py")
                    newline = b"\r\n" if platform == "windows-amd64" else b"\n"
                    self.assertIn(b'    os.environ["OCTOP_CUSTOM_BUILD"] = "1"' + newline, launch)
                    if platform == "windows-amd64":
                        self.assertNotIn(b"\n", launch.replace(b"\r\n", b""))

    def test_launch_guard_preserves_newlines_and_runs_before_bootstrap(self) -> None:
        source = (
            "import os\n"
            "def _bootstrap():\n"
            '    assert os.environ["OCTOP_CUSTOM_BUILD"] == "1"\n'
            "def main() -> None:\n"
            "    _bootstrap()\n"
        )
        for newline in (b"\n", b"\r\n"):
            with self.subTest(newline=newline):
                original = source.encode().replace(b"\n", newline)
                patched = builder.custom_launch(original)
                injection = b'    os.environ["OCTOP_CUSTOM_BUILD"] = "1"' + newline
                self.assertEqual(patched.replace(injection, b"", 1), original)
                namespace: dict = {}
                exec(compile(patched, "launch.py", "exec"), namespace)
                with mock.patch.dict(os.environ, {"OCTOP_CUSTOM_BUILD": "0"}):
                    namespace["main"]()
                    self.assertEqual(os.environ["OCTOP_CUSTOM_BUILD"], "1")

    def test_unknown_architectures_refused(self) -> None:
        for binary in (b"not a binary", pe(0xAA64), pe()[:40], b"\xcf\xfa\xed\xfe" + bytes(20)):
            with self.subTest(binary=binary[:8]), self.assertRaises(ValueError):
                builder.binary_architecture(binary)

    def test_launch_patch_refuses_changed_upstream_layout(self) -> None:
        with self.assertRaisesRegex(ValueError, "layout changed"):
            builder.custom_launch(b"# unexpected new upstream entrypoint")

    def test_package_directory_required(self) -> None:
        (self.overlay / "octop" / "__init__.py").unlink()
        with self.assertRaisesRegex(ValueError, "Incomplete custom package"):
            builder.collect_overlay(self.overlay)


if __name__ == "__main__":
    unittest.main()
