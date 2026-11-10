import { existsSync } from "node:fs";
import { URL as NodeURL } from "node:url";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  status: vi.fn(),
  oauth: vi.fn(),
  dark: false,
}));

vi.mock("../../context/ThemeContext", () => ({
  useTheme: () => ({ isDark: mocks.dark }),
}));
vi.mock("../../api/modules/auth", () => ({
  authApi: {
    getAuthStatus: mocks.status,
    getOauthStatus: mocks.oauth,
    getCaptcha: () => Promise.resolve({ provider: "none" }),
    getLdapStatus: () => Promise.resolve({ enabled: false, display_name: "" }),
    getPasskeyLoginStatus: () => Promise.resolve({ passwordless_login: false }),
  },
}));
vi.mock("../../utils/locale", () => ({
  applyGuestLocale: () => Promise.resolve(),
  applyUserLocale: () => Promise.resolve(),
}));
vi.mock("./CaptchaField", () => ({ default: () => null }));

import LoginPage from "./index";

function renderLogin(path = "/login") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <LoginPage />
    </MemoryRouter>,
  );
}

describe("login configuration discovery", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.dark = false;
    mocks.status.mockResolvedValue({ setup_required: false });
    mocks.oauth.mockResolvedValue({ providers: [] });
  });

  it("does not present password login while the login method is unknown", () => {
    mocks.status.mockReturnValue(new Promise(() => {}));
    renderLogin();
    expect(screen.getByRole("status")).toHaveTextContent(
      "login.checkingConfiguration",
    );
    expect(screen.queryByPlaceholderText("login.username")).toBeNull();
    expect(screen.queryByPlaceholderText("login.password")).toBeNull();
  });

  it("reports a failed configuration request instead of silently showing personal login", async () => {
    mocks.status.mockRejectedValue(new TypeError("Failed to fetch"));
    renderLogin();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "login.configurationUnavailable",
    );
    expect(screen.queryByPlaceholderText("login.username")).toBeNull();
    expect(mocks.oauth).not.toHaveBeenCalled();
  });

  it("recovers to company login after retry without offering a personal account", async () => {
    mocks.status.mockRejectedValueOnce(new Error("unavailable"));
    mocks.status.mockResolvedValueOnce({
      setup_required: false,
      enterprise_login: true,
      enterprise_authority_url: "https://company.example",
    });
    renderLogin();
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "common.retry" }));
    expect(
      await screen.findByRole("button", { name: "enterprise.signIn" }),
    ).toBeInTheDocument();
    expect(screen.getByText("https://company.example")).toBeInTheDocument();
    expect(mocks.status).toHaveBeenCalledTimes(2);
    expect(screen.queryByPlaceholderText("login.username")).toBeNull();
  });

  it("uses company sign-in when the backend enables enterprise login", async () => {
    mocks.status.mockResolvedValue({
      setup_required: false,
      enterprise_login: true,
      enterprise_authority_url: "https://company.example",
    });
    renderLogin();
    expect(
      await screen.findByRole("button", { name: "enterprise.signIn" }),
    ).toBeInTheDocument();
    expect(mocks.oauth).not.toHaveBeenCalled();
    expect(screen.queryByPlaceholderText("login.username")).toBeNull();
  });

  it("keeps the existing local-account verification flow explicit", async () => {
    mocks.status.mockResolvedValue({
      setup_required: false,
      enterprise_login: true,
      enterprise_authority_url: "https://company.example",
      enterprise_local_login: true,
    });
    renderLogin("/login?local_link=1");
    expect(await screen.findByPlaceholderText("login.username")).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "enterprise.signIn" }),
    ).toBeNull();
  });

  it.each([false, true])(
    "loads a logo that actually exists in the shipped public files (dark=%s)",
    async (dark) => {
      mocks.dark = dark;
      renderLogin();
      await screen.findByPlaceholderText("login.username");
      const image = screen.getByRole("img", { name: "Octop" });
      const name = image.getAttribute("src")!.split("/").pop()!;
      expect(
        existsSync(new NodeURL(`../../../public/${name}`, import.meta.url)),
      ).toBe(true);
    },
  );
});
