import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import AuthGuard from "../../components/AuthGuard";
import EnterpriseApprove from "./EnterpriseApprove";
import { authApi } from "../../api/modules/auth";
import { getAuthToken } from "../../api/request";
import { enterpriseApi } from "../../api/modules/enterprise";

vi.mock("react-i18next", () => {
  const t = (key: string, values?: { name?: string }) =>
    key === "enterprise.currentAccount"
      ? `Current account: ${values?.name}`
      : key;
  return { useTranslation: () => ({ t }) };
});
vi.mock("../../utils/locale", () => ({
  applyUserLocale: vi.fn().mockResolvedValue(undefined),
}));
vi.mock("../../api/request", () => ({
  getAuthToken: vi.fn(),
  clearAuthToken: vi.fn(),
}));
vi.mock("../../api/modules/auth", () => ({
  authApi: { getAuthStatus: vi.fn(), me: vi.fn(), logout: vi.fn() },
}));
vi.mock("../../api/modules/enterprise", () => ({
  enterpriseApi: {
    devices: vi.fn(),
    inspect: vi.fn(),
    approve: vi.fn(),
    revoke: vi.fn(),
  },
}));

beforeEach(() => {
  vi.clearAllMocks();
  window.history.replaceState(null, "", "/enterprise/approve?code=ABCDEFGH");
  vi.mocked(getAuthToken).mockReturnValue("account-a");
  vi.mocked(authApi.getAuthStatus).mockResolvedValue({
    setup_required: false,
  } as never);
  vi.mocked(authApi.me)
    .mockResolvedValueOnce({
      id: 1,
      username: "member-a",
      display_name: "Member A",
      role: "admin",
      locale: "zh",
      sso_identities: [{ kind: "feishu" }],
    } as never)
    .mockResolvedValueOnce({
      id: 2,
      username: "member-b",
      display_name: "Member B",
      role: "user",
      locale: "zh",
      sso_identities: [{ kind: "feishu" }],
    } as never)
    .mockResolvedValue({
      id: 2,
      username: "member-b",
      display_name: "Member B",
      role: "user",
      locale: "zh",
      sso_identities: [{ kind: "feishu" }],
    } as never);
  vi.mocked(enterpriseApi.devices).mockResolvedValue([]);
  vi.mocked(enterpriseApi.inspect).mockResolvedValue({
    name: "Office computer",
    platform: "web",
    expires_at: 2000000000,
    host_fingerprint: "test",
  });
});
afterEach(() => vi.unstubAllGlobals());

it("shows the new account and privileges before approving after a cross-tab account switch", async () => {
  const realWindow = window;
  const reload = vi.fn();
  vi.stubGlobal(
    "window",
    new Proxy(realWindow, {
      get(target, key) {
        return key === "location"
          ? { ...realWindow.location, reload }
          : Reflect.get(target, key, target);
      },
    }),
  );
  const approvedAs: string[] = [];
  vi.mocked(enterpriseApi.approve).mockImplementation(async () => {
    approvedAs.push(getAuthToken());
  });
  const view = render(
    <MemoryRouter>
      <AuthGuard>
        <EnterpriseApprove />
      </AuthGuard>
    </MemoryRouter>,
  );
  await screen.findByText("Current account: Member A");
  await screen.findByText("Office computer");
  expect(
    screen.getByRole("link", { name: "enterprise.manage" }),
  ).toBeInTheDocument();
  vi.mocked(getAuthToken).mockReturnValue("account-b");
  act(() =>
    window.dispatchEvent(new StorageEvent("storage", { key: "auth_token" })),
  );
  await waitFor(() => expect(reload).toHaveBeenCalledTimes(1));
  expect(screen.queryByText("Current account: Member A")).toBeNull();
  view.unmount();
  render(
    <MemoryRouter>
      <AuthGuard>
        <EnterpriseApprove />
      </AuthGuard>
    </MemoryRouter>,
  );
  await screen.findByText("Current account: Member B");
  await screen.findByText("Office computer");
  expect(screen.queryByText("Current account: Member A")).toBeNull();
  expect(screen.queryByRole("link", { name: "enterprise.manage" })).toBeNull();
  expect(enterpriseApi.inspect).toHaveBeenCalledTimes(2);
  expect(enterpriseApi.approve).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "enterprise.confirm" }));
  await waitFor(() => expect(approvedAs).toEqual(["account-b"]));
});
