import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("../../api/modules/accountConnections", () => ({
  accountConnectionsApi: {
    vaults: vi.fn(),
    references: vi.fn(),
    requests: vi.fn(),
    approve: vi.fn(),
    reject: vi.fn(),
    saveVault: vi.fn(),
    unlock: vi.fn(),
    lock: vi.fn(),
    disconnect: vi.fn(),
    items: vi.fn(),
    createReference: vi.fn(),
    requestUse: vi.fn(),
    oauthApp: vi.fn(),
    saveOauthApp: vi.fn(),
    deleteOauthApp: vi.fn(),
  },
}));
vi.mock("../../api/modules/connectors", () => ({
  connectorsApi: { catalog: vi.fn() },
}));
vi.mock("../../api/config", () => ({
  getApiUrl: (path: string) => "/api" + path,
}));
vi.mock("../../hooks/useServerTimezone", () => ({
  useServerTimezone: () => "Asia/Shanghai",
}));
import { accountConnectionsApi as api } from "../../api/modules/accountConnections";
import { connectorsApi } from "../../api/modules/connectors";
import { AccountConnectionsPanel } from "./index";

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.vaults).mockResolvedValue([]);
  vi.mocked(api.references).mockResolvedValue([
    {
      reference: "vaultref_owned",
      connection_id: "vault1",
      label: "Owned reference",
      field_name: "password",
    },
  ]);
  vi.mocked(api.requests).mockResolvedValue([
    {
      request_id: "request1",
      reference: "vaultref_owned",
      url: "https://api.example.com/v1/action?mode=one",
      method: "POST",
      purpose: "Reviewed operation",
      state: "pending",
      expires_at: 1890000000,
      approval_token: "synthetic-one-use-approval",
      header_name: "Authorization",
      prefix: "Bearer ",
      body: { reviewed: true },
    },
  ]);
  vi.mocked(api.approve).mockResolvedValue({
    request_id: "request1",
    state: "completed",
    status_code: 204,
  });
  vi.mocked(connectorsApi.catalog).mockResolvedValue([]);
});

describe("Account connection approvals", () => {
  it("requires opening review and an explicit approval, and cancel performs no delivery", async () => {
    render(<AccountConnectionsPanel />);
    await userEvent.click(
      await screen.findByRole("tab", {
        name: "accountConnections.approvals (1)",
      }),
    );
    expect(api.approve).not.toHaveBeenCalled();
    await userEvent.click(
      screen.getByRole("button", { name: "accountConnections.review" }),
    );
    expect(
      screen.getAllByText(/https:\/\/api\.example\.com\/v1\/action\?mode=one/)
        .length,
    ).toBeGreaterThan(0);
    expect(screen.getByText(/"reviewed": true/)).toBeInTheDocument();
    expect(api.approve).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(api.approve).not.toHaveBeenCalled();
    await userEvent.click(
      screen.getByRole("button", { name: "accountConnections.review" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "accountConnections.approveOnce" }),
    );
    await waitFor(() =>
      expect(api.approve).toHaveBeenCalledExactlyOnceWith(
        "request1",
        "synthetic-one-use-approval",
      ),
    );
  });
});
