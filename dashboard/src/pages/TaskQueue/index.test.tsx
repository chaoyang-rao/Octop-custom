import { App } from "antd";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  taskQueueApi,
  type QueuedTask,
  type TaskDetail,
  type TaskCoordination,
} from "../../api/modules/tasks";
import TaskQueue from "./index";

const context = vi.hoisted(() => ({
  agents: [
    { agent_id: "a", name: "Owned", is_owner: true, bridge: false },
    { agent_id: "foreign", name: "Foreign", is_owner: false, bridge: false },
    { agent_id: "remote", name: "Remote", is_owner: true, bridge: true },
  ],
}));
vi.mock("../../context/AgentContext", () => ({
  useAgent: () => context,
}));
vi.mock("../../components/expertPortrait", () => ({
  ExpertPortrait: ({ agent }: { agent: { agent_id: string } }) => (
    <span data-testid={`expert-avatar-${agent.agent_id}`} />
  ),
}));
vi.mock("../../hooks/useServerTimezone", () => ({
  useServerTimezone: () => "Asia/Shanghai",
}));
vi.mock("../../api/modules/tasks", () => ({
  taskQueueApi: {
    list: vi.fn(),
    workflows: vi.fn(),
    runs: vi.fn(),
    controls: vi.fn(),
    create: vi.fn(),
    action: vi.fn(),
    pauseQueue: vi.fn(),
    projects: vi.fn(),
    detail: vi.fn(),
    continueCoordination: vi.fn(),
    stopCoordination: vi.fn(),
  },
}));
const api = vi.mocked(taskQueueApi);
beforeEach(() => {
  vi.clearAllMocks();
  context.agents = [
    { agent_id: "a", name: "Owned", is_owner: true, bridge: false },
    { agent_id: "foreign", name: "Foreign", is_owner: false, bridge: false },
    { agent_id: "remote", name: "Remote", is_owner: true, bridge: true },
  ];
  api.list.mockResolvedValue([]);
  api.workflows.mockResolvedValue([]);
  api.runs.mockResolvedValue([]);
  api.controls.mockResolvedValue({});
  api.create.mockResolvedValue({ id: "new" } as never);
  api.projects.mockResolvedValue([]);
  api.continueCoordination.mockResolvedValue(undefined);
  api.stopCoordination.mockResolvedValue(undefined);
});
const Content = () => (
  <App>
    <MemoryRouter>
      <TaskQueue />
    </MemoryRouter>
  </App>
);
const mount = () => render(<Content />);

const reviewScope: TaskCoordination = {
  scope_id: "review-one",
  user_id: 1,
  origin_agent_id: "a",
  origin_thread_id: "original",
  state: "needs_user",
  review_turns: 2,
  decision: "needs_user",
  summary: "The worker result needs a final choice.",
  question: "Should the report use CSV or XLSX?",
  allow_publish: false,
};
function reviewTask(scope: TaskCoordination): TaskDetail {
  return {
    id: "review-task",
    task_id: "review-task",
    user_id: 1,
    agent_id: "a",
    thread_id: "worker-thread",
    title: "Reviewed work",
    state: "completed",
    run_id: null,
    step_key: null,
    dependencies: [],
    archived: false,
    attempt: 1,
    error_code: null,
    created_at: 0,
    updated_at: 0,
    started_at: 0,
    finished_at: 0,
    prompt: "Review the report",
    result: "Worker result",
    options: {},
    events: [],
    dispatch: {
      coding_run: {},
      returned_attempt: 1,
      returned_state: "completed",
      coordination: scope,
    },
  };
}

describe("durable task UI", () => {
  it("creates a real queue request with an owned expert and instructions", async () => {
    mount();
    await userEvent.click(
      await screen.findByRole("button", { name: "taskQueue.create" }),
    );
    await userEvent.click(screen.getByLabelText("taskQueue.expert"));
    expect(
      await screen.findByText("Owned", {
        selector: ".ant-select-item-option-content",
      }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Foreign")).not.toBeInTheDocument();
    expect(screen.queryByText("Remote")).not.toBeInTheDocument();
    await userEvent.click(
      screen.getByText("Owned", {
        selector: ".ant-select-item-option-content",
      }),
    );
    await userEvent.type(
      screen.getByLabelText("taskQueue.name"),
      "Queued report",
    );
    await userEvent.type(
      screen.getByLabelText("taskQueue.prompt"),
      "Read the project report",
    );
    await userEvent.click(screen.getByLabelText("taskQueue.notifyPolicy"));
    await userEvent.click(
      await screen.findByText("taskQueue.onlyFailures", {
        selector: ".ant-select-item-option-content",
      }),
    );
    await userEvent.click(screen.getByRole("button", { name: "OK" }));
    await waitFor(() =>
      expect(api.create).toHaveBeenCalledWith({
        agent_id: "a",
        title: "Queued report",
        prompt: "Read the project report",
        options: { quiet: true },
      }),
    );
    expect(api.projects).not.toHaveBeenCalled();
  });

  it("includes a newly created expert and can assign it a coding task", async () => {
    const view = mount();
    context.agents = [
      ...context.agents,
      {
        agent_id: "new-writer",
        name: "New Writer",
        is_owner: true,
        bridge: false,
      },
    ];
    view.rerender(<Content />);
    api.projects.mockImplementation(async (id) =>
      id === "a"
        ? [
            {
              project_path: "/workspace/app",
              project_name: "App",
              created_at: 0,
              thread_count: 1,
            },
          ]
        : [],
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "taskQueue.create" }),
    );
    await userEvent.click(screen.getByLabelText("taskQueue.expert"));
    await userEvent.click(
      await screen.findByText("New Writer", {
        selector: ".ant-select-item-option-content",
      }),
    );
    await userEvent.click(screen.getByLabelText("taskQueue.codingTask"));
    await waitFor(() => expect(api.projects).toHaveBeenCalledWith("a"));
    await userEvent.click(screen.getByLabelText("taskQueue.codeProject"));
    await userEvent.click(
      await screen.findByText("App · /workspace/app", {
        selector: ".ant-select-item-option-content",
      }),
    );
    await userEvent.type(
      screen.getByLabelText("taskQueue.name"),
      "Fix project",
    );
    await userEvent.type(
      screen.getByLabelText("taskQueue.prompt"),
      "Fix the report output",
    );
    await userEvent.type(
      screen.getByLabelText("taskQueue.verificationCommands"),
      "npm test\nnpm run build",
    );
    await userEvent.click(screen.getByRole("button", { name: "OK" }));
    await waitFor(() =>
      expect(api.create).toHaveBeenCalledWith({
        agent_id: "new-writer",
        title: "Fix project",
        prompt: "Fix the report output",
        options: { quiet: false },
        coding: {
          project_path: "/workspace/app",
          test_commands: ["npm test", "npm run build"],
          publish_pr: false,
        },
      }),
    );
    expect(api.projects).toHaveBeenCalledWith("new-writer");
    expect(api.projects).not.toHaveBeenCalledWith("foreign");
    expect(api.projects).not.toHaveBeenCalledWith("remote");
  });

  it("shows delivery, failed verification and the actual assigned expert", async () => {
    const task: QueuedTask = {
      id: "task-one",
      task_id: "task-one",
      user_id: 1,
      agent_id: "a",
      thread_id: "worker-thread",
      title: "Review output",
      state: "failed",
      run_id: null,
      step_key: null,
      dependencies: [],
      archived: false,
      attempt: 1,
      error_code: null,
      created_at: 0,
      updated_at: 0,
      started_at: 0,
      finished_at: 0,
    };
    api.list.mockResolvedValue([task] as never);
    api.detail.mockResolvedValue({
      ...task,
      prompt: "Review output",
      result: "Verification needs attention",
      options: {},
      events: [],
      dispatch: {
        origin_agent_id: "a",
        origin_thread_id: "original",
        returned_attempt: 1,
        returned_state: "failed",
        coding_spec: {
          project_path: "/workspace/app",
          test_commands: ["npm test"],
        },
        coding_run: {
          phase: "verification_failed",
          verification: [
            {
              command_index: 0,
              exit_code: 1,
              passed: false,
              log_path: "/private/check.log",
            },
          ],
        },
      },
    });
    mount();
    await userEvent.click(
      await screen.findByRole("button", { name: "Review output" }),
    );
    expect(
      await screen.findByText("taskQueue.verificationFailed"),
    ).toBeInTheDocument();
    expect(screen.getByText("npm test")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "taskQueue.openOriginConversation" }),
    ).toBeInTheDocument();
    expect(screen.getAllByTestId("expert-avatar-a")).toHaveLength(2);
    expect(
      screen.queryByRole("link", { name: "taskQueue.openPullRequest" }),
    ).not.toBeInTheDocument();
  });

  it("updates an open task detail when verification finishes", async () => {
    const task: QueuedTask = {
      id: "live-task",
      task_id: "live-task",
      user_id: 1,
      agent_id: "a",
      thread_id: "worker-thread",
      title: "Live task",
      state: "running",
      run_id: null,
      step_key: null,
      dependencies: [],
      archived: false,
      attempt: 1,
      error_code: null,
      created_at: 0,
      updated_at: 0,
      started_at: 0,
      finished_at: null,
    };
    const detail = {
      ...task,
      prompt: "Fix",
      result: "",
      options: {},
      events: [],
      dispatch: {
        returned_attempt: 0,
        returned_state: "",
        origin_agent_id: "a",
        origin_thread_id: "source-thread",
        current_event_id: 1,
        returned_event_id: 0,
        coding_spec: {
          project_path: "/workspace/app",
          test_commands: ["npm test"],
        },
        coding_run: { phase: "prepared" },
      },
    };
    api.list.mockResolvedValue([task]);
    api.detail.mockResolvedValue(detail);
    mount();
    await userEvent.click(
      await screen.findByRole("button", { name: "Live task" }),
    );
    expect(await screen.findByText("prepared")).toBeInTheDocument();
    const completed = {
      ...detail,
      state: "completed" as const,
      dispatch: {
        ...detail.dispatch,
        returned_attempt: 1,
        returned_state: "completed",
        current_event_id: 2,
        returned_event_id: 1,
        coding_run: {
          phase: "published",
          pr_url: "https://github.com/example/project/pull/7",
        },
      },
    };
    api.detail.mockResolvedValue(completed);
    expect(
      await screen.findByRole(
        "link",
        { name: "taskQueue.openPullRequest" },
        { timeout: 6500 },
      ),
    ).toHaveAttribute("href", "https://github.com/example/project/pull/7");
    expect(
      screen.getByText("taskQueue.originReturnPending"),
    ).toBeInTheDocument();
    api.detail.mockResolvedValue({
      ...completed,
      dispatch: { ...completed.dispatch, returned_event_id: 2 },
    });
    expect(
      await screen.findByText(
        "taskQueue.originReturned",
        {},
        { timeout: 6500 },
      ),
    ).toBeInTheDocument();
  }, 20000);

  it("does not replace a newer task context with an older detail response", async () => {
    const first: TaskDetail = {
      id: "first",
      task_id: "first",
      user_id: 1,
      agent_id: "a",
      thread_id: "first-thread",
      title: "First task",
      state: "completed",
      run_id: null,
      step_key: null,
      dependencies: [],
      archived: false,
      attempt: 1,
      error_code: null,
      created_at: 0,
      updated_at: 0,
      started_at: 0,
      finished_at: 0,
      prompt: "First prompt",
      result: "First result",
      options: {},
      events: [],
    };
    const second: TaskDetail = {
      ...first,
      id: "second",
      task_id: "second",
      title: "Second task",
      thread_id: "second-thread",
      prompt: "Second prompt",
      result: "Second result",
    };
    let finishFirst!: (detail: TaskDetail) => void;
    api.list.mockResolvedValue([first, second]);
    api.detail.mockImplementation(async (id) =>
      id === "first"
        ? new Promise<TaskDetail>((resolve) => {
            finishFirst = resolve;
          })
        : second,
    );
    mount();
    await userEvent.click(
      await screen.findByRole("button", { name: "First task" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Second task" }));
    expect(await screen.findByText("Second result")).toBeInTheDocument();
    await act(async () => finishFirst(first));
    expect(screen.getByText("Second result")).toBeInTheDocument();
    expect(screen.queryByText("First result")).not.toBeInTheDocument();
  });

  it("keeps reviewing a finished expert task until the overall goal is ready", async () => {
    const running = reviewTask({
      ...reviewScope,
      state: "running",
      question: "",
      decision: "continue",
    });
    api.list.mockResolvedValue([running]);
    api.detail.mockResolvedValue(running);
    mount();
    await userEvent.click(
      await screen.findByRole("button", { name: "Reviewed work" }),
    );
    expect(
      screen.getAllByText("taskQueue.coordinationStates.running").length,
    ).toBeGreaterThan(0);
    expect(
      screen.queryByText("taskQueue.coordinationReady"),
    ).not.toBeInTheDocument();
    expect(
      screen.getAllByText("taskQueue.executorStatus").length,
    ).toBeGreaterThan(0);
    const ready = reviewTask({
      ...reviewScope,
      state: "idle",
      decision: "ready",
      question: "",
      summary: "The complete goal is verified.",
    });
    api.list.mockResolvedValue([ready]);
    api.detail.mockResolvedValue(ready);
    expect(
      await screen.findByText(
        "The complete goal is verified.",
        {},
        { timeout: 6500 },
      ),
    ).toBeInTheDocument();
    expect(
      screen.getAllByText("taskQueue.coordinationReady").length,
    ).toBeGreaterThan(0);
  }, 12000);

  it.each([false, true])(
    "submits real clarification with coding=%s without automatic publication",
    async (coding) => {
      const task = reviewTask({
        ...reviewScope,
        has_coding_tasks: coding,
        allow_publish: false,
      });
      api.list.mockResolvedValue([task]);
      api.detail.mockResolvedValue(task);
      api.continueCoordination.mockImplementation(async () => {
        const pending = reviewTask({
          ...reviewScope,
          state: "pending",
          question: "",
          has_coding_tasks: coding,
        });
        api.list.mockResolvedValue([pending]);
        api.detail.mockResolvedValue(pending);
        return undefined;
      });
      mount();
      await userEvent.click(
        await screen.findByRole("button", { name: "Reviewed work" }),
      );
      expect(await screen.findByText(reviewScope.question)).toBeInTheDocument();
      const checkbox = screen.queryByRole("checkbox", {
        name: "taskQueue.coordinationAllowPublish",
      });
      if (coding) expect(checkbox).not.toBeChecked();
      else expect(checkbox).not.toBeInTheDocument();
      await userEvent.type(
        screen.getByLabelText("taskQueue.coordinationInput"),
        "Use XLSX and include the missing values.",
      );
      await userEvent.click(
        screen.getByRole("button", { name: "taskQueue.coordinationContinue" }),
      );
      await waitFor(() =>
        expect(api.continueCoordination).toHaveBeenCalledWith("review-task", {
          prompt: "Use XLSX and include the missing values.",
          ...(coding ? { allow_publish: false } : {}),
        }),
      );
      expect(api.action).not.toHaveBeenCalled();
    },
  );

  it("pauses only subsequent tasks for the selected owned expert", async () => {
    api.pauseQueue.mockResolvedValue({ paused: true });
    mount();
    await userEvent.click(
      await screen.findByRole("switch", { name: "taskQueue.pauseQueueFor" }),
    );
    await waitFor(() => expect(api.pauseQueue).toHaveBeenCalledWith("a", true));
    expect(api.action).not.toHaveBeenCalled();
  });

  it("stops coordinator review without submitting new work or clearing finished output", async () => {
    const task = reviewTask({ ...reviewScope, state: "running", question: "" });
    api.list.mockResolvedValue([task]);
    api.detail.mockResolvedValue(task);
    api.stopCoordination.mockImplementation(async () => {
      const stopped = reviewTask({ ...reviewScope, state: "stopped" });
      api.list.mockResolvedValue([stopped]);
      api.detail.mockResolvedValue(stopped);
      return undefined;
    });
    mount();
    await userEvent.click(
      await screen.findByRole("button", { name: "Reviewed work" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "taskQueue.coordinationStop" }),
    );
    await waitFor(() =>
      expect(api.stopCoordination).toHaveBeenCalledWith("review-task"),
    );
    expect(api.continueCoordination).not.toHaveBeenCalled();
    expect(api.action).not.toHaveBeenCalled();
    expect(await screen.findByText("Worker result")).toBeInTheDocument();
    await waitFor(() =>
      expect(
        screen.getAllByText("taskQueue.coordinationStates.stopped").length,
      ).toBeGreaterThan(0),
    );
  });
});
