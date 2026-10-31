import { App } from "antd";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { taskQueueApi } from "../../api/modules/tasks";
import TaskQueue from "./index";

vi.mock("../../context/AgentContext", () => ({
  useAgent: () => ({
    agents: [
      { agent_id: "a", name: "Owned", is_owner: true },
      { agent_id: "foreign", name: "Foreign", is_owner: false },
      { agent_id: "remote", name: "Remote", is_owner: true, bridge: true },
    ],
  }),
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
  },
}));
const api = vi.mocked(taskQueueApi);
beforeEach(() => {
  vi.clearAllMocks();
  api.list.mockResolvedValue([]);
  api.workflows.mockResolvedValue([]);
  api.runs.mockResolvedValue([]);
  api.controls.mockResolvedValue({});
  api.create.mockResolvedValue({ id: "new" } as never);
});
const mount = () =>
  render(
    <App>
      <MemoryRouter>
        <TaskQueue />
      </MemoryRouter>
    </App>,
  );

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
  });

  it("pauses only subsequent tasks for the selected owned expert", async () => {
    api.pauseQueue.mockResolvedValue({ paused: true });
    mount();
    await userEvent.click(
      await screen.findByRole("switch", { name: "taskQueue.pauseQueueFor" }),
    );
    await waitFor(() => expect(api.pauseQueue).toHaveBeenCalledWith("a", true));
    expect(api.action).not.toHaveBeenCalled();
  });
});
