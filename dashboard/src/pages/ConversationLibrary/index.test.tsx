import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "antd";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { conversationsApi } from "../../api/modules/conversations";
import ConversationLibrary from "./index";

vi.mock("react-i18next", async (importOriginal) => {
  const original = await importOriginal<typeof import("react-i18next")>();
  const t = (key: string) => key;
  return {
    ...original,
    useTranslation: () => ({ t, i18n: { language: "en" } }),
  };
});

vi.mock("../../context/AgentContext", () => ({
  useAgent: () => ({
    agents: [
      { agent_id: "a", name: "Owned expert", is_owner: true },
      { agent_id: "foreign", name: "Foreign expert", is_owner: false },
      {
        agent_id: "remote",
        name: "Remote expert",
        is_owner: true,
        bridge: true,
      },
    ],
    refresh: vi.fn(async () => undefined),
  }),
}));
vi.mock("../../hooks/useServerTimezone", () => ({
  useServerTimezone: () => "Asia/Shanghai",
}));
vi.mock("../../api/modules/conversations", () => ({
  conversationsApi: {
    list: vi.fn(),
    archive: vi.fn(),
    stage: vi.fn(),
    confirm: vi.fn(),
    discard: vi.fn(),
    export: vi.fn(),
  },
}));
const api = vi.mocked(conversationsApi);
beforeEach(() => {
  vi.clearAllMocks();
  api.list.mockResolvedValue({
    conversations: [],
    has_more: false,
    next_offset: 50,
  });
  api.stage.mockResolvedValue({
    id: "preview",
    kind: "transfer",
    state: "preview",
    sha256: "a".repeat(64),
    expires_at: 10,
    omitted_messages: 0,
    ignored_files: 0,
    warnings: [],
    bytes: 10,
    items: [
      {
        key: "source",
        name: "Imported expert",
        messages: 0,
        skills: 0,
        files: 0,
        duplicate: false,
        name_conflict: false,
      },
    ],
  });
  api.confirm.mockResolvedValue({
    agents: [
      { agent_id: "new", name: "Imported expert", source_key: "source" },
    ],
    threads: [],
    skipped: 0,
    warnings: [],
  });
});
const mount = () =>
  render(
    <MemoryRouter>
      <App>
        <ConversationLibrary />
      </App>
    </MemoryRouter>,
  );

describe("conversation library", () => {
  it("previews an uploaded file and requires a distinct confirmation before writing", async () => {
    const { container } = mount();
    await userEvent.click(screen.getByText("conversationLibrary.import"));
    const input = container.ownerDocument.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    fireEvent.change(input, {
      target: {
        files: [new File(["zip"], "export.zip", { type: "application/zip" })],
      },
    });
    await screen.findByDisplayValue("Imported expert");
    expect(api.stage).toHaveBeenCalledOnce();
    expect(api.confirm).not.toHaveBeenCalled();
    await userEvent.click(screen.getByText("conversationLibrary.confirm"));
    await userEvent.click(await screen.findByText("OK"));
    await waitFor(() =>
      expect(api.confirm).toHaveBeenCalledWith(
        "preview",
        expect.objectContaining({ keys: ["source"], include_files: false }),
      ),
    );
  }, 20000);

  it("uses the real archive endpoint and reloads the list", async () => {
    api.list.mockResolvedValueOnce({
      conversations: [
        {
          thread_id: "thread",
          agent_id: "a",
          agent_name: "Owned expert",
          title: "Existing chat",
          kind: "expert",
          archived: false,
          last_active: 10,
          created_at: 10,
        },
      ],
      has_more: false,
      next_offset: 50,
    });
    mount();
    await screen.findByText("Existing chat");
    await userEvent.click(screen.getByText("conversationLibrary.archive"));
    await waitFor(() =>
      expect(api.archive).toHaveBeenCalledWith("thread", true),
    );
    await waitFor(() => expect(screen.queryByText("Existing chat")).toBeNull());
  }, 20000);
});
