import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import EnterpriseApprove from "./EnterpriseApprove";
import { enterpriseApi } from "../../api/modules/enterprise";

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
