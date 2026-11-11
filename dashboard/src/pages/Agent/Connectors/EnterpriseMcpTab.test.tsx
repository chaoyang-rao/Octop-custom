import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import EnterpriseMcpTab from "./EnterpriseMcpTab";
import {
  enterpriseMcpApi,
  type EnterpriseMcpNodeState,
} from "../../../api/modules/enterpriseMcp";

vi.mock("react-i18next", () => {
  const t = (key: string, options?: { time?: string }) =>
    options?.time ? `${key} ${options.time}` : key;
  return { useTranslation: () => ({ t }) };
});
vi.mock("../../../api/modules/enterpriseMcp", () => ({
  enterpriseMcpApi: {
    nodeStatus: vi.fn(),
    sync: vi.fn(),
    authorize: vi.fn(),
    clearAuthorization: vi.fn(),
  },
}));
vi.mock("../../../hooks/useServerTimezone", () => ({
  useServerTimezone: () => "Asia/Shanghai",
}));
vi.mock("../../../utils/formatMessageTime", () => ({
  formatServerDateTime: (value: number, zone: string) => `${value}:${zone}`,
}));
vi.mock("./customMcpUtils", () => ({ notifyConnectorsChanged: vi.fn() }));

const state: EnterpriseMcpNodeState = {
  enabled: true,
  authority_url: "https://company.example",
  revision: 2,
  last_synced_at: 1800000000,
  sync_error: null,
  pending_apply: false,
  entries: [
    {
      entry_id: "aftersales_quality",
      display_name: "Aftersales",
      description: "Read-only quality tools",
      url: "https://quality.example/mcp",
      auth_kind: "bearer",
      enabled: true,
      allowed_subjects: [],
      server_name: "corp__center__aftersales_quality",
      fingerprint: "a".repeat(64),
      authorized: false,
      needs_reauthorization: false,
    },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  for (const method of Object.values(enterpriseMcpApi))
    vi.mocked(method).mockReset();
  vi.mocked(enterpriseMcpApi.nodeStatus).mockResolvedValue(state);
  vi.mocked(enterpriseMcpApi.sync).mockResolvedValue(state);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("company MCP member configuration", { timeout: 15_000 }, () => {
  it("shows a read-only catalog and server-timezone synchronization status without automatically authorizing", async () => {
    render(<EnterpriseMcpTab />);
    await screen.findByText("Aftersales");
    expect(screen.getByText("https://quality.example/mcp")).toBeInTheDocument();
    expect(screen.getByText(/1800000000:Asia\/Shanghai/)).toBeInTheDocument();
    expect(
      screen.getByText("enterpriseMcp.authorizationRequired"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(enterpriseMcpApi.authorize).not.toHaveBeenCalled();
    expect(enterpriseMcpApi.sync).not.toHaveBeenCalled();
  });

  it("keeps the previous catalog visibly stale when synchronization fails", async () => {
    vi.mocked(enterpriseMcpApi.nodeStatus).mockResolvedValue({
      ...state,
      sync_error: "Company server unavailable",
    });
    render(<EnterpriseMcpTab />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Company server unavailable",
    );
    expect(screen.getByText(/enterpriseMcp.cachedHint/)).toBeInTheDocument();
    expect(screen.getByText("Aftersales")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "enterpriseMcp.syncNow" }),
    );
    await waitFor(() => expect(enterpriseMcpApi.sync).toHaveBeenCalledOnce());
    await waitFor(() =>
      expect(screen.queryByText("Company server unavailable")).toBeNull(),
    );
  });

  it("retains entered credentials after failure and clears them after successful authorization", async () => {
    vi.mocked(enterpriseMcpApi.authorize)
      .mockRejectedValueOnce(new Error("unavailable"))
      .mockResolvedValueOnce({
        ...state,
        entries: [{ ...state.entries[0], authorized: true }],
      });
    render(<EnterpriseMcpTab />);
    fireEvent.click(
      await screen.findByRole("button", { name: "enterpriseMcp.authorize" }),
    );
    const dialog = await screen.findByRole("dialog");
    const token = within(dialog).getByLabelText("enterpriseMcp.token");
    expect(token).toHaveValue("");
    fireEvent.change(token, { target: { value: "member-private-token" } });
    fireEvent.click(
      within(dialog).getByRole("button", {
        name: "enterpriseMcp.saveAuthorization",
      }),
    );
    expect(await within(dialog).findByText("unavailable")).toBeInTheDocument();
    expect(token).toHaveValue("member-private-token");
    fireEvent.click(
      within(dialog).getByRole("button", {
        name: "enterpriseMcp.saveAuthorization",
      }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(enterpriseMcpApi.authorize).toHaveBeenLastCalledWith(
      "aftersales_quality",
      {
        token: "member-private-token",
        expected_fingerprint: state.entries[0].fingerprint,
      },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "enterpriseMcp.updateAuthorization" }),
    );
    expect(await screen.findByLabelText("enterpriseMcp.token")).toHaveValue("");
    expect(document.body.textContent).not.toContain("member-private-token");
  });

  it("sends the member's own username/password without putting them in the catalog", async () => {
    vi.mocked(enterpriseMcpApi.nodeStatus).mockResolvedValue({
      ...state,
      entries: [{ ...state.entries[0], auth_kind: "basic" }],
    });
    vi.mocked(enterpriseMcpApi.authorize).mockResolvedValue({
      ...state,
      entries: [{ ...state.entries[0], auth_kind: "basic", authorized: true }],
    });
    render(<EnterpriseMcpTab />);
    fireEvent.click(
      await screen.findByRole("button", { name: "enterpriseMcp.authorize" }),
    );
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("enterpriseMcp.username"), {
      target: { value: "member" },
    });
    fireEvent.change(within(dialog).getByLabelText("enterpriseMcp.password"), {
      target: { value: " private password " },
    });
    fireEvent.click(
      within(dialog).getByRole("button", {
        name: "enterpriseMcp.saveAuthorization",
      }),
    );
    await waitFor(() =>
      expect(enterpriseMcpApi.authorize).toHaveBeenCalledWith(
        "aftersales_quality",
        {
          username: "member",
          password: " private password ",
          expected_fingerprint: state.entries[0].fingerprint,
        },
      ),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(document.body.textContent).not.toContain("private password");
  });

  it("clears entered credentials if background synchronization changes the authorization target", async () => {
    vi.useFakeTimers();
    const visibility = vi
      .spyOn(document, "visibilityState", "get")
      .mockReturnValue("visible");
    try {
      render(<EnterpriseMcpTab />);
      await act(async () => {});
      fireEvent.click(
        screen.getByRole("button", { name: "enterpriseMcp.authorize" }),
      );
      await act(async () => {});
      fireEvent.change(screen.getByLabelText("enterpriseMcp.token"), {
        target: { value: "secret-for-old-target" },
      });
      vi.mocked(enterpriseMcpApi.nodeStatus).mockResolvedValue({
        ...state,
        entries: [
          {
            ...state.entries[0],
            url: "https://new-quality.example/mcp",
            fingerprint: "b".repeat(64),
          },
        ],
      });
      await act(async () => {
        vi.advanceTimersByTime(15_000);
      });
      await act(async () => {
        vi.advanceTimersByTime(500);
      });
      expect(screen.queryByRole("dialog")).toBeNull();
      expect(
        screen.getByText("enterpriseMcp.authorizationTargetChanged"),
      ).toBeInTheDocument();
      expect(enterpriseMcpApi.authorize).not.toHaveBeenCalled();
      fireEvent.click(
        screen.getByRole("button", { name: "enterpriseMcp.authorize" }),
      );
      await act(async () => {});
      expect(screen.getByLabelText("enterpriseMcp.token")).toHaveValue("");
    } finally {
      visibility.mockRestore();
    }
  });

  it("handles a server target-fingerprint conflict by clearing the form and loading the new target", async () => {
    vi.mocked(enterpriseMcpApi.nodeStatus)
      .mockResolvedValueOnce(state)
      .mockResolvedValueOnce({
        ...state,
        entries: [
          {
            ...state.entries[0],
            url: "https://new-quality.example/mcp",
            fingerprint: "b".repeat(64),
          },
        ],
      });
    vi.mocked(enterpriseMcpApi.authorize).mockRejectedValue(
      new Error(
        JSON.stringify({
          error: {
            code: "ENTERPRISE_MCP_CATALOG_CONFLICT",
            message: "changed target",
          },
        }),
      ),
    );
    render(<EnterpriseMcpTab />);
    fireEvent.click(
      await screen.findByRole("button", { name: "enterpriseMcp.authorize" }),
    );
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("enterpriseMcp.token"), {
      target: { value: "secret-for-old-target" },
    });
    fireEvent.click(
      within(dialog).getByRole("button", {
        name: "enterpriseMcp.saveAuthorization",
      }),
    );
    expect(
      await screen.findByText("enterpriseMcp.authorizationTargetChanged"),
    ).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(enterpriseMcpApi.authorize).toHaveBeenCalledExactlyOnceWith(
      "aftersales_quality",
      { token: "secret-for-old-target", expected_fingerprint: "a".repeat(64) },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "enterpriseMcp.authorize" }),
    );
    expect(await screen.findByLabelText("enterpriseMcp.token")).toHaveValue("");
    expect(
      screen.getAllByText("https://new-quality.example/mcp").length,
    ).toBeGreaterThan(0);
  });

  it.each(["none", "bearer"] as const)(
    "marks a verified reconnection as pending while it remains disconnected until the task boundary (%s)",
    async (authKind) => {
      vi.mocked(enterpriseMcpApi.nodeStatus).mockResolvedValue({
        ...state,
        pending_apply: true,
        entries: [
          {
            ...state.entries[0],
            auth_kind: authKind,
            authorized: true,
            local_disabled: true,
          },
        ],
      });
      render(<EnterpriseMcpTab />);
      expect(
        await screen.findByText("enterpriseMcp.pendingApplyHint"),
      ).toBeInTheDocument();
      expect(screen.queryByText("enterpriseMcp.ready")).toBeNull();
      expect(screen.queryByText("enterpriseMcp.locallyEnabled")).toBeNull();
      expect(
        screen.queryByText("enterpriseMcp.locallyDisconnected"),
      ).toBeNull();
      expect(
        screen.queryByRole("button", {
          name: "enterpriseMcp.enableConnection",
        }),
      ).toBeNull();
    },
  );

  it("blocks authorization for disabled or invalid definitions", async () => {
    vi.mocked(enterpriseMcpApi.nodeStatus).mockResolvedValue({
      ...state,
      entries: [{ ...state.entries[0], configuration_error: "Name collision" }],
    });
    render(<EnterpriseMcpTab />);
    expect(
      await screen.findByRole("button", { name: "enterpriseMcp.authorize" }),
    ).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent("Name collision");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("does not label a credential-free definition as a verified remote authorization", async () => {
    vi.mocked(enterpriseMcpApi.nodeStatus).mockResolvedValue({
      ...state,
      entries: [{ ...state.entries[0], auth_kind: "none", authorized: true }],
    });
    render(<EnterpriseMcpTab />);
    expect(
      await screen.findByText("enterpriseMcp.locallyEnabled"),
    ).toBeInTheDocument();
    expect(screen.queryByText("enterpriseMcp.ready")).toBeNull();
    expect(
      screen.queryByRole("button", { name: "enterpriseMcp.authorize" }),
    ).toBeNull();
  });

  it("enables a disconnected credential-free connection only after explicit local action and keeps ordinary sync disconnected", async () => {
    const disconnected: EnterpriseMcpNodeState = {
      ...state,
      entries: [
        {
          ...state.entries[0],
          auth_kind: "none",
          authorized: false,
          local_disabled: true,
        },
      ],
    };
    vi.mocked(enterpriseMcpApi.nodeStatus).mockResolvedValue(disconnected);
    vi.mocked(enterpriseMcpApi.sync).mockResolvedValue(disconnected);
    vi.mocked(enterpriseMcpApi.authorize).mockResolvedValue({
      ...state,
      entries: [
        {
          ...state.entries[0],
          auth_kind: "none",
          authorized: true,
          local_disabled: false,
        },
      ],
    });
    vi.mocked(enterpriseMcpApi.clearAuthorization).mockResolvedValue(
      disconnected,
    );
    render(<EnterpriseMcpTab />);
    await screen.findByText("enterpriseMcp.locallyDisconnected");
    fireEvent.click(
      screen.getByRole("button", { name: "enterpriseMcp.syncNow" }),
    );
    await waitFor(() => expect(enterpriseMcpApi.sync).toHaveBeenCalledOnce());
    expect(enterpriseMcpApi.authorize).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "enterpriseMcp.enableConnection" }),
      ).toBeEnabled(),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "enterpriseMcp.enableConnection" }),
    );
    expect(
      await screen.findByText("enterpriseMcp.locallyEnabled"),
    ).toBeInTheDocument();
    expect(enterpriseMcpApi.authorize).toHaveBeenCalledExactlyOnceWith(
      "aftersales_quality",
      { expected_fingerprint: "a".repeat(64) },
    );
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: "enterpriseMcp.disconnectLocal" }),
    );
    expect(
      await screen.findByText("enterpriseMcp.locallyDisconnected"),
    ).toBeInTheDocument();
  });

  it("lets a member clear local credentials for a globally disabled definition", async () => {
    const disabled = {
      ...state,
      entries: [{ ...state.entries[0], enabled: false, authorized: false }],
    };
    vi.mocked(enterpriseMcpApi.nodeStatus).mockResolvedValue(disabled);
    vi.mocked(enterpriseMcpApi.clearAuthorization).mockResolvedValue(disabled);
    render(<EnterpriseMcpTab />);
    const clear = await screen.findByRole("button", {
      name: "enterpriseMcp.clearAuthorization",
    });
    expect(clear).toBeEnabled();
    expect(
      screen.getByRole("button", { name: "enterpriseMcp.authorize" }),
    ).toBeDisabled();
    fireEvent.click(clear);
    await waitFor(() =>
      expect(enterpriseMcpApi.clearAuthorization).toHaveBeenCalledWith(
        "aftersales_quality",
      ),
    );
  });

  it("clears only this entry's local authorization", async () => {
    vi.mocked(enterpriseMcpApi.nodeStatus).mockResolvedValue({
      ...state,
      entries: [{ ...state.entries[0], authorized: true }],
    });
    vi.mocked(enterpriseMcpApi.clearAuthorization).mockResolvedValue({
      ...state,
      entries: [{ ...state.entries[0], local_disabled: true }],
    });
    render(<EnterpriseMcpTab />);
    fireEvent.click(
      await screen.findByRole("button", {
        name: "enterpriseMcp.clearAuthorization",
      }),
    );
    await waitFor(() =>
      expect(enterpriseMcpApi.clearAuthorization).toHaveBeenCalledWith(
        "aftersales_quality",
      ),
    );
    expect(
      await screen.findByText("enterpriseMcp.locallyDisconnected"),
    ).toBeInTheDocument();
  });

  it("does not let an older status response overwrite a completed manual synchronization", async () => {
    vi.useFakeTimers();
    const visibility = vi
      .spyOn(document, "visibilityState", "get")
      .mockReturnValue("visible");
    let resolveStatus: (value: EnterpriseMcpNodeState) => void = () => {};
    vi.mocked(enterpriseMcpApi.nodeStatus)
      .mockResolvedValueOnce(state)
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveStatus = resolve;
          }),
      );
    vi.mocked(enterpriseMcpApi.sync).mockResolvedValue({
      ...state,
      entries: [{ ...state.entries[0], display_name: "New catalog" }],
    });
    render(<EnterpriseMcpTab />);
    await act(async () => {});
    expect(screen.getByText("Aftersales")).toBeInTheDocument();
    await act(async () => {
      vi.advanceTimersByTime(15_000);
    });
    expect(enterpriseMcpApi.nodeStatus).toHaveBeenCalledTimes(2);
    fireEvent.click(
      screen.getByRole("button", { name: "enterpriseMcp.syncNow" }),
    );
    await act(async () => {
      await Promise.resolve();
    });
    await act(async () => {
      resolveStatus(state);
    });
    expect(screen.getByText("New catalog")).toBeInTheDocument();
    visibility.mockRestore();
  });
});
