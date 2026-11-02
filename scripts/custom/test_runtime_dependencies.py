"""Offline checks for locked wheel provenance, native compatibility and ZIP safety."""

from __future__ import annotations

import base64
import csv
import hashlib
import importlib.util
import io
import json
import stat
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "runtime_dependencies", Path(__file__).with_name("runtime_dependencies.py")
)
assert SPEC and SPEC.loader
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)


def macho(cpu=0x01000007, minimum=(10, 13, 0)):
    version = (minimum[0] << 16) | (minimum[1] << 8) | minimum[2]
    return struct.pack("<8I", 0xFEEDFACF, cpu, 3, 6, 1, 24, 0, 0) + struct.pack(
        "<6I", 0x32, 24, 1, version, 0x000E0000, 0
    )


class RuntimeDependencyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def fixture(self, *, extra=None, altered_record=False, native=None):
        tag = "cp311-abi3-macosx_10_9_universal2" if native else "py3-none-any"
        filename = f"webauthn-3.0.1-{tag}.whl"
        dist = "webauthn-3.0.1.dist-info"
        files = {
            "webauthn/__init__.py": b"VERSION = 'fixture'\n",
            f"{dist}/METADATA": b"Metadata-Version: 2.4\nName: webauthn\nVersion: 3.0.1\nLicense-File: LICENSE\nRequires-Dist: cryptography>=49.0.0\n\nFixture metadata\n",
            f"{dist}/WHEEL": f"Wheel-Version: 1.0\nTag: {tag}\n".encode(),
            f"{dist}/licenses/LICENSE": b"fixture license must survive",
        }
        if native:
            files["webauthn/_fixture.abi3.so"] = native
        records = io.StringIO()
        writer = csv.writer(records)
        for name, data in files.items():
            digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
            writer.writerow([name, "sha256=" + digest, len(data)])
        writer.writerow([f"{dist}/RECORD", "", ""])
        files[f"{dist}/RECORD"] = records.getvalue().encode()
        if altered_record:
            files["webauthn/__init__.py"] = b"changed without updating RECORD"
        path = self.root / filename
        with zipfile.ZipFile(path, "w") as archive:
            for name, data in files.items():
                archive.writestr(name, data)
            if extra:
                name, data, mode = extra
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = mode << 16
                archive.writestr(info, data)
        row = {
            "name": "webauthn",
            "version": "3.0.1",
            "filename": filename,
            "url": "https://files.pythonhosted.org/packages/aa/bb/" + "c" * 60 + "/" + filename,
            "metadata_url": "https://pypi.org/pypi/webauthn/3.0.1/json",
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size": path.stat().st_size,
            "tag": tag,
            "modules": ["webauthn"],
        }
        return path, row

    def test_locked_cached_wheel_preserves_license_and_provenance(self):
        path, row = self.fixture()
        with patch.object(
            runtime.urllib.request, "build_opener", side_effect=AssertionError("offline")
        ):
            self.assertEqual(runtime.obtain_wheel(row, self.root), path)
            files, provenance = runtime.wheel_files(path, row, "darwin-amd64")
        self.assertEqual(
            files["webauthn-3.0.1.dist-info/licenses/LICENSE"], b"fixture license must survive"
        )
        self.assertEqual(provenance["sha256"], row["sha256"])
        self.assertEqual(provenance["native_macos_targets"], {})

    def test_official_host_and_exact_download_url_are_required(self):
        _, row = self.fixture()
        for url in (
            row["url"].replace("https:", "http:"),
            row["url"].replace("files.pythonhosted.org", "files.pythonhosted.org.invalid"),
            row["url"].replace("files.pythonhosted.org", "user@files.pythonhosted.org"),
            row["url"] + "?source=unreviewed",
            row["url"].replace("/packages/", "/packages/../"),
        ):
            with self.subTest(url=url), self.assertRaisesRegex(ValueError, "official PyPI"):
                runtime.obtain_wheel({**row, "url": url}, self.root)

    def test_corrupted_cache_is_rejected_without_downloading(self):
        path, row = self.fixture()
        data = path.read_bytes()
        path.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
        with patch.object(
            runtime.urllib.request, "build_opener", side_effect=AssertionError("offline")
        ), self.assertRaisesRegex(ValueError, "SHA256"):
            runtime.obtain_wheel(row, self.root)

    def test_zip_escape_absolute_path_symlink_and_unexpected_modules_are_refused(self):
        for name, mode in (
            ("../escape", stat.S_IFREG | 0o644),
            ("/webauthn/escape", stat.S_IFREG | 0o644),
            ("webauthn/../escape", stat.S_IFREG | 0o644),
            ("webauthn/link", stat.S_IFLNK | 0o777),
            ("other_package/__init__.py", stat.S_IFREG | 0o644),
        ):
            with self.subTest(name=name):
                path, row = self.fixture(extra=(name, b"outside", mode))
                with self.assertRaisesRegex(ValueError, "Unsafe wheel|Unexpected wheel"):
                    runtime.wheel_files(path, row, "darwin-amd64")

    def test_record_digest_mismatch_is_rejected_even_with_matching_wheel_hash(self):
        path, row = self.fixture(altered_record=True)
        with self.assertRaisesRegex(ValueError, "RECORD hash"):
            runtime.wheel_files(path, row, "darwin-amd64")

    def test_native_intel_minimum_macos_is_checked_from_the_binary(self):
        path, row = self.fixture(native=macho())
        _, provenance = runtime.wheel_files(path, row, "darwin-amd64")
        self.assertEqual(
            provenance["native_macos_targets"]["webauthn/_fixture.abi3.so"], {"x86_64": "10.13.0"}
        )
        for binary in (macho(minimum=(13, 0, 0)), macho(cpu=0x0100000C, minimum=(11, 0, 0))):
            with self.subTest(binary=binary):
                path, row = self.fixture(native=binary)
                with self.assertRaisesRegex(ValueError, "unsupported Intel macOS"):
                    runtime.wheel_files(path, row, "darwin-amd64")

    def test_other_platforms_do_not_download_or_replace_dependencies(self):
        _, row = self.fixture()
        lock = self.root / "lock.json"
        lock.write_text(
            json.dumps(
                {"schema_version": 1, "reason": "fixture", "platforms": {"darwin-amd64": [row]}}
            )
        )
        for platform in ("darwin-arm64", "windows-amd64"):
            with (
                self.subTest(platform=platform),
                patch.object(runtime, "obtain_wheel", side_effect=AssertionError("offline")),
            ):
                overlay = runtime.prepare(platform, self.root, lock_path=lock)
                self.assertFalse(overlay.files)
                self.assertFalse(overlay.replaces("packages/webauthn/__init__.py"))
                self.assertEqual(overlay.provenance["wheels"], [])

    def test_replacements_are_limited_to_exact_modules_and_old_distribution_metadata(self):
        overlay = runtime.RuntimeDependencyOverlay()
        overlay.modules.add("OpenSSL")
        overlay.distributions.add("pyopenssl")
        for name in ("packages/OpenSSL/crypto.py", "packages/pyopenssl-26.3.0.dist-info/METADATA"):
            self.assertTrue(overlay.replaces(name), name)
        for name in (
            "packages/other/crypto.py",
            "packages/OpenSSL_extra/crypto.py",
            "runtime/OpenSSL/crypto.py",
            "packages/pyopenssl-26.3.0.data/file",
        ):
            self.assertFalse(overlay.replaces(name), name)

    def test_reviewed_metadata_adjustment_preserves_code_and_updates_record(self):
        path, row = self.fixture()
        original_wheel = path.read_bytes()
        row["requires_dist_overrides"] = {"cryptography>=49.0.0": ["cryptography>=48.0.1,<49"]}

        files, provenance = runtime.wheel_files(path, row, "darwin-amd64")

        metadata_name = "webauthn-3.0.1.dist-info/METADATA"
        with zipfile.ZipFile(path) as archive:
            self.assertEqual(files["webauthn/__init__.py"], archive.read("webauthn/__init__.py"))
            self.assertEqual(
                provenance["metadata_adjustment"]["original_sha256"],
                hashlib.sha256(archive.read(metadata_name)).hexdigest(),
            )
        self.assertIn(b"Requires-Dist: cryptography>=48.0.1,<49\n", files[metadata_name])
        self.assertEqual(
            provenance["metadata_adjustment"]["sha256"],
            hashlib.sha256(files[metadata_name]).hexdigest(),
        )
        records = list(csv.reader(io.StringIO(files["webauthn-3.0.1.dist-info/RECORD"].decode())))
        record = next(row for row in records if row[0] == metadata_name)
        digest = (
            base64.urlsafe_b64encode(hashlib.sha256(files[metadata_name]).digest())
            .rstrip(b"=")
            .decode()
        )
        self.assertEqual(record[1:], ["sha256=" + digest, str(len(files[metadata_name]))])
        self.assertEqual(path.read_bytes(), original_wheel)

    def test_metadata_change_refuses_unreviewed_upstream_requirement(self):
        path, row = self.fixture()
        row["requires_dist_overrides"] = {"cryptography>=48.0.0": ["cryptography>=48.0.1,<49"]}
        with self.assertRaisesRegex(ValueError, "Review changed upstream metadata"):
            runtime.wheel_files(path, row, "darwin-amd64")

    def test_portable_overlay_removes_old_modules_without_duplicate_zip_members(self):
        spec = importlib.util.spec_from_file_location(
            "fixture_builder", Path(__file__).with_name("build_portable.py")
        )
        assert spec and spec.loader
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        path, row = self.fixture()
        data, provenance = runtime.wheel_files(path, row, "darwin-amd64")
        overlay = runtime.RuntimeDependencyOverlay()
        overlay.files = {"packages/" + name: content for name, content in data.items()}
        overlay.modules.add("webauthn")
        overlay.distributions.add("webauthn")
        overlay.provenance["wheels"].append(provenance)
        source = self.root / "official.zip"
        prefix = "Octop-darwin-amd64/"
        with zipfile.ZipFile(source, "w") as archive:
            for name, content in {
                "VERSION.txt": b"platform=darwin-amd64\noctop_version=1.0.3b2\n",
                "launch.py": b"import os\ndef main() -> None:\n    pass\n",
                "runtime/bin/python3": macho(),
                "packages/webauthn/obsolete.py": b"remove old module",
                "packages/webauthn/__init__.py": b"replace old code",
                "packages/webauthn-2.7.1.dist-info/METADATA": b"remove old metadata",
                "packages/unrelated/native.so": b"retain unrelated binary",
            }.items():
                archive.writestr(prefix + name, content)
        custom = self.root / "custom"
        for name in builder.PACKAGE_NAMES:
            (custom / name).mkdir(parents=True)
            (custom / name / "__init__.py").write_text("# fixture\n")
        lock = {
            "upstream_version": "1.0.3b2",
            "custom_version": "test-custom",
            "upstream_commit": "fixture",
            "assets": {
                "darwin-amd64": {
                    "size": source.stat().st_size,
                    "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                }
            },
        }
        destination = self.root / "custom.zip"

        report = builder.build_archive(
            source, destination, "darwin-amd64", custom, lock, "fixture", dependency_overlay=overlay
        )

        with zipfile.ZipFile(destination) as archive:
            self.assertEqual(len(archive.namelist()), len(set(archive.namelist())))
            self.assertNotIn(prefix + "packages/webauthn/obsolete.py", archive.namelist())
            self.assertFalse(any("webauthn-2.7.1.dist-info" in name for name in archive.namelist()))
            self.assertEqual(
                archive.read(prefix + "packages/unrelated/native.so"), b"retain unrelated binary"
            )
            manifest = json.loads(archive.read(prefix + "custom-release-manifest.json"))
            for name, digest in manifest["runtime_dependency_file_sha256"].items():
                self.assertEqual(hashlib.sha256(archive.read(prefix + name)).hexdigest(), digest)
            self.assertEqual(
                archive.read(prefix + "packages/webauthn-3.0.1.dist-info/licenses/LICENSE"),
                b"fixture license must survive",
            )
            self.assertEqual(
                stat.S_IMODE(
                    archive.getinfo(prefix + "packages/webauthn/__init__.py").external_attr >> 16
                ),
                0o644,
            )
        self.assertEqual(report["verification"]["runtime_dependency_files_verified"], len(data))


if __name__ == "__main__":
    unittest.main()
