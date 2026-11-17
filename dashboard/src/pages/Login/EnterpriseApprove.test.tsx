import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import EnterpriseApprove from "./EnterpriseApprove";
import { enterpriseApi } from "../../api/modules/enterprise";
import { authApi } from "../../api/modules/auth";
import { clearAuthToken } from "../../api/request";

vi.mock("../../api/modules/auth", () => ({
  authApi: { logout: vi.fn(), startOauthBind: vi.fn() },
}));
vi.mock("../../api/request", () => ({ clearAuthToken: vi.fn() }));

vi.mock("react-i18next", () => {
  const t = (key: string) => key;
  return { useTranslation: () => ({ t }) };
});
vi.mock("../../hooks/useCurrentUser", () => ({
  useCurrentUser: () => ({
    username: "colleague",
    role: "user",
    sso_identities: [{ kind: "feishu" }],
  }),
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
  window.history.replaceState(null, "", "/");
  vi.mocked(enterpriseApi.devices).mockResolvedValue([]);
  vi.mocked(enterpriseApi.inspect).mockResolvedValue({
    name: "Office computer",
    platform: "web",
    expires_at: 2000000000,
    host_fingerprint: "test",
  });
});

afterEach(() => vi.unstubAllGlobals());

it("automatically previews the short code from the link but never approves without a click", async () => {
  window.history.replaceState(null, "", "/enterprise/approve?code=ABCDEFGH");
  render(<EnterpriseApprove />);
  await screen.findByText("Office computer");
  expect(enterpriseApi.inspect).toHaveBeenCalledExactlyOnceWith("ABCDEFGH");
  expect(enterpriseApi.approve).not.toHaveBeenCalled();
  expect(
    screen.queryByRole("button", { name: "enterprise.bindFeishu" }),
  ).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "enterprise.confirm" }));
  await waitFor(() =>
    expect(enterpriseApi.approve).toHaveBeenCalledExactlyOnceWith("ABCDEFGH"),
  );
  expect(screen.getByRole("status").textContent).toContain(
    "enterprise.approved",
  );
});

it("previews the computer before explicit approval and invalidates the preview when the code changes", async () => {
  render(<EnterpriseApprove />);
  const input = screen.getByRole("textbox", { name: "enterprise.codeLabel" });
  fireEvent.change(input, { target: { value: "ABCD-EFGH" } });
  fireEvent.click(screen.getByRole("button", { name: "enterprise.inspect" }));
  await screen.findByText("Office computer");
  expect(enterpriseApi.approve).not.toHaveBeenCalled();
  fireEvent.change(input, { target: { value: "IJKL-MNOP" } });
  expect(
    screen.queryByRole("button", { name: "enterprise.confirm" }),
  ).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "enterprise.inspect" }));
  await screen.findByText("Office computer");
  fireEvent.click(screen.getByRole("button", { name: "enterprise.confirm" }));
  await waitFor(() =>
    expect(enterpriseApi.approve).toHaveBeenCalledExactlyOnceWith("IJKL-MNOP"),
  );
});

it("offers account switching beside the identity and preserves the device code without approving", async () => {
  window.history.replaceState(null, "", "/enterprise/approve?code=ABCD-EFGH");
  const realWindow = window;
  const assign = vi.fn();
  vi.stubGlobal(
    "window",
    new Proxy(realWindow, {
      get(target, key) {
        return key === "location"
          ? { search: realWindow.location.search, assign }
          : Reflect.get(target, key, target);
      },
    }),
  );
  let finishLogout!: () => void;
  vi.mocked(authApi.logout).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finishLogout = resolve;
      }),
  );
  render(<EnterpriseApprove />);
  await screen.findByText("Office computer");
  const button = screen.getByRole("button", {
    name: "enterprise.switchAccount",
  });
  expect(button.closest("details")).toBeNull();
  fireEvent.click(button);
  expect(
    screen.queryByRole("button", { name: "enterprise.confirm" }),
  ).toBeNull();
  expect(button).toBeDisabled();
  await act(async () => finishLogout());
  expect(authApi.logout).toHaveBeenCalledTimes(1);
  expect(clearAuthToken).toHaveBeenCalledTimes(1);
  expect(assign).toHaveBeenCalledExactlyOnceWith(
    "/login?enterprise=1&device_code=ABCDEFGH&switch_account=1",
  );
  expect(enterpriseApi.approve).not.toHaveBeenCalled();
});
