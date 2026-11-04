import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ScopedMemoryPanel from "./ScopedMemoryPanel";
import type { ScopedMemoryList } from "../../../api/modules/scopedMemory";

const api = vi.hoisted(() => ({
  list: vi.fn(),
  save: vi.fn(),
  retire: vi.fn(),
  revisions: vi.fn(),
}));
vi.mock("../../../api/modules/scopedMemory", () => ({ scopedMemoryApi: api }));
vi.mock("../../../hooks/useServerTimezone", () => ({
  useServerTimezone: () => "Asia/Shanghai",
}));

const result = (assertion = "Confirmed project rule"): ScopedMemoryList => ({
  scope: "project",
  scope_token: "project-scope-token",
  default_scope: "project",
  available_scopes: ["user", "project", "expert", "session"],
  project_name: "Project A",
  items: [
    {
      id: "atom-original",
      assertion,
      created_at: "2026-11-04T01:00:00Z",
      sources: [
        {
          thread_id: "source-thread",
          agent_id: "source-expert",
          title: "Source discussion",
          created_at: "2026-11-04T01:00:00Z",
          origin: "user",
        },
      ],
    },
  ],
  total: 1,
  has_more: false,
});
const wrap = (agentId = "expert-a", threadId = "actual-thread") => (
  <MemoryRouter>
    <ScopedMemoryPanel
      agentId={agentId}
      threadId={threadId}
      onClose={vi.fn()}
    />
  </MemoryRouter>
);

describe("ScopedMemoryPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.list.mockResolvedValue(result());
    api.save.mockResolvedValue({ atom_id: "atom-new" });
  });

  it("links the real source conversation and corrects in the resolved project scope", async () => {
    render(wrap());
    expect(
      await screen.findByText("Confirmed project rule"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Source discussion/ }),
    ).toHaveAttribute("href", "/chat/source-expert/source-thread");
    fireEvent.click(
      screen.getByRole("button", { name: "scopedMemory.correct" }),
    );
    fireEvent.change(
      screen.getByRole("textbox", { name: "scopedMemory.content" }),
      { target: { value: "Corrected project rule" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "common.save" }));
    await waitFor(() =>
      expect(api.save).toHaveBeenCalledWith(
        "expert-a",
        "actual-thread",
        "project",
        "Corrected project rule",
        "project-scope-token",
        "atom-original",
      ),
    );
  });

  it("discards a late response from a different expert and thread", async () => {
    let finish!: (value: ScopedMemoryList) => void;
    api.list.mockImplementationOnce(
      () =>
        new Promise<ScopedMemoryList>((resolve) => {
          finish = resolve;
        }),
    );
    const view = render(wrap("expert-a", "old-thread"));
    await waitFor(() => expect(api.list).toHaveBeenCalled());
    view.rerender(wrap("expert-b", "new-thread"));
    expect(
      await screen.findByText("Confirmed project rule"),
    ).toBeInTheDocument();
    await act(async () => {
      finish(result("Private old project fact"));
    });
    expect(
      screen.queryByText("Private old project fact"),
    ).not.toBeInTheDocument();
    expect(api.list).toHaveBeenLastCalledWith(
      "expert-b",
      "new-thread",
      "auto",
      "",
      0,
      false,
    );
  });

  it("prevents saving when the server cannot authorize the scope", async () => {
    api.list.mockRejectedValue(new Error("Memory unavailable"));
    render(wrap());
    expect(await screen.findByText("Memory unavailable")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "common.save" })).toBeDisabled();
    expect(api.save).not.toHaveBeenCalled();
  });
});
