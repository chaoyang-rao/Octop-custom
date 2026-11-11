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

it("opens the company catalog in the existing authority administration page for an administrator", async () => {
  profile.role = "admin";
  render(<EnterpriseAdmin />);
  await screen.findByText("existing-user-management");
  fireEvent.click(
    screen.getByRole("tab", { name: "enterpriseMcp.adminTitle" }),
  );
  expect(await screen.findByText("company-mcp-management")).toBeInTheDocument();
});
