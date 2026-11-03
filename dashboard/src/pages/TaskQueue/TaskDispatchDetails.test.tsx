import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { TaskDispatchView } from "../../api/modules/tasks";
import TaskDispatchDetails from "./TaskDispatchDetails";

const dispatch: TaskDispatchView = {
  origin_agent_id: "host",
  origin_thread_id: "source-thread",
  returned_attempt: 1,
  returned_state: "completed",
  coding_spec: {
    project_path: "/workspace/project",
    test_commands: ["npm test"],
  },
  coding_run: {
    phase: "published",
    branch: "codex/octop-task-one",
    verification: [
      {
        command_index: 0,
        exit_code: 0,
        passed: true,
        log_path: "/private/verification.log",
      },
    ],
    pr_url: "https://github.com/example/project/pull/12",
  },
};

describe("task origin and code delivery", () => {
  it("links a visible original conversation and the published PR", async () => {
    const open = vi.fn();
    render(
      <TaskDispatchDetails
        dispatch={dispatch}
        taskAttempt={1}
        taskState="completed"
        visibleAgentIds={new Set(["host"])}
        openConversation={open}
      />,
    );
    await userEvent.click(
      screen.getByRole("button", { name: "taskQueue.openOriginConversation" }),
    );
    expect(open).toHaveBeenCalledWith("host", "source-thread");
    const link = screen.getByRole("link", {
      name: "taskQueue.openPullRequest",
    });
    expect(link).toHaveAttribute(
      "href",
      "https://github.com/example/project/pull/12",
    );
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(
      screen.getByText("taskQueue.verificationPassed"),
    ).toBeInTheDocument();
    expect(screen.getByText("taskQueue.originReturned")).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "/private/verification.log" }),
    ).not.toBeInTheDocument();
  });

  it("does not navigate to an origin outside visible expert context", () => {
    render(
      <TaskDispatchDetails
        dispatch={dispatch}
        taskAttempt={1}
        taskState="completed"
        visibleAgentIds={new Set(["worker"])}
        openConversation={vi.fn()}
      />,
    );
    expect(
      screen.queryByRole("button", {
        name: "taskQueue.openOriginConversation",
      }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("taskQueue.originUnavailable")).toBeInTheDocument();
  });

  it("rejects executable or non-GitHub PR links from delivery data", () => {
    render(
      <TaskDispatchDetails
        dispatch={{
          ...dispatch,
          coding_run: {
            phase: "delivery_failed",
            pr_url: "javascript:alert(1)",
          },
        }}
        taskAttempt={1}
        taskState="failed"
        visibleAgentIds={new Set()}
        openConversation={vi.fn()}
      />,
    );
    expect(
      screen.queryByRole("link", { name: "taskQueue.openPullRequest" }),
    ).not.toBeInTheDocument();
  });

  it("keeps a later waiting event pending until that event is returned", () => {
    const event = {
      ...dispatch,
      returned_state: "waiting",
      current_event_id: 12,
      returned_event_id: 11,
    };
    const view = render(
      <TaskDispatchDetails
        dispatch={event}
        taskAttempt={1}
        taskState="waiting"
        visibleAgentIds={new Set(["host"])}
        openConversation={vi.fn()}
      />,
    );
    expect(
      screen.getByText("taskQueue.originReturnPending"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("taskQueue.originReturned"),
    ).not.toBeInTheDocument();
    view.rerender(
      <TaskDispatchDetails
        dispatch={{ ...event, returned_event_id: 12 }}
        taskAttempt={1}
        taskState="waiting"
        visibleAgentIds={new Set(["host"])}
        openConversation={vi.fn()}
      />,
    );
    expect(screen.getByText("taskQueue.originReturned")).toBeInTheDocument();
  });
});
