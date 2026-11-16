import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import DesktopPet from "./DesktopPet";
import { request } from "../api/request";
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("../api/request", () => ({ request: vi.fn() }));
vi.mock("../utils/desktopCompanion", () => ({
  isCompanionSupported: () => true,
}));
beforeEach(() => vi.clearAllMocks());
it("opens the independent pet from the sidebar entry without extra installer or MCP forms", async () => {
  vi.mocked(request)
    .mockResolvedValueOnce({ allowed: true, managed: true, supported: true })
    .mockResolvedValueOnce({
      opened: true,
      installed: true,
      update_pending: false,
      version: "0.4.0",
    });
  render(
    <MemoryRouter initialEntries={["/companion?autostart=1"]}>
      <DesktopPet />
    </MemoryRouter>,
  );
  expect(await screen.findByText("companion.opened")).toBeInTheDocument();
  expect(request).toHaveBeenCalledWith("/companion/launch", {
    method: "POST",
    body: JSON.stringify({ action: "open" }),
  });
});
it("shows the super-administrator access requirement without launching an unapproved pet", async () => {
  vi.mocked(request).mockResolvedValueOnce({
    allowed: false,
    managed: true,
    supported: true,
  });
  render(
    <MemoryRouter initialEntries={["/companion?autostart=1"]}>
      <DesktopPet />
    </MemoryRouter>,
  );
  expect(await screen.findByText("companion.notOpened")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "companion.open" })).toBeDisabled();
  expect(request).toHaveBeenCalledTimes(1);
});
