"""Online document import: Feishu CLI fetching plus knowledge service wiring."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.repos.knowledge import KnowledgeRepo
from octop.infra.db.repos.users import UserRepo
from octop.infra.knowledge import fetch as fetch_module
from octop.infra.knowledge.fetch import (
    OnlineDocument,
    OnlineDocumentError,
    fetch_feishu_document,
    fetch_online_document,
    fetch_web_document,
    is_feishu_url,
)
from octop.infra.knowledge.files import document_path
from octop.infra.knowledge.service import KnowledgeService, online_document_filename
from octop.infra.utils.paths import PathLayout


@pytest.mark.asyncio
async def test_url_import_does_not_block_the_request_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from octop.api.routers import knowledge_bases as routes

    event_loop_thread = threading.get_ident()
    fetch_threads: list[int] = []

    def import_document(*_args: object, **_kwargs: object) -> SimpleNamespace:
        fetch_threads.append(threading.get_ident())
        return SimpleNamespace(id="document")

    service = SimpleNamespace(import_online_document=import_document)
    monkeypatch.setattr(routes, "resolve_request_locale", lambda _request: "zh")
    monkeypatch.setattr(routes, "_require_usable", lambda *_args: None)
    monkeypatch.setattr(routes, "_knowledge_service", lambda _server: service)
    monkeypatch.setattr(routes, "_row_payload", lambda _row: {"id": "document"})
    queued: list[str] = []
    monkeypatch.setattr(
        routes, "enqueue_index_document", lambda _services, _kb, doc: queued.append(doc)
    )
    result = await routes.import_url_document(
        "knowledge-base",
        routes.ImportUrlBody(url="https://example.com/document"),
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(services=object()),  # type: ignore[arg-type]
        SimpleNamespace(id=1, is_admin=False),  # type: ignore[arg-type]
    )
    assert result == {"id": "document"}
    assert queued == ["document"]
    assert len(fetch_threads) == 1 and fetch_threads[0] != event_loop_thread


@pytest.fixture
def services(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    monkeypatch.setenv("OCTOP_HOME", str(tmp_path / ".octop"))
    paths = PathLayout.from_env()
    paths.ensure_root()
    db = SqlitePool(paths.db)
    run_migrations(db)
    owner_id = UserRepo(db).create(username="owner", password_hash="h", role="user")
    settings = MagicMock()
    settings.get.side_effect = lambda key, default=None: {
        "knowledge_feature_enabled": "1",
        "knowledge_embedding_backend": "onnx",
        "knowledge_embedding_model": "tiny",
    }.get(key, default)
    return SimpleNamespace(
        knowledge_repo=KnowledgeRepo(db),
        settings_repo=settings,
        provider_repo=None,
        owner_id=owner_id,
    )


def test_is_feishu_url() -> None:
    assert is_feishu_url("https://acme.feishu.cn/docx/ABC123")
    assert is_feishu_url("https://acme.larksuite.com/wiki/XYZ")
    assert is_feishu_url("https://acme.doubao.com/docx/ABC123")
    assert not is_feishu_url("https://example.com/blog/post")


def test_fetch_online_document_rejects_non_http() -> None:
    with pytest.raises(OnlineDocumentError):
        fetch_online_document("file:///etc/passwd")
    with pytest.raises(OnlineDocumentError):
        fetch_online_document("")


def test_fetch_feishu_document_parses_cli_json(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run_cli(argv: list[str], **_kwargs: object) -> str:
        calls.append(argv)
        return json.dumps(
            {
                "ok": True,
                "data": {
                    "document": {
                        "document_id": "doxcnABC",
                        "content": "# 季度复盘\n\n正文内容。",
                    }
                },
            }
        )

    monkeypatch.setattr(fetch_module, "resolve_binary", lambda _name: "/fake/lark-cli")
    monkeypatch.setattr(fetch_module, "run_cli", fake_run_cli)

    document = fetch_feishu_document("https://acme.feishu.cn/docx/ABC")

    assert calls == [
        [
            "/fake/lark-cli",
            "docs",
            "+fetch",
            "--doc",
            "https://acme.feishu.cn/docx/ABC",
            "--doc-format",
            "markdown",
            "--format",
            "json",
        ]
    ]
    assert document.title == "季度复盘"
    assert document.markdown.startswith("# 季度复盘")
    assert document.source_url.endswith("/docx/ABC")


def test_fetch_feishu_document_hints_missing_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run_cli(_argv: list[str], **_kwargs: object) -> str:
        raise ValueError("lark-cli auth login required: token expired")

    monkeypatch.setattr(fetch_module, "resolve_binary", lambda _name: "/fake/lark-cli")
    monkeypatch.setattr(fetch_module, "run_cli", fake_run_cli)

    with pytest.raises(OnlineDocumentError) as excinfo:
        fetch_feishu_document("https://acme.feishu.cn/docx/ABC")
    assert "授权" in str(excinfo.value)


def test_fetch_web_document_rejects_private_hosts() -> None:
    with pytest.raises(OnlineDocumentError):
        fetch_web_document("http://127.0.0.1:8088/api/health")


def test_online_document_filename() -> None:
    assert online_document_filename("Q3/规划: 复盘*") == "Q3 规划 复盘.md"
    assert online_document_filename("   ") == "在线文档.md"
    assert len(online_document_filename("长" * 200)) <= 83


def test_import_online_document_stores_markdown(
    services: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "octop.infra.knowledge.service.assert_knowledge_usable",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "octop.infra.knowledge.service.fetch_online_document",
        lambda url: OnlineDocument(
            title="飞书文档标题", markdown="# 飞书文档标题\n\n内容", source_url=url
        ),
    )
    svc = KnowledgeService(services)
    base = svc.create_base(owner_user_id=services.owner_id, name="Docs")

    created = svc.import_online_document(
        base.id,
        actor_user_id=services.owner_id,
        url="https://acme.feishu.cn/docx/ABC",
    )

    assert created.filename == "飞书文档标题.md"
    assert created.content_type == "text/markdown"
    assert created.status == "pending"
    stored = document_path(base.id, created.id, created.filename)
    assert stored.read_text(encoding="utf-8") == "# 飞书文档标题\n\n内容"
