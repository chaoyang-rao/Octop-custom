"""Coding delivery uses real local Git and fake GitHub, never an actual model/PR."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from octop.infra.tasks.coding import (
    CodingTaskError,
    CodingTaskService,
    CommandResult,
    github_repository,
    run_command,
)

posix_only = pytest.mark.skipif(os.name != "posix", reason="POSIX signals and symlinks")


def git(root: Path, *args: str) -> str:
    return (
        subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.PIPE)
        .decode()
        .strip()
    )


@dataclass
class Spec:
    project_path: str
    base_ref: str = "HEAD"
    test_commands: list[str] = field(
        default_factory=lambda: [f'"{sys.executable}" -c "print(123)"']
    )
    publish_pr: bool = False


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("OCTOP_HOME", str(tmp_path / "octop"))
    root = tmp_path / "project with spaces"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Fixture")
    git(root, "config", "user.email", "fixture@example.invalid")
    (root / "tracked.txt").write_text("committed input\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "initial")
    return root


class FakeGithub:
    def __init__(self, remote: Path):
        self.remote = remote
        self.calls: list[list[str]] = []
        self.prs: list[dict] = []
        self.lookup_fails = False
        self.ambiguous_create = False

    async def __call__(self, argv, *, cwd, timeout, log_path=None):
        self.calls.append(argv)
        if argv[0] == "gh":
            if argv[2] == "list":
                return (
                    CommandResult(1)
                    if self.lookup_fails
                    else CommandResult(0, json.dumps(self.prs))
                )
            assert argv[2] == "create"
            assert "--draft" in argv
            branch = argv[argv.index("--head") + 1]
            base = argv[argv.index("--base") + 1]
            body = Path(argv[argv.index("--body-file") + 1]).read_text()
            assert "publish" in body and "1" in body
            self.prs = [
                {
                    "url": "https://github.com/fixture/project/pull/1",
                    "state": "OPEN",
                    "headRefName": branch,
                    "baseRefName": base,
                    "headRepositoryOwner": {"login": "fixture"},
                }
            ]
            if self.ambiguous_create:
                self.ambiguous_create = False
                return CommandResult(1, stderr="simulated response lost after creation")
            return CommandResult(0, self.prs[0]["url"] + "\n")
        if len(argv) > 3 and argv[3] == "push":
            return await run_command(
                ["git", "-C", str(cwd), "push", str(self.remote), argv[-1]],
                cwd=cwd,
                timeout=timeout,
                log_path=log_path,
            )
        return await run_command(argv, cwd=cwd, timeout=timeout, log_path=log_path)


@pytest.fixture
def github(project, tmp_path):
    bare = tmp_path / "remote.git"
    bare.mkdir()
    git(bare, "init", "--bare")
    git(project, "remote", "add", "origin", "https://github.com/fixture/project.git")
    return FakeGithub(bare)


async def test_worktree_keeps_original_dirty_files_and_does_not_commit_by_default(project):
    before = git(project, "rev-parse", "HEAD")
    (project / "tracked.txt").write_text("private unfinished edit")
    (project / "private-note.txt").write_text("must stay only in original")
    status = git(project, "status", "--porcelain")
    service = CodingTaskService()
    spec = Spec(str(project))
    run = await service.prepare("task-1", 7, spec)
    worktree = Path(run["worktree"])
    assert worktree != project and worktree.is_relative_to(Path(os.environ["OCTOP_HOME"]))
    assert (worktree / "tracked.txt").read_text() == "committed input\n"
    assert not (worktree / "private-note.txt").exists()
    (worktree / "result.py").write_text("answer = 42\n")
    result = await service.finalize("task-1", "Implement answer", spec, run)
    assert result["phase"] == "ready"
    assert result["changed_files"] == ["result.py"]
    assert "answer = 42" in Path(result["diff_path"]).read_text()
    assert result["verification"][0]["passed"]
    assert Path(result["verification"][0]["log_path"]).is_file()
    assert git(worktree, "rev-parse", "HEAD") == before
    assert git(project, "rev-parse", "HEAD") == before
    assert git(project, "status", "--porcelain") == status
    assert (project / "tracked.txt").read_text() == "private unfinished edit"


async def test_tasks_are_separate_and_retry_recovers_existing_work(project):
    service = CodingTaskService()
    spec = Spec(str(project))
    a = await service.prepare("one", 7, spec)
    b = await service.prepare("two", 7, spec)
    assert a["worktree"] != b["worktree"] and a["branch"] != b["branch"]
    (Path(a["worktree"]) / "unfinished.txt").write_text("keep me")
    (project / "later.txt").write_text("later source commit")
    git(project, "add", ".")
    git(project, "commit", "-m", "later")
    recovered = await CodingTaskService().prepare("one", 7, spec)
    assert recovered["base_oid"] == a["base_oid"]
    assert (Path(recovered["worktree"]) / "unfinished.txt").read_text() == "keep me"


async def test_context_cannot_point_to_another_task(project):
    service = CodingTaskService()
    spec = Spec(str(project))
    run = await service.prepare("one", 7, spec)
    with pytest.raises(CodingTaskError, match="coding_context_mismatch"):
        await service.prepare("one", 7, spec, {**run, "user_id": 8})
    with pytest.raises(CodingTaskError, match="coding_invalid_task"):
        await service.prepare("../escape", 7, spec)
    nested = project / "nested"
    nested.mkdir()
    with pytest.raises(CodingTaskError, match="coding_repository_root_required"):
        await service.prepare("nested", 7, Spec(str(nested)))


@posix_only
async def test_rejects_symlink_checkout_or_context_file(project, tmp_path):
    service = CodingTaskService()
    spec = Spec(str(project))
    run = await service.prepare("one", 7, spec)
    context = Path(run["worktree"]).parent / "context.json"
    context.unlink()
    other = tmp_path / "other.json"
    other.write_text(json.dumps(run))
    context.symlink_to(other)
    with pytest.raises(CodingTaskError, match="coding_invalid_path"):
        await service.prepare("one", 7, spec)
    alias = tmp_path / "alias"
    alias.symlink_to(project, target_is_directory=True)
    with pytest.raises(CodingTaskError, match="coding_invalid_path"):
        await service.prepare("alias", 7, Spec(str(alias)))


async def test_failed_verification_never_contacts_github(project, github):
    service = CodingTaskService(command_runner=github)
    spec = Spec(
        str(project),
        test_commands=[f'"{sys.executable}" -c "raise SystemExit(3)"'],
        publish_pr=True,
    )
    run = await service.prepare("fail", 7, spec)
    (Path(run["worktree"]) / "result.py").write_text("invalid implementation")
    result = await service.finalize("fail", "Should fail", spec, run)
    assert result["phase"] == "verification_failed"
    assert result["verification"][0]["exit_code"] == 3
    assert not any(call[0] == "gh" or "push" in call for call in github.calls)


async def test_verification_that_changes_sources_requires_another_attempt(project):
    service = CodingTaskService()
    spec = Spec(
        str(project),
        test_commands=[
            f'''"{sys.executable}" -c "from pathlib import Path; Path('format.txt').write_text('formatted')"'''
        ],
    )
    run = await service.prepare("format", 7, spec)
    first = await service.finalize("format", "Formatting", spec, run)
    assert first["phase"] == "verification_failed"
    assert first["error_code"] == "coding_verification_changed_files"
    second = await service.finalize("format", "Formatting", spec, first)
    assert second["phase"] == "ready"


async def test_publish_uses_local_remote_and_reuses_draft_pr(project, github):
    service = CodingTaskService(command_runner=github)
    spec = Spec(str(project), publish_pr=True)
    original = git(project, "rev-parse", "HEAD")
    run = await service.prepare("publish", 7, spec)
    (Path(run["worktree"]) / "result.py").write_text("answer = 42\n")
    first = await service.finalize("publish", "Answer", spec, run)
    assert first["phase"] == "published"
    assert first["pr_url"] == "https://github.com/fixture/project/pull/1"
    assert git(github.remote, "rev-parse", first["branch"]) == first["commit"]
    second = await service.finalize("publish", "Answer", spec, first)
    assert second["pr_url"] == first["pr_url"]
    assert sum(call[:3] == ["gh", "pr", "create"] for call in github.calls) == 1
    assert git(project, "rev-parse", "HEAD") == original
    assert not any(argument == "merge" for call in github.calls for argument in call)


async def test_lookup_failure_does_not_fall_back_to_creating_a_pr(project, github):
    service = CodingTaskService(command_runner=github)
    spec = Spec(str(project), publish_pr=True)
    run = await service.prepare("lookup", 7, spec)
    (Path(run["worktree"]) / "result.py").write_text("answer = 42\n")
    github.lookup_fails = True
    result = await service.finalize("lookup", "Answer", spec, run)
    assert result["phase"] == "delivery_failed"
    assert result["error_code"] == "coding_pr_lookup_failed"
    assert not any(call[:3] == ["gh", "pr", "create"] or "push" in call for call in github.calls)


async def test_retry_after_lost_create_response_reuses_existing_pr(project, github):
    service = CodingTaskService(command_runner=github)
    spec = Spec(str(project), publish_pr=True)
    run = await service.prepare("publish-unknown", 7, spec)
    (Path(run["worktree"]) / "result.py").write_text("answer = 42\n")
    github.ambiguous_create = True
    first = await service.finalize("publish-unknown", "Answer", spec, run)
    assert first["phase"] == "delivery_failed"
    second = await service.finalize("publish-unknown", "Answer", spec, first)
    assert second["phase"] == "published"
    assert sum(call[:3] == ["gh", "pr", "create"] for call in github.calls) == 1


async def test_closed_pr_does_not_create_a_replacement(project, github):
    service = CodingTaskService(command_runner=github)
    spec = Spec(str(project), publish_pr=True)
    run = await service.prepare("closed", 7, spec)
    (Path(run["worktree"]) / "result.py").write_text("answer = 42\n")
    github.prs = [
        {
            "url": "https://github.com/fixture/project/pull/1",
            "state": "CLOSED",
            "headRefName": run["branch"],
            "baseRefName": "main",
            "headRepositoryOwner": {"login": "fixture"},
        }
    ]
    result = await service.finalize("closed", "Answer", spec, run)
    assert result["error_code"] == "coding_pr_closed_or_mismatched"
    assert not any(call[:3] == ["gh", "pr", "create"] or "push" in call for call in github.calls)


async def test_sensitive_files_are_not_automatically_published(project, github):
    service = CodingTaskService(command_runner=github)
    spec = Spec(str(project), publish_pr=True)
    run = await service.prepare("secret", 7, spec)
    (Path(run["worktree"]) / "private.pem").write_text("synthetic fixture only")
    result = await service.finalize("secret", "Do not publish", spec, run)
    assert result["error_code"] == "coding_sensitive_paths"
    assert not any("push" in call for call in github.calls)


async def test_missing_delivery_template_fails_before_push(project, github, monkeypatch):
    monkeypatch.setattr("octop.infra.tasks.coding.tr", lambda key, *args, **kwargs: key)
    service = CodingTaskService(command_runner=github)
    spec = Spec(str(project), publish_pr=True)
    run = await service.prepare("missing-template", 7, spec)
    (Path(run["worktree"]) / "result.py").write_text("answer = 42\n")
    result = await service.finalize("missing-template", "Answer", spec, run)
    assert result["error_code"] == "coding_pr_delivery_failed"
    assert not any("push" in call for call in github.calls)


@posix_only
@pytest.mark.parametrize("hook", ["pre-commit", "post-commit"])
async def test_commit_hooks_cannot_publish_an_unverified_tree_or_branch(project, github, hook):
    script = project / ".git" / "hooks" / hook
    operation = (
        "printf 'changed by hook\\n' > result.py\ngit add result.py"
        if hook == "pre-commit"
        else "git checkout -b unexpected-branch"
    )
    script.write_text("#!/bin/sh\n" + operation + "\n")
    script.chmod(0o755)
    service = CodingTaskService(command_runner=github)
    spec = Spec(str(project), publish_pr=True)
    run = await service.prepare("publish-hook", 7, spec)
    (Path(run["worktree"]) / "result.py").write_text("answer = 42\n")
    result = await service.finalize("publish-hook", "Answer", spec, run)
    assert result["phase"] == "delivery_failed"
    assert result["error_code"] == (
        "coding_verification_changed_files" if hook == "pre-commit" else "coding_context_mismatch"
    )
    assert not any(call[:3] == ["gh", "pr", "create"] or "push" in call for call in github.calls)


@pytest.mark.parametrize("revoke_after", ["lookup", "push"])
async def test_authorization_is_rechecked_before_remote_side_effects(project, github, revoke_after):
    revoked = False

    async def runner(argv, *, cwd, timeout, log_path=None):
        nonlocal revoked
        result = await github(argv, cwd=cwd, timeout=timeout, log_path=log_path)
        if (revoke_after == "lookup" and argv[:3] == ["gh", "pr", "list"]) or (
            revoke_after == "push" and "push" in argv
        ):
            revoked = True
        return result

    async def check_active():
        if revoked:
            raise asyncio.CancelledError

    service = CodingTaskService(command_runner=runner)
    spec = Spec(str(project), publish_pr=True)
    run = await service.prepare("publish-guard", 7, spec)
    (Path(run["worktree"]) / "result.py").write_text("answer = 42\n")
    with pytest.raises(asyncio.CancelledError):
        await service.finalize("publish-guard", "Answer", spec, run, check_active=check_active)
    assert not any(call[:3] == ["gh", "pr", "create"] for call in github.calls)
    if revoke_after == "lookup":
        assert not any("push" in call for call in github.calls)


async def test_timeout_stops_command_before_it_writes(tmp_path):
    late = tmp_path / "late"
    result = await run_command(
        [
            sys.executable,
            "-c",
            f"import time; from pathlib import Path; time.sleep(.5); Path({str(late)!r}).write_text('late')",
        ],
        cwd=tmp_path,
        timeout=0.05,
    )
    assert result.timed_out
    await asyncio.sleep(0.6)
    assert not late.exists()


async def test_repeated_cancellation_stops_command(tmp_path):
    started = tmp_path / "started"
    late = tmp_path / "late"
    job = asyncio.create_task(
        run_command(
            [
                sys.executable,
                "-c",
                f"import time; from pathlib import Path; Path({str(started)!r}).touch(); time.sleep(.5); Path({str(late)!r}).touch()",
            ],
            cwd=tmp_path,
            timeout=10,
        )
    )
    for _ in range(500):
        if started.exists():
            break
        await asyncio.sleep(0.01)
    assert started.exists()
    job.cancel()
    await asyncio.sleep(0)
    job.cancel()
    with pytest.raises(asyncio.CancelledError):
        await job
    await asyncio.sleep(0.6)
    assert not late.exists()


@posix_only
async def test_timeout_kills_child_even_when_its_parent_already_exited(tmp_path):
    late = tmp_path / "grandchild"
    child = f"import signal,time; from pathlib import Path; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(.5); Path({str(late)!r}).touch()"
    parent = f"import subprocess,sys; subprocess.Popen([sys.executable,'-c',{child!r}])"
    result = await run_command([sys.executable, "-c", parent], cwd=tmp_path, timeout=0.1)
    assert result.timed_out
    await asyncio.sleep(0.6)
    assert not late.exists()


async def test_output_and_private_log_are_bounded(tmp_path):
    log = tmp_path / "log.txt"
    result = await run_command(
        [sys.executable, "-c", "print('x'*2000000)"], cwd=tmp_path, timeout=5, log_path=log
    )
    assert result.returncode == 0 and result.truncated
    assert len(result.stdout.encode()) <= 1024 * 1024
    assert log.stat().st_size <= 1024 * 1024


@pytest.mark.parametrize(
    "remote",
    [
        "https://github.com/owner/repo.git",
        "git@github.com:owner/repo.git",
        "ssh://git@github.com/owner/repo.git",
    ],
)
def test_github_repository_addresses(remote):
    assert github_repository(remote) == "owner/repo"


@pytest.mark.parametrize(
    "remote",
    [
        "https://token@github.com/owner/repo",
        "https://other.example/owner/repo",
        "https://github.com/owner/repo?token=x",
        "https://github.com/../repo",
        "file:///somewhere",
    ],
)
def test_rejects_credential_or_non_github_addresses(remote):
    with pytest.raises(CodingTaskError):
        github_repository(remote)
