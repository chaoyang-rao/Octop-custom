import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

vi.mock("../../api/modules/mobileAccess", () => ({
  mobileAccessApi: {
    list: vi.fn(),
    inspect: vi.fn(),
    approve: vi.fn(),
    revoke: vi.fn(),
  },
  mobileRemoteApi: {
    status: vi.fn(),
    configure: vi.fn(),
    check: vi.fn(),
    tailscaleStatus: vi.fn(),
    enableTailscale: vi.fn(),
    disableTailscale: vi.fn(),
  },
  mobilePushApi: { status: vi.fn(), configure: vi.fn() },
}));
vi.mock("../../hooks/useCurrentUser", () => ({
  useCurrentUser: () => ({ id: 1, role: "admin", permissions: [] }),
}));
vi.mock("../../hooks/useServerTimezone", () => ({
  useServerTimezone: () => "Asia/Shanghai",
}));
vi.mock("../../layouts/PageShell", () => ({
  default: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
}));

import {
  mobileAccessApi,
  mobileRemoteApi,
  mobilePushApi,
} from "../../api/modules/mobileAccess";
import MobileAccess from ".";

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(mobileAccessApi.list).mockResolvedValue([]);
  vi.mocked(mobileAccessApi.inspect).mockResolvedValue({
    name: "My phone",
    platform: "ios",
    expires_at: 2000000000,
    host_fingerprint: "matching-host",
  });
  vi.mocked(mobileRemoteApi.status).mockResolvedValue({
    public_url: "https://octop.example",
    request_origin: "http://127.0.0.1",
    listener: "http://127.0.0.1:8088",
    native_tls: false,
    tailscale_installed: false,
    last_check: null,
  });
  vi.mocked(mobilePushApi.status).mockResolvedValue({
    apns: false,
    fcm: false,
  });
});

describe("Mobile device approval", () => {
  it("requires inspecting the real requesting device before explicit approval", async () => {
    render(
      <MemoryRouter>
        <MobileAccess />
      </MemoryRouter>,
    );
    await userEvent.type(
      screen.getByLabelText("mobileAccess.pairingCode"),
      "ABCD-EFGH",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "mobileAccess.inspect", exact: true }),
    );
    expect(mobileAccessApi.approve).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("My phone · ios")).toBeInTheDocument();
    expect(
      within(dialog).getByLabelText("mobileAccess.scope.terminal"),
    ).not.toBeChecked();
    await userEvent.click(
      within(dialog).getByRole("button", {
        name: "mobileAccess.approve",
        exact: true,
      }),
    );
    await waitFor(() =>
      expect(mobileAccessApi.approve).toHaveBeenCalledWith("ABCD-EFGH", [
        "chat",
        "files",
        "notifications",
        "tasks",
      ]),
    );
    expect(mobileRemoteApi.enableTailscale).not.toHaveBeenCalled();
    expect(mobilePushApi.configure).not.toHaveBeenCalled();
  });

  it("revokes only the selected device after the user confirms", async () => {
    vi.mocked(mobileAccessApi.list).mockResolvedValue([
      {
        device_id: "device-owned",
        name: "My phone",
        platform: "android",
        scopes: ["chat"],
        created_at: 1700000000,
        expires_at: 2000000000,
        revoked_at: null,
        push_enabled: false,
      },
    ]);
    render(
      <MemoryRouter>
        <MobileAccess />
      </MemoryRouter>,
    );
    await userEvent.click(
      await screen.findByRole("button", {
        name: "mobileAccess.revoke",
        exact: true,
      }),
    );
    expect(mobileAccessApi.revoke).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(
      within(dialog).getByRole("button", {
        name: "mobileAccess.revoke",
        exact: true,
      }),
    );
    await waitFor(() =>
      expect(mobileAccessApi.revoke).toHaveBeenCalledExactlyOnceWith(
        "device-owned",
      ),
    );
  });
});
