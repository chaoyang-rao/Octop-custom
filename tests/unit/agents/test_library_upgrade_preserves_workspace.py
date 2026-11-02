"""Updating packaged templates must preserve expert-owned workspace content."""

from pathlib import Path

import pytest
from deepagents.backends import FilesystemBackend
from octop_harness.backends.workspace import BackendWorkspace


@pytest.mark.parametrize("system_files_path", [None, ".octop"])
def test_workspace_seed_preserves_custom_documents_and_skills(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, system_files_path: str | None
) -> None:
    monkeypatch.setenv("OCTOP_HOME", str(tmp_path / "octop-home"))
    workspace = BackendWorkspace(
        FilesystemBackend(root_dir=str(tmp_path), virtual_mode=False),
        tmp_path,
        system_files_path=system_files_path,
    )
    originals = {
        "SOUL.md": "Custom expert instructions\n",
        "AGENTS.md": "Custom workspace rules\n",
        "USER.md": "Custom user preferences\n",
        "skills/private-workflow/SKILL.md": "Custom workflow instructions\n",
        "agents/private-reviewer.md": "Custom reviewer instructions\n",
    }
    for path, content in originals.items():
        workspace.write_text(path, content, force=True)
    # Simulate the old builtin-version marker before starting the new package.
    workspace.write_text("_builtin_skills/.version", "old-package-version", force=True)
    result = workspace.init_workspace(language="zh")
    assert result.skills_synced
    assert result.templates_overwritten == []
    assert result.agents_overwritten == []
    for path, content in originals.items():
        assert workspace.read_text(path) == content
    workspace.init_workspace(language="zh")
    for path, content in originals.items():
        assert workspace.read_text(path) == content
