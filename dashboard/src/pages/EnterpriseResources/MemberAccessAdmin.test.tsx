import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
