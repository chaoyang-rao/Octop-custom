import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import MemberAccessAdmin from "./MemberAccessAdmin";
import {
  memberAccessApi,
  type MemberAccessState,
} from "../../api/modules/memberAccess";
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("../../api/modules/memberAccess", () => ({
  memberAccessApi: {
    read: vi.fn(),
    save: vi.fn(),
    choices: vi.fn(),
    connect: vi.fn(),
  },
}));
const state: MemberAccessState = {
  etag: "a".repeat(64),
  configured: true,
  revision: 1,
  mcp_options: [
    {
      entry_id: "aftersales-quality",
      display_name: "memberAccess.aftersales",
      enabled: true,
    },
    {
      entry_id: "quota-workbench",
      display_name: "memberAccess.workbench",
      enabled: true,
    },
    {
      entry_id: "negative-profit",
      display_name: "memberAccess.negative",
      enabled: true,
    },
  ],
  services: [],
  members: [
    {
      user_id: 1,
      username: "alice",
      display_name: "Alice",
      verified: true,
      disabled: false,
      mcp_ids: [],
      companion: false,
    },
    {
      user_id: 2,
      username: "pending",
      display_name: "Pending",
      verified: false,
      disabled: false,
      mcp_ids: [],
      companion: false,
    },
  ],
};
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(memberAccessApi.read).mockResolvedValue(state);
  vi.mocked(memberAccessApi.save).mockResolvedValue(state);
});
it("saves MCP and pet access from a single member row without requesting business credentials", async () => {
  render(<MemberAccessAdmin />);
  fireEvent.click(
    await screen.findByRole("checkbox", {
      name: "Alice memberAccess.aftersales",
    }),
  );
  fireEvent.click(
    screen.getByRole("checkbox", { name: "Alice memberAccess.companion" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "memberAccess.save" }));
  await waitFor(() =>
    expect(memberAccessApi.save).toHaveBeenCalledWith(
      expect.arrayContaining([
        expect.objectContaining({
          user_id: 1,
          mcp_ids: ["aftersales-quality"],
          companion: true,
        }),
      ]),
      state.etag,
    ),
  );
  expect(memberAccessApi.choices).not.toHaveBeenCalled();
  expect(screen.queryByLabelText(/password/i)).toBeNull();
});
it("does not allow opening features for identities that have not completed company login", async () => {
  render(<MemberAccessAdmin />);
  expect(
    await screen.findByRole("checkbox", {
      name: "Pending memberAccess.companion",
    }),
  ).toBeDisabled();
  expect(
    screen.getByRole("checkbox", { name: "Pending memberAccess.negative" }),
  ).toBeDisabled();
});
it("retains edited selections after a concurrent-policy conflict", async () => {
  vi.mocked(memberAccessApi.save).mockRejectedValue(
    new Error("Request failed: 409 Conflict"),
  );
  render(<MemberAccessAdmin />);
  fireEvent.click(
    await screen.findByRole("checkbox", {
      name: "Alice memberAccess.companion",
    }),
  );
  fireEvent.click(screen.getByRole("button", { name: "memberAccess.save" }));
  await screen.findByRole("alert");
  await waitFor(() =>
    expect(
      screen.getByRole("checkbox", { name: "Alice memberAccess.companion" }),
    ).toBeChecked(),
  );
});

it("refreshes catalog MCP columns and saves their IDs while retaining existing grants", async () => {
  vi.mocked(memberAccessApi.read)
    .mockResolvedValueOnce(state)
    .mockResolvedValueOnce({
      ...state,
      mcp_options: [
        { entry_id: "negative-profit", display_name: "负利润", enabled: true },
        { entry_id: "dianjian", display_name: "设备点检 MCP", enabled: true },
        {
          entry_id: "production-dashboard",
          display_name: "一线生产看板 MCP",
          enabled: true,
        },
      ],
      members: state.members.map((row) => ({
        ...row,
        mcp_ids: row.user_id === 1 ? ["negative-profit"] : [],
      })),
    });
  render(<MemberAccessAdmin />);
  await screen.findByRole("checkbox", {
    name: "Alice memberAccess.aftersales",
  });
  fireEvent.click(screen.getByRole("button", { name: "memberAccess.refresh" }));
  fireEvent.click(
    await screen.findByRole("checkbox", { name: "Alice 设备点检 MCP" }),
  );
  expect(screen.getByRole("checkbox", { name: "Alice 负利润" })).toBeChecked();
  expect(
    screen.getByRole("checkbox", { name: "Pending 一线生产看板 MCP" }),
  ).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "memberAccess.save" }));
  await waitFor(() =>
    expect(memberAccessApi.save).toHaveBeenCalledWith(
      expect.arrayContaining([
        expect.objectContaining({
          user_id: 1,
          mcp_ids: ["negative-profit", "dianjian"],
        }),
      ]),
      state.etag,
    ),
  );
  expect(memberAccessApi.choices).not.toHaveBeenCalled();
});

it("refreshes idle forms automatically and preserves unsaved permissions", async () => {
  vi.useFakeTimers();
  try {
    await act(async () => {
      render(<MemberAccessAdmin />);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(memberAccessApi.read).toHaveBeenCalledTimes(2);
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Alice memberAccess.companion" }),
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(memberAccessApi.read).toHaveBeenCalledTimes(2);
    expect(
      screen.getByRole("checkbox", { name: "Alice memberAccess.companion" }),
    ).toBeChecked();
  } finally {
    vi.useRealTimers();
  }
});

it("does not show legacy MCPs when the published catalog is explicitly empty", async () => {
  vi.mocked(memberAccessApi.read).mockResolvedValue({
    ...state,
    mcp_options: [],
  });
  render(<MemberAccessAdmin />);
  await screen.findByRole("checkbox", { name: "Alice memberAccess.companion" });
  expect(
    screen.queryByRole("checkbox", { name: "Alice memberAccess.aftersales" }),
  ).toBeNull();
});

it("keeps an MCP named companion separate from desktop-pet access", async () => {
  vi.mocked(memberAccessApi.read).mockResolvedValue({
    ...state,
    mcp_options: [
      { entry_id: "companion", display_name: "Pet data MCP", enabled: true },
    ],
  });
  render(<MemberAccessAdmin />);
  fireEvent.click(
    await screen.findByRole("checkbox", { name: "Alice Pet data MCP" }),
  );
  expect(
    screen.getByRole("checkbox", { name: "Alice memberAccess.companion" }),
  ).not.toBeChecked();
  fireEvent.click(screen.getByRole("button", { name: "memberAccess.save" }));
  await waitFor(() =>
    expect(memberAccessApi.save).toHaveBeenCalledWith(
      expect.arrayContaining([
        expect.objectContaining({
          user_id: 1,
          mcp_ids: ["companion"],
          companion: false,
        }),
      ]),
      state.etag,
    ),
  );
});
