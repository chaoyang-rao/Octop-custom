import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import EnterpriseApprove from "./EnterpriseApprove";
import { enterpriseApi } from "../../api/modules/enterprise";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
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
  vi.mocked(enterpriseApi.devices).mockResolvedValue([]);
  vi.mocked(enterpriseApi.inspect).mockResolvedValue({
    name: "Office computer",
    platform: "web",
    expires_at: 2000000000,
    host_fingerprint: "test",
  });
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
