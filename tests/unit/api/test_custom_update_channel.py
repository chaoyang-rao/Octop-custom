"""Custom installations advertise their channel and reject official installers."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from octop.api.deps import current_user, get_server
from octop.api.routers import update
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.setup import self_update


def test_custom_marker_is_visible_without_environment_and_never_offers_pypi_install(
    tmp_path, monkeypatch
):
    source = tmp_path / "octop/infra/setup/self_update.py"
    source.parent.mkdir(parents=True)
    marker = {"custom_version": "1.0.3b3.post20261106", "upstream_version": "1.0.3b3"}
    (tmp_path / "octop-custom-release.json").write_text(json.dumps(marker))
    monkeypatch.setattr(self_update, "__file__", str(source))
    monkeypatch.delenv("OCTOP_CUSTOM_BUILD", raising=False)
    monkeypatch.setattr(update, "get_local_version", lambda: "1.0.3b3")
    result = update._present_status(
        {"current_version": "1.0.3b3", "latest_any": "1.0.3b4"},
        stable_only=False,
        include_prerelease=True,
    )
    assert result["custom_build"] is True
    assert result["custom_version"] == marker["custom_version"]
    assert result["official_latest_version"] == "1.0.3b4"
    assert result["official_has_update"] is True
    assert result["has_update"] is False
    assert result["in_place_upgrade_allowed"] is False
    assert result["custom_repository_url"] == "https://github.com/chaoyang-rao/Octop-custom"


def test_custom_upgrade_stops_before_any_version_probe_or_install(monkeypatch):
    monkeypatch.setenv("OCTOP_CUSTOM_BUILD", "1")
    probe, install = Mock(), Mock()
    monkeypatch.setattr(self_update, "get_local_version", probe)
    monkeypatch.setattr(self_update, "_run_managed_upgrade", install)
    result = self_update.run_upgrade(locale="zh")
    assert not result.success and "定制版" in result.error
    probe.assert_not_called()
    install.assert_not_called()


def test_custom_http_upgrade_rejects_before_task_or_network(monkeypatch):
    monkeypatch.setenv("OCTOP_CUSTOM_BUILD", "1")
    probe, create = Mock(), Mock()
    monkeypatch.setattr(update, "fetch_pypi_info", probe)
    monkeypatch.setattr(update, "create_task", create)
    app = FastAPI()
    app.include_router(update.router, prefix="/api")
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(id=1, is_admin=True)
    app.dependency_overrides[get_server] = lambda: SimpleNamespace()

    @app.exception_handler(OctopError)
    async def error(_, exc):
        return JSONResponse(exc.to_envelope(), status_code=exc.status)

    with TestClient(app) as client:
        response = client.post("/api/update/upgrade", json={"version": "1.0.3b4"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == ErrorCode.UPDATE_CUSTOM_BUILD_PROTECTED
    probe.assert_not_called()
    create.assert_not_called()


def test_official_status_keeps_normal_upgrade_semantics(monkeypatch):
    monkeypatch.setattr(update, "custom_build_metadata", lambda: None)
    result = update._present_status(
        {"current_version": "1.0.3b2", "latest_any": "1.0.3b3"},
        stable_only=False,
        include_prerelease=True,
    )
    assert result["has_update"] is True
    assert result["custom_build"] is False
    assert result["in_place_upgrade_allowed"] is True
