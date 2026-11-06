import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import EnterpriseLogin from "./EnterpriseLogin";
import { enterpriseApi } from "../../api/modules/enterprise";
import { getAuthToken } from "../../api/request";

vi.mock("react-i18next", () => {
  const t = (key: string) => key;
  return { useTranslation: () => ({ t }) };
});
vi.mock("../../api/modules/enterprise", () => ({
  enterpriseApi: { begin: vi.fn(), poll: vi.fn() },
}));
vi.mock("../../api/request", () => ({ getAuthToken: vi.fn() }));

const challenge = {
  login_id: "local-secret-not-for-the-address-bar",
  user_code: "ABCD-EFGH",
  verification_uri: "https://company.example/enterprise/approve",
  expires_at: 2000000000,
  interval: 3,
};

describe("enterprise sign-in consent and recovery", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    vi.mocked(getAuthToken).mockReturnValue(null);
    vi.mocked(enterpriseApi.begin).mockResolvedValue(challenge);
    vi.mocked(enterpriseApi.poll).mockResolvedValue({ status: "pending" });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  async function start() {
    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", { name: "enterprise.signIn" }),
      );
    });
  }

  it("starts only after user action and puts only the short code in the UI", async () => {
    render(
      <EnterpriseLogin
        authority="https://company.example"
        onSuccess={vi.fn()}
      />,
    );
    expect(enterpriseApi.begin).not.toHaveBeenCalled();
    await start();
    expect(screen.getByText("ABCD-EFGH")).toBeTruthy();
    expect(
      screen
        .getByRole("link", { name: "enterprise.openCenter" })
        .getAttribute("href"),
    ).toBe(challenge.verification_uri);
    expect(document.body.textContent).not.toContain(challenge.login_id);
    expect(enterpriseApi.begin).toHaveBeenCalledWith(
      "enterprise.deviceName",
      false,
    );
  });

  it("lets the user explicitly choose whether an existing local account is linked", async () => {
    vi.mocked(getAuthToken).mockReturnValue("existing-local-session");
    render(
      <EnterpriseLogin
        authority="https://company.example"
        onSuccess={vi.fn()}
        localLoginAvailable
      />,
    );
    const keep = screen.getByRole("checkbox", {
      name: "enterprise.keepLocalAccount",
    });
    expect((keep as HTMLInputElement).checked).toBe(true);
    fireEvent.click(keep);
    await start();
    expect(enterpriseApi.begin).toHaveBeenCalledWith(
      "enterprise.deviceName",
      false,
    );
  });

  it("stops polling when cancelled", async () => {
    render(
      <EnterpriseLogin
        authority="https://company.example"
        onSuccess={vi.fn()}
      />,
    );
    await start();
    fireEvent.click(screen.getByRole("button", { name: "enterprise.cancel" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000);
    });
    expect(enterpriseApi.poll).not.toHaveBeenCalled();
    expect(
      screen.getByRole("button", { name: "enterprise.signIn" }),
    ).toBeTruthy();
  });

  it("shows both identities and waits for explicit confirmation before linking local data", async () => {
    const success = vi.fn();
    vi.mocked(getAuthToken).mockReturnValue("local-session");
    vi.mocked(enterpriseApi.poll).mockResolvedValueOnce({
      status: "confirm",
      company_name: "Company colleague",
      local_name: "Personal account",
    });
    render(
      <EnterpriseLogin
        authority="https://company.example"
        onSuccess={success}
      />,
    );
    await start();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(success).not.toHaveBeenCalled();
    expect(enterpriseApi.poll).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30000);
    });
    expect(enterpriseApi.poll).toHaveBeenCalledTimes(1);
    vi.mocked(enterpriseApi.poll).mockResolvedValueOnce({
      status: "approved",
      access_token: "local-jwt",
      user: {
        id: 1,
        username: "colleague",
        role: "user",
        display_name: "Company colleague",
        locale: "zh",
        permissions: [],
      },
    });
    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", { name: "enterprise.confirmLink" }),
      );
    });
    expect(enterpriseApi.poll).toHaveBeenLastCalledWith(
      challenge.login_id,
      true,
    );
    expect(success).toHaveBeenCalledExactlyOnceWith("local-jwt", "zh");
  });

  it("completes sign-in once and never replays the completed result", async () => {
    const success = vi.fn();
    vi.mocked(enterpriseApi.poll).mockResolvedValueOnce({
      status: "approved",
      access_token: "local-jwt",
      user: {
        id: 1,
        username: "employee",
        role: "user",
        display_name: "Colleague",
        locale: "zh",
        permissions: [],
      },
    });
    render(
      <EnterpriseLogin
        authority="https://company.example"
        onSuccess={success}
      />,
    );
    await start();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30000);
    });
    expect(success).toHaveBeenCalledExactlyOnceWith("local-jwt", "zh");
    expect(enterpriseApi.poll).toHaveBeenCalledTimes(1);
  });

  it("recovers from an expired code without silently creating a different identity", async () => {
    vi.mocked(enterpriseApi.poll).mockResolvedValue({ status: "expired" });
    render(
      <EnterpriseLogin
        authority="https://company.example"
        onSuccess={vi.fn()}
      />,
    );
    await start();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(screen.getByRole("alert").textContent).toContain(
      "enterprise.expired",
    );
    expect(
      screen.getByRole("button", { name: "enterprise.signIn" }),
    ).toBeTruthy();
  });
});
