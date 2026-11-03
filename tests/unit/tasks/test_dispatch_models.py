"""Delegation is expert-neutral and code-specific requirements remain optional."""

import pytest
from pydantic import ValidationError

from octop.infra.tasks.models import CodingTaskSpec, TaskCreate, TaskDispatchView


def test_plain_task_accepts_any_expert_without_a_coding_requirement() -> None:
    task = TaskCreate(agent_id="new-analysis-expert", title="分析", prompt="分析这份数据")
    assert task.coding is None and task.origin_thread_id is None
    assert task.options.conversation_mode == "craft"


@pytest.mark.parametrize("commands", [[], [" "], ["ok"] * 9])
def test_coding_requires_bounded_nonblank_verification_commands(commands: list[str]) -> None:
    with pytest.raises(ValidationError):
        CodingTaskSpec(project_path="project", test_commands=commands)


def test_coding_input_and_dispatch_view_do_not_accept_or_emit_server_fields() -> None:
    body = TaskCreate(
        agent_id="new-code-expert",
        title="修复",
        prompt="修复并测试",
        origin_thread_id="original-chat",
        coding={"project_path": " project ", "test_commands": [" make all "]},
    )
    assert body.coding.project_path == "project"
    assert body.coding.test_commands == ["make all"]
    assert body.coding.publish_pr is False
    for field in ("coding_run", "parent_task_id", "parent_attempt", "scope_id", "coordination"):
        with pytest.raises(ValidationError):
            TaskCreate.model_validate({**body.model_dump(), field: "server-only"})
    view = TaskDispatchView.model_validate({"task_id": "task", "request_key": "internal"})
    assert "request_key" not in view.model_dump()
