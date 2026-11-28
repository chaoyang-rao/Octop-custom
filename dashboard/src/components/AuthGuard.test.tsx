import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";
import AuthGuard from "./AuthGuard";

vi.mock("../api/modules/auth", () => ({
  authApi: {
    getAuthStatus: vi.fn(),
    me: vi.fn(),
  },
}));

vi.mock("../api/request", () => ({
  getAuthToken: vi.fn(() => null),
  clearAuthToken: vi.fn(),
}));

vi.mock("../utils/locale", () => ({
  applyUserLocale: vi.fn(() => Promise.resolve()),
}));

import { authApi } from "../api/modules/auth";
import { getAuthToken } from "../api/request";
import { useCurrentUser } from "../hooks/useCurrentUser";

function IdentityProbe() {
  const user = useCurrentUser();
  return <div>{user?.username}</div>;
}

describe("AuthGuard offline boot", () => {
  afterEach(() => vi.unstubAllGlobals());
  beforeEach(() => {
    vi.mocked(authApi.getAuthStatus).mockReset();
    vi.mocked(authApi.me).mockReset();
    vi.mocked(getAuthToken).mockReset();
    vi.mocked(getAuthToken).mockReturnValue(null);
  });

  it("shows offline panel instead of the protected shell when setup/status fails", async () => {
    vi.mocked(authApi.getAuthStatus).mockRejectedValue(
      new TypeError("Failed to fetch"),
    );

    render(
      <MemoryRouter>
        <AuthGuard>
          <div>protected-shell</div>
        </AuthGuard>
      </MemoryRouter>,
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toBeInTheDocument();
    expect(alert.textContent).toMatch(
      /errors\.offlineTitle|Cannot reach|无法连接/,
    );
    expect(
      screen.getByRole("button", { name: /errors\.retry|Retry|重试/ }),
    ).toBeInTheDocument();
    expect(screen.queryByText("protected-shell")).not.toBeInTheDocument();
  });

  it("keeps the authenticated shell mounted across in-app navigations", async () => {
    vi.mocked(getAuthToken).mockReturnValue("tok");
    vi.mocked(authApi.getAuthStatus).mockResolvedValue({
      setup_required: false,
      has_admin: true,
    } as never);
    vi.mocked(authApi.me).mockResolvedValue({
      user_id: 1,
      username: "admin",
      role: "admin",
      locale: "zh",
    } as never);

    render(
      <MemoryRouter initialEntries={["/a"]}>
        <AuthGuard>
          <Routes>
            <Route
              path="/a"
              element={<Link to="/b">Open protected page</Link>}
            />
            <Route path="/b" element={<div>protected-shell</div>} />
          </Routes>
        </AuthGuard>
      </MemoryRouter>,
    );

    const link = await screen.findByRole("link", {
      name: "Open protected page",
    });
    await userEvent.setup().click(link);
    expect(await screen.findByText("protected-shell")).toBeInTheDocument();
    expect(authApi.getAuthStatus).toHaveBeenCalledTimes(1);
    expect(authApi.me).toHaveBeenCalledTimes(1);
  });

  it("retries auth from the offline panel without leaving a blank shell", async () => {
    vi.mocked(authApi.getAuthStatus)
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValue({
        setup_required: false,
        has_admin: true,
      } as never);
    vi.mocked(getAuthToken).mockReturnValue("tok");
    vi.mocked(authApi.me).mockResolvedValue({
      user_id: 1,
      username: "admin",
      role: "admin",
      locale: "zh",
    } as never);

    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <AuthGuard>
          <div>protected-shell</div>
        </AuthGuard>
      </MemoryRouter>,
    );

    const retry = await screen.findByRole("button", {
      name: /errors\.retry|Retry|重试/,
    });
    await user.click(retry);
    expect(await screen.findByText("protected-shell")).toBeInTheDocument();
  });

  it.each(["storage", "focus"])(
    "refreshes the displayed account after another login on %s",
    async (event) => {
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
      vi.mocked(getAuthToken).mockReturnValue("old-account-token");
      vi.mocked(authApi.getAuthStatus).mockResolvedValue({
        setup_required: false,
      } as never);
      vi.mocked(authApi.me)
        .mockResolvedValueOnce({
          id: 1,
          username: "previous-member",
          locale: "zh",
        } as never)
        .mockResolvedValue({
          id: 2,
          username: "new-member",
          locale: "zh",
        } as never);
      const view = render(
        <MemoryRouter>
          <AuthGuard>
            <IdentityProbe />
          </AuthGuard>
        </MemoryRouter>,
      );
      await screen.findByText("previous-member");
      vi.mocked(getAuthToken).mockReturnValue("new-account-token");
      act(() =>
        window.dispatchEvent(
          event === "storage"
            ? new StorageEvent("storage", { key: "auth_token" })
            : new Event("focus"),
        ),
      );
      await waitFor(() => expect(reload).toHaveBeenCalledTimes(1));
      expect(screen.queryByText("previous-member")).toBeNull();
      expect(authApi.me).toHaveBeenCalledTimes(2);
      view.unmount();
      render(
        <MemoryRouter>
          <AuthGuard>
            <IdentityProbe />
          </AuthGuard>
        </MemoryRouter>,
      );
      await screen.findByText("new-member");
      act(() => window.dispatchEvent(new Event("focus")));
      expect(authApi.me).toHaveBeenCalledTimes(3);
    },
  );

  it("discards the old in-flight identity response after the account changes", async () => {
    let finishOld!: (value: never) => void;
    vi.mocked(getAuthToken).mockReturnValue("old-account-token");
    vi.mocked(authApi.getAuthStatus).mockResolvedValue({
      setup_required: false,
    } as never);
    vi.mocked(authApi.me)
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            finishOld = resolve;
          }),
      )
      .mockResolvedValueOnce({
        id: 2,
        username: "new-member",
        locale: "zh",
      } as never);
    render(
      <MemoryRouter>
        <AuthGuard>
          <IdentityProbe />
        </AuthGuard>
      </MemoryRouter>,
    );
    await waitFor(() => expect(authApi.me).toHaveBeenCalledTimes(1));
    vi.mocked(getAuthToken).mockReturnValue("new-account-token");
    act(() =>
      window.dispatchEvent(new StorageEvent("storage", { key: "auth_token" })),
    );
    await screen.findByText("new-member");
    await act(async () =>
      finishOld({
        id: 1,
        username: "previous-member",
        locale: "zh",
      } as never),
    );
    expect(screen.queryByText("previous-member")).toBeNull();
    expect(screen.getByText("new-member")).toBeInTheDocument();
  });
});
