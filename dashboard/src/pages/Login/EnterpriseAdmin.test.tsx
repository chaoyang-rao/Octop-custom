import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import EnterpriseAdmin from "./EnterpriseAdmin";

const profile = vi.hoisted(() => ({ role: "user" }));
vi.mock("../../hooks/useCurrentUser", () => ({
  useCurrentUser: () => profile,
}));
vi.mock("../Admin/Users", () => ({
  default: () => <div>existing-user-management</div>,
}));
vi.mock("../EnterpriseMcp/EnterpriseMcpAdmin", () => ({
  default: () => <div>company-mcp-management</div>,
}));
vi.mock("../EnterpriseResources/MemberAccessAdmin", () => ({
  default: () => <div>central-member-access</div>,
}));

beforeEach(() => {
  profile.role = "user";
});

it("does not offer catalog publishing to an ordinary member", async () => {
  render(<EnterpriseAdmin />);
  await screen.findByText("existing-user-management");
  expect(
    screen.queryByRole("tab", { name: "enterpriseMcp.adminTitle" }),
  ).toBeNull();
  expect(screen.queryByText("company-mcp-management")).toBeNull();
});

it("opens unified member access by default for a super-administrator", async () => {
  profile.role = "admin";
  render(<EnterpriseAdmin />);
  expect(await screen.findByText("central-member-access")).toBeInTheDocument();
  expect(
    screen.getByRole("tab", { name: "memberAccess.title" }),
  ).toHaveAttribute("aria-selected", "true");
  fireEvent.click(screen.getByRole("tab", { name: "enterprise.manage" }));
  expect(
    await screen.findByText("existing-user-management"),
  ).toBeInTheDocument();
});
