import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ChatMessageActions, ConversationAnnotations } from "./index";
import { conversationsApi } from "../../api/modules/conversations";

vi.mock("../../api/modules/conversations", () => ({
  conversationsApi: {
    annotations: vi.fn(),
    resolve: vi.fn(),
    react: vi.fn(),
    side: vi.fn(),
    resumeSide: vi.fn(),
  },
}));

class FakeSocket {
  static instances: FakeSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  sent: string[] = [];
  constructor() {
    FakeSocket.instances.push(this);
    queueMicrotask(() => this.onopen?.());
  }
  send(value: string) {
    this.sent.push(value);
  }
  close() {
    this.onclose?.();
  }
}

beforeEach(async () => {
  vi.clearAllMocks();
  FakeSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeSocket);
  vi.mocked(conversationsApi.annotations).mockResolvedValue({
    reactions: [],
    allowed: ["👍"],
  });
  vi.mocked(conversationsApi.resolve).mockResolvedValue({
    source_thread_id: "thread",
    source_agent_id: "expert",
    message_key: "real-message",
    role: "assistant",
    content: "Verified answer",
  });
  vi.mocked(conversationsApi.side).mockResolvedValue({
    thread_id: "side-thread",
    agent_id: "expert",
    session_key: "expert:dashboard:1:side-unique",
    source_thread_id: "thread",
    copied_messages: 2,
    title: "Side",
    conversation_mode: "ask",
  });
});
afterEach(() => vi.unstubAllGlobals());
const wrapper = ({ children }: { children: React.ReactNode }) => (
  <MemoryRouter>
    <App>{children}</App>
  </MemoryRouter>
);

describe("message actions", () => {
  it("quotes the server-resolved message and retains source identity", async () => {
    const onQuote = vi.fn();
    render(
      <ConversationAnnotations threadId="thread">
        <ChatMessageActions
          agentId="expert"
          threadId="thread"
          messageId="optimistic"
          role="assistant"
          content="Verified answer"
          onQuote={onQuote}
        />
      </ConversationAnnotations>,
      { wrapper },
    );
    fireEvent.click(screen.getByLabelText("conversationLibrary.quote"));
    await waitFor(() => expect(onQuote).toHaveBeenCalledOnce());
    expect(onQuote.mock.calls[0][0].reference).toMatchObject({
      source_thread_id: "thread",
      message: { message_id: "real-message" },
    });
    expect(onQuote.mock.calls[0][0].resolved.content).toBe("Verified answer");
  });

  it("opens a distinct branch but sends no model turn before explicit Send", async () => {
    render(
      <ChatMessageActions
        agentId="expert"
        threadId="thread"
        role="assistant"
        content="Verified answer"
      />,
      { wrapper },
    );
    fireEvent.click(screen.getByLabelText("conversationLibrary.sideQuestion"));
    await screen.findByPlaceholderText("conversationLibrary.sidePlaceholder");
    await waitFor(() => expect(FakeSocket.instances).toHaveLength(1));
    const socket = FakeSocket.instances[0];
    expect(socket.sent.map((row) => JSON.parse(row).type)).toEqual([
      "subscribe",
    ]);
    fireEvent.change(
      screen.getByPlaceholderText("conversationLibrary.sidePlaceholder"),
      { target: { value: "Explain this" } },
    );
    await act(async () =>
      fireEvent.click(screen.getByText("conversationLibrary.send")),
    );
    const turn = socket.sent
      .map((row) => JSON.parse(row))
      .find((row) => row.type === "user_turn");
    expect(turn).toMatchObject({
      thread_id: "side-thread",
      session_key: "expert:dashboard:1:side-unique",
      conversation_mode: "ask",
      text: "Explain this",
    });
    await act(
      async () =>
        socket.onmessage?.({
          data: JSON.stringify({
            type: "token",
            thread_id: "different-thread",
            content: "wrong room",
          }),
        }),
    );
    expect(screen.queryByText("wrong room")).toBeNull();
    await act(
      async () =>
        socket.onmessage?.({
          data: JSON.stringify({
            type: "token",
            thread_id: "side-thread",
            content: "Correct branch answer",
          }),
        }),
    );
    expect(screen.getByText("Correct branch answer")).toBeTruthy();
  });
});
