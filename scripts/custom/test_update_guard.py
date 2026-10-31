"""Ensure custom builds cannot silently install the upstream package."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from octop.api.routers.health import health
from octop.infra.setup import self_update


class UpdateProtectionTests(unittest.TestCase):
    def test_custom_environment_stops_before_installer_or_version_probe(self):
        with patch.dict(os.environ, {"OCTOP_CUSTOM_BUILD": "1"}), patch.object(
            self_update, "get_local_version"
        ) as probe, patch.object(self_update, "_run_managed_upgrade") as install:
            result = self_update.run_upgrade(locale="zh")
        self.assertFalse(result.success)
        self.assertIn("定制版", result.error)
        probe.assert_not_called()
        install.assert_not_called()

    def test_marker_protects_even_when_environment_was_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            packages = Path(tmp)
            fake_source = packages / "octop/infra/setup/self_update.py"
            fake_source.parent.mkdir(parents=True)
            (packages / "octop-custom-release.json").write_text("{}")
            with patch.dict(os.environ, {"OCTOP_CUSTOM_BUILD": ""}), patch.object(
                self_update, "__file__", str(fake_source)
            ), patch.object(self_update, "get_local_version") as probe:
                result = self_update.run_upgrade(locale="en")
            self.assertFalse(result.success)
            self.assertIn("custom build", result.error)
            probe.assert_not_called()

    def test_health_marks_only_custom_processes(self):
        server = SimpleNamespace(
            database_bound=True, user_manager=None, app_runtime=None, _started_at=0
        )
        with patch.dict(os.environ, {"OCTOP_CUSTOM_BUILD": "1"}):
            self.assertEqual(
                asyncio.run(health(server))["custom_release"], "1.0.2.post20261101"
            )
        with patch.dict(os.environ, {"OCTOP_CUSTOM_BUILD": ""}):
            self.assertNotIn("custom_release", asyncio.run(health(server)))


if __name__ == "__main__":
    unittest.main()
