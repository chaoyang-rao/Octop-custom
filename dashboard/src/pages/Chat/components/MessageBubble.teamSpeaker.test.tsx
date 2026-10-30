import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import MessageBubble from "./MessageBubble";
import type { ChatMessage } from "../hooks/useChat";
import { ChatAgentProfileProvider } from "../ChatAgentProfileContext";

const primaryState = vi.hoisted(() => ({ enabled: false }));
afterEach(() => {
  primaryState.enabled = false;
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { name?: string }) =>
      key === "chat.teamHostHover" || key === "chat.teamPrimaryHostHover"
        ? `[${opts?.name ?? ""}] 主持人`
        : key,
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
    activeAgent: {
      agent_id: "host",
      primary_agent_id: primaryState.enabled ? "doctor" : undefined,
      primary_agent_name: primaryState.enabled ? "小通" : undefined,
      name: "主持团队",
      kind: "team",
      icon_name: "bot",
    },
    agents: [
      {
        agent_id: "host",
        name: "主持团队",
        kind: "team",
        icon_name: "bot",
      },
      {
        agent_id: "doctor",
        name: "小通 · 通用助手",
        icon_name: "sparkles",
      },
    ],
  }),
}));

function assistant(extra: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: extra.id ?? "m1",
    role: "assistant",
    content: extra.content ?? "please rest",
    status: "done",
    timestamp: Date.now(),
    ...extra,
  };
}

describe("MessageBubble team speaker chrome", () => {
  it("prints the actual member name next to the member reply", () => {
    render(
      <MessageBubble
        message={assistant({ speakerAgentId: "doctor" })}
        agentId="host"
        showAvatar
        groupPosition="only"
      />,
    );

    expect(screen.getByText("please rest")).toBeInTheDocument();
    expect(screen.getByText("小通 · 通用助手")).toHaveClass(
      "octop-member-name",
    );
  });

  it("labels the host avatar as team host and opens a member profile", () => {
    const onOpen = vi.fn();
    const { rerender } = render(
      <ChatAgentProfileProvider canOpen onOpen={onOpen} isTeam>
        <MessageBubble
          message={assistant({ content: "稍等", speakerAgentId: "host" })}
          agentId="host"
          showAvatar
          groupPosition="only"
        />
      </ChatAgentProfileProvider>,
    );
    expect(
      screen.getByRole("button", { name: "[主持团队] 主持人" }),
    ).toBeInTheDocument();

    rerender(
      <ChatAgentProfileProvider canOpen onOpen={onOpen} isTeam>
        <MessageBubble
          message={assistant({ speakerAgentId: "doctor" })}
          agentId="host"
          showAvatar
          groupPosition="only"
        />
      </ChatAgentProfileProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "小通 · 通用助手" }));
    expect(onOpen).toHaveBeenCalledWith("doctor");
  });
  it("uses the real primary avatar and profile for a legacy team host reply", () => {
    primaryState.enabled = true;
    const onOpen = vi.fn();
    render(
      <ChatAgentProfileProvider canOpen onOpen={onOpen} isTeam>
        <MessageBubble
          message={assistant({ speakerAgentId: "host" })}
          agentId="host"
          showAvatar
          groupPosition="only"
        />
      </ChatAgentProfileProvider>,
    );
    expect(
      screen.queryByRole("button", { name: "[主持团队] 主持人" }),
    ).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "[小通 · 通用助手] 主持人" }),
    );
    expect(onOpen).toHaveBeenCalledWith("doctor");
  });
});
