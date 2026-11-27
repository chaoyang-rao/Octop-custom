import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ChatMessage } from "../hooks/useChat";
import { COLLAPSE_THINKING_TEAM_KEY } from "../hooks/useCollapseThinking";
import AssistantTurnView from "./AssistantTurnView";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: string | { defaultValue?: string }) => {
      if (typeof opts === "string") return opts;
      return opts?.defaultValue ?? key;
    },
  }),
}));

vi.mock("react-router-dom", () => ({
  useNavigate: () => vi.fn(),
}));

vi.mock("../../../hooks/useServerTimezone", () => ({
  useServerTimezone: () => "UTC",
}));

vi.mock("../../../hooks/useCurrentUser", () => ({
  useCurrentUser: () => ({ username: "ada", display_name: "Ada" }),
}));

vi.mock("../../../context/VoiceOutputContext", () => ({
  useVoiceOutputContext: () => ({ speakingId: null, speak: vi.fn() }),
}));

vi.mock("../../../context/AgentContext", () => ({
  useAgent: () => ({
    activeAgentId: "host",
    activeAgent: {
      agent_id: "host",
      name: "主持团队",
      kind: "team",
      icon_name: "bot",
      primary_agent_id: "primary",
      member_ids: ["primary"],
    },
    agents: [
      {
        agent_id: "host",
        name: "主持团队",
        kind: "team",
        icon_name: "bot",
        primary_agent_id: "primary",
        member_ids: ["primary"],
      },
      {
        agent_id: "primary",
        name: "小通",
        is_team_primary: true,
        icon_name: "bot",
      },
    ],
  }),
}));

function message(
  extra: Partial<ChatMessage> & Pick<ChatMessage, "id">,
): ChatMessage {
  return {
    role: "assistant",
    content: "",
    status: "done",
    timestamp: 1,
    ...extra,
  };
}

describe("AssistantTurnView approval", () => {
  it("animates live work and celebrates only a confirmed completion", () => {
    const answer = { id: "answer", content: "回复" };
    const { container, rerender } = render(
      <AssistantTurnView
        messages={[message({ ...answer, durationMs: 830 })]}
      />,
    );
    const current = () =>
      container
        .querySelector("[data-avatar-motion]")
        ?.getAttribute("data-avatar-motion");
    expect(current()).toBe("idle");
    rerender(
      <AssistantTurnView
        isTurnInProgress
        messages={[
          message({
            id: answer.id,
            type: "reasoning",
            content: "考虑下一步",
            status: "streaming",
          }),
        ]}
      />,
    );
    expect(current()).toBe("think");
    rerender(
      <AssistantTurnView
        isTurnInProgress
        messages={[message({ ...answer, status: "streaming" })]}
      />,
    );
    expect(current()).toBe("work");
    rerender(
      <AssistantTurnView
        messages={[message({ ...answer, durationMs: 830 })]}
      />,
    );
    expect(current()).toBe("done");
    rerender(
      <AssistantTurnView
        isTurnInProgress
        messages={[message({ ...answer, status: "streaming" })]}
      />,
    );
    rerender(<AssistantTurnView messages={[message(answer)]} />);
    expect(current()).toBe("idle");
  });

  it("keeps the answer that arrived before the approval card", () => {
    const { container } = render(
      <AssistantTurnView
        messages={[
          message({ id: "text", content: "磁盘还剩 8G" }),
          message({
            id: "tool",
            toolData: { name: "execute", arguments: "{}" },
          }),
          message({
            id: "card",
            hitlData: {
              action_requests: [{ name: "execute", args: { command: "df" } }],
              status: "pending",
            },
          }),
        ]}
      />,
    );

    expect(screen.getByText("磁盘还剩 8G")).toBeInTheDocument();
    expect(screen.getByText("Confirm this action")).toBeInTheDocument();
    expect(
      container.querySelector('[data-avatar-motion="wait"]'),
    ).not.toBeNull();
  });

  it("keeps host wrap-up below the divider and leaves the decision collapsed", () => {
    render(
      <AssistantTurnView
        messages={[
          message({
            id: "wrap",
            content: "今天就到这里",
            teamWrapup: true,
            speakerAgentId: "host",
            decision: {
              model: "laya",
              empty: false,
              parts: [
                { kind: "result", kept: [{ name: "结果充分", score: 0.91 }] },
              ],
            },
          }),
        ]}
      />,
    );

    const badge = screen.getByText("主持人总结");
    const answer = screen.getByText("今天就到这里");
    expect(
      badge.compareDocumentPosition(answer) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(screen.getByText(/决策模型/)).toBeInTheDocument();
    expect(screen.queryByText(/结果充分/)).not.toBeInTheDocument();
  });

  it("does not flash a lone decision row before tools arrive", () => {
    localStorage.setItem(COLLAPSE_THINKING_TEAM_KEY, "true");
    const decision = {
      model: "laya",
      empty: true,
      parts: [],
    };
    const { rerender } = render(
      <AssistantTurnView
        isTurnInProgress
        messages={[
          message({
            id: "pending",
            status: "streaming",
            decision,
          }),
        ]}
      />,
    );
    expect(screen.queryByText(/决策模型/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();

    rerender(
      <AssistantTurnView
        isTurnInProgress
        messages={[
          message({
            id: "pending",
            status: "done",
            decision,
          }),
          message({
            id: "tool",
            status: "streaming",
            toolData: { name: "execute", arguments: "{}" },
          }),
        ]}
      />,
    );
    const summary = screen.getByRole("button", { name: /正在调用工具/ });
    expect(screen.queryByText(/决策模型/)).not.toBeInTheDocument();
    fireEvent.click(summary);
    expect(screen.getByText(/决策模型/)).toBeInTheDocument();
  });
});
