import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const startOauth = vi.hoisted(() => vi.fn());

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: { name?: string }) => options?.name ?? key,
  }),
}));
vi.mock("../../context/ThemeContext", () => ({
  useTheme: () => ({ isDark: false }),
}));
vi.mock("../../api/modules/auth", () => ({
  authApi: {
    getAuthStatus: () => Promise.resolve({ setup_required: false }),
    getOauthStatus: () =>
      Promise.resolve({
        providers: [{ kind: "feishu", enabled: true, display_name: "Feishu" }],
      }),
    getCaptcha: () => Promise.resolve({ provider: "none" }),
    getLdapStatus: () => Promise.resolve({ enabled: false, display_name: "" }),
    getPasskeyLoginStatus: () => Promise.resolve({ passwordless_login: false }),
    startOauth,
  },
}));
vi.mock("../../utils/locale", () => ({
  applyGuestLocale: () => Promise.resolve(),
  applyUserLocale: () => Promise.resolve(),
}));
vi.mock("./CaptchaField", () => ({ default: () => null }));

import LoginPage from "./index";

const authorizeUrl = "https://accounts.feishu.cn/authorize?state=test-state";
const realWindow = window;
let location: {
  href: string;
  origin: string;
  hostname: string;
  protocol: string;
};

describe("SSO when desktop or browser popups are unavailable", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    location = {
      href: "http://localhost:3000/login",
      origin: "http://localhost:3000",
      hostname: "localhost",
      protocol: "http:",
    };
    vi.stubGlobal(
      "window",
      new Proxy(realWindow, {
        get(target, key) {
          return key === "location"
            ? location
            : Reflect.get(target, key, target);
        },
      }),
    );
    startOauth.mockResolvedValue({ authorization_url: authorizeUrl });
    vi.spyOn(realWindow, "setInterval").mockReturnValue(1);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  async function signIn() {
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Feishu" }));
    await waitFor(() =>
      expect(startOauth).toHaveBeenCalledWith("feishu", "/chat"),
    );
  }

  it("continues Feishu authorization in the current window when a popup is blocked", async () => {
    vi.spyOn(realWindow, "open").mockReturnValue(null);
    await signIn();
    await waitFor(() => expect(location.href).toBe(authorizeUrl));
  });

  it("continues in the current window if the popup is already closed", async () => {
    const popup = { closed: true, close: vi.fn() } as unknown as Window;
    vi.spyOn(realWindow, "open").mockReturnValue(popup);
    await signIn();
    await waitFor(() => expect(location.href).toBe(authorizeUrl));
  });

  it("keeps using a functioning popup without navigating the login page", async () => {
    const popup = {
      closed: false,
      location: { href: "about:blank" },
      close: vi.fn(),
    };
    vi.spyOn(realWindow, "open").mockReturnValue(popup as unknown as Window);
    await signIn();
    await waitFor(() => expect(popup.location.href).toBe(authorizeUrl));
    expect(location.href).toBe("http://localhost:3000/login");
  });
});
