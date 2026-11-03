import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { TaskCoordination } from "../../api/modules/tasks";
import TaskCoordinationDetails from "./TaskCoordinationDetails";

const scope: TaskCoordination = {
  scope_id: "scope-one",
  user_id: 1,
  origin_agent_id: "host",
  origin_thread_id: "original",
  state: "needs_user",
  review_turns: 2,
  decision: "needs_user",
  summary: "The analysis is ready.",
  question: "Which output format should be used?",
  allow_publish: false,
};

describe("coordinator review details", () => {
  it("opens the actual task group using local encoded path segments", () => {
    render(
      <TaskCoordinationDetails
        scope={{
          ...scope,
          room: {
            agent_id: "group/a",
            thread_id: "thread?one",
            name: "Task group",
          },
        }}
        isCoding={false}
      />,
    );
    expect(
      screen.getByRole("link", { name: "taskQueue.openTaskRoom" }),
    ).toHaveAttribute("href", "/chat/group%2Fa/thread%3Fone");
  });
  it("shows ongoing review separately from useful summary and ignores private fields", () => {
    render(
      <TaskCoordinationDetails
        scope={{
          ...scope,
          state: "running",
          question: "",
          signature: "private-signature",
          goals: { text: "private-long-goal-json" },
        }}
        isCoding={false}
        onContinue={vi.fn()}
      />,
    );
    expect(
      screen.getByText("taskQueue.coordinationStates.running"),
    ).toBeInTheDocument();
    expect(screen.getByText("The analysis is ready.")).toBeInTheDocument();
    expect(screen.queryByText("private-signature")).not.toBeInTheDocument();
    expect(
      screen.queryByText("private-long-goal-json"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "taskQueue.coordinationContinue" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("taskQueue.coordinationReady"),
    ).not.toBeInTheDocument();
  });

  it("sends actual human clarification without publication fields for a general task", async () => {
    const resume = vi.fn().mockResolvedValue(undefined);
    render(
      <TaskCoordinationDetails
        scope={{ ...scope, allow_publish: true }}
        isCoding={false}
        onContinue={resume}
      />,
    );
    expect(screen.getByText(scope.question)).toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    await userEvent.type(
      screen.getByLabelText("taskQueue.coordinationInput"),
      "Use CSV, including missing values.",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "taskQueue.coordinationContinue" }),
    );
    await waitFor(() =>
      expect(resume).toHaveBeenCalledWith({
        prompt: "Use CSV, including missing values.",
      }),
    );
  });

  it("keeps publication disabled unless the coding checkbox is selected", async () => {
    const resume = vi.fn().mockResolvedValue(undefined);
    render(
      <TaskCoordinationDetails scope={scope} isCoding onContinue={resume} />,
    );
    expect(
      screen.getByRole("checkbox", {
        name: "taskQueue.coordinationAllowPublish",
      }),
    ).not.toBeChecked();
    await userEvent.type(
      screen.getByLabelText("taskQueue.coordinationInput"),
      "Validate locally first.",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "taskQueue.coordinationContinue" }),
    );
    await waitFor(() =>
      expect(resume).toHaveBeenLastCalledWith({
        prompt: "Validate locally first.",
        allow_publish: false,
      }),
    );
    await userEvent.type(
      screen.getByLabelText("taskQueue.coordinationInput"),
      "Create the draft PR.",
    );
    await userEvent.click(
      screen.getByRole("checkbox", {
        name: "taskQueue.coordinationAllowPublish",
      }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "taskQueue.coordinationContinue" }),
    );
    await waitFor(() =>
      expect(resume).toHaveBeenLastCalledWith({
        prompt: "Create the draft PR.",
        allow_publish: true,
      }),
    );
  });

  it("preserves a human draft and unchecked permission across status refreshes", async () => {
    const resume = vi.fn().mockResolvedValue(undefined);
    const view = render(
      <TaskCoordinationDetails
        scope={{ ...scope, allow_publish: true }}
        isCoding
        onContinue={resume}
      />,
    );
    const checkbox = screen.getByRole("checkbox", {
      name: "taskQueue.coordinationAllowPublish",
    });
    expect(checkbox).toBeChecked();
    await userEvent.click(checkbox);
    await userEvent.type(
      screen.getByLabelText("taskQueue.coordinationInput"),
      "Keep this clarification draft.",
    );
    view.rerender(
      <TaskCoordinationDetails
        scope={{ ...scope, allow_publish: true, summary: "Updated progress." }}
        isCoding
        onContinue={resume}
      />,
    );
    expect(screen.getByLabelText("taskQueue.coordinationInput")).toHaveValue(
      "Keep this clarification draft.",
    );
    expect(checkbox).not.toBeChecked();
  });

  it("keeps input on an interrupted-parent error rather than bypassing retry", async () => {
    const resume = vi.fn().mockRejectedValue(
      new Error(
        JSON.stringify({
          error: {
            message: "Retry the parent task before continuing.",
            details: { task_reason: "coordination_parent_interrupted" },
          },
        }),
      ),
    );
    render(
      <TaskCoordinationDetails
        scope={{ ...scope, state: "interrupted" }}
        isCoding={false}
        onContinue={resume}
      />,
    );
    await userEvent.type(
      screen.getByLabelText("taskQueue.coordinationInput"),
      "Continue with the existing work.",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "taskQueue.coordinationContinue" }),
    );
    expect(
      await screen.findByText("Retry the parent task before continuing."),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("taskQueue.coordinationInput")).toHaveValue(
      "Continue with the existing work.",
    );
    expect(resume).toHaveBeenCalledOnce();
  });

  it("rejects empty human input and displays overall completion only after ready", async () => {
    const resume = vi.fn();
    const view = render(
      <TaskCoordinationDetails
        scope={scope}
        isCoding={false}
        onContinue={resume}
      />,
    );
    await userEvent.click(
      screen.getByRole("button", { name: "taskQueue.coordinationContinue" }),
    );
    await waitFor(() =>
      expect(
        screen.getByLabelText("taskQueue.coordinationInput"),
      ).toHaveAttribute("aria-invalid", "true"),
    );
    expect(resume).not.toHaveBeenCalled();
    view.rerender(
      <TaskCoordinationDetails
        scope={{ ...scope, state: "idle", decision: "ready", question: "" }}
        isCoding={false}
        onContinue={resume}
      />,
    );
    expect(screen.getByText("taskQueue.coordinationReady")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "taskQueue.coordinationContinue" }),
    ).not.toBeInTheDocument();
  });

  it("stops running review directly without a confirmation dialog", async () => {
    const stop = vi.fn().mockResolvedValue(undefined);
    const resume = vi.fn();
    render(
      <TaskCoordinationDetails
        scope={{ ...scope, state: "running", question: "" }}
        isCoding={false}
        onStop={stop}
        onContinue={resume}
      />,
    );
    await userEvent.click(
      screen.getByRole("button", { name: "taskQueue.coordinationStop" }),
    );
    await waitFor(() => expect(stop).toHaveBeenCalledOnce());
    expect(resume).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("can stop an unanswered question and keeps completed work visible", async () => {
    const stop = vi.fn().mockResolvedValue(undefined);
    const resume = vi.fn();
    const view = render(
      <TaskCoordinationDetails
        scope={scope}
        isCoding={false}
        onStop={stop}
        onContinue={resume}
      />,
    );
    await userEvent.click(
      screen.getByRole("button", { name: "taskQueue.coordinationStop" }),
    );
    await waitFor(() => expect(stop).toHaveBeenCalledOnce());
    expect(resume).not.toHaveBeenCalled();
    view.rerender(
      <TaskCoordinationDetails
        scope={{ ...scope, state: "stopped" }}
        isCoding={false}
        onStop={stop}
        onContinue={resume}
      />,
    );
    expect(screen.getByText(scope.summary)).toBeInTheDocument();
    expect(screen.queryByText(scope.question)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "taskQueue.coordinationStop" }),
    ).not.toBeInTheDocument();
  });

  it("disables both actions while a stop is being submitted", async () => {
    let finish!: () => void;
    const stop = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        }),
    );
    render(
      <TaskCoordinationDetails
        scope={scope}
        isCoding={false}
        onStop={stop}
        onContinue={vi.fn()}
      />,
    );
    const stopButton = screen.getByRole("button", {
      name: "taskQueue.coordinationStop",
    });
    await userEvent.click(stopButton);
    expect(stopButton).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "taskQueue.coordinationContinue" }),
    ).toBeDisabled();
    await act(async () => finish());
    expect(stop).toHaveBeenCalledOnce();
  });

  it("shows a stop failure even when no clarification form is open", async () => {
    const stop = vi
      .fn()
      .mockRejectedValue(new Error("The review could not be stopped."));
    render(
      <TaskCoordinationDetails
        scope={{ ...scope, state: "running", question: "" }}
        isCoding={false}
        onStop={stop}
      />,
    );
    await userEvent.click(
      screen.getByRole("button", { name: "taskQueue.coordinationStop" }),
    );
    expect(
      await screen.findByText("The review could not be stopped."),
    ).toBeInTheDocument();
  });
});
