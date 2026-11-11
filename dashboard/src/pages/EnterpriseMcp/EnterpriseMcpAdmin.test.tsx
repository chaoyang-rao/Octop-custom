import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import EnterpriseMcpAdmin from "./EnterpriseMcpAdmin";
import {
  enterpriseMcpApi,
  type EnterpriseMcpAdminState,
} from "../../api/modules/enterpriseMcp";

vi.mock("react-i18next", () => {
  const t = (key: string, options?: { revision?: number }) =>
    options?.revision != null ? `${key}:${options.revision}` : key;
  return { useTranslation: () => ({ t }) };
});
vi.mock("../../api/modules/enterpriseMcp", () => ({
  enterpriseMcpApi: {
    adminCatalog: vi.fn(),
    members: vi.fn(),
    saveDraft: vi.fn(),
    publish: vi.fn(),
    rollback: vi.fn(),
  },
}));
vi.mock("../../hooks/useServerTimezone", () => ({
  useServerTimezone: () => "Asia/Shanghai",
}));
vi.mock("../../utils/formatMessageTime", () => ({
  formatServerDateTime: () => "server time",
}));

const entries = [
  {
    entry_id: "quality",
    display_name: "Quality",
    description: "Read-only",
    url: "https://quality.example/mcp",
    auth_kind: "bearer" as const,
    enabled: true,
    allowed_subjects: ["member-a"],
  },
];
const state: EnterpriseMcpAdminState = {
  etag: "etag-2",
  draft: { entries },
  published: {
    schema_version: 1,
    revision: 2,
    checksum: "checksum-2",
    published_at: 1800000000,
    entries,
  },
  history: [
    {
      revision: 1,
      published_at: 1700000000,
      published_by: "admin",
      checksum: "checksum-1",
    },
    {
      revision: 2,
      published_at: 1800000000,
      published_by: "admin",
      checksum: "checksum-2",
    },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  for (const method of Object.values(enterpriseMcpApi))
    vi.mocked(method).mockReset();
  vi.mocked(enterpriseMcpApi.adminCatalog).mockResolvedValue(state);
  vi.mocked(enterpriseMcpApi.members).mockResolvedValue([
    { subject: "member-a", display_name: "Member A" },
    { subject: "member-b", display_name: "Member B" },
  ]);
});

describe("company MCP catalog publishing", { timeout: 15_000 }, () => {
  it("requires an explicit publish action using the current server etag", async () => {
    vi.mocked(enterpriseMcpApi.publish).mockResolvedValue({
      ...state,
      etag: "etag-3",
      published: { ...state.published, revision: 3 },
    });
    render(<EnterpriseMcpAdmin />);
    await screen.findByDisplayValue("Quality");
    expect(enterpriseMcpApi.publish).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "enterpriseMcp.publish" }),
    );
    await waitFor(() =>
      expect(enterpriseMcpApi.publish).toHaveBeenCalledWith("etag-2"),
    );
    expect(
      await screen.findByText("enterpriseMcp.publishedRevision:3"),
    ).toBeInTheDocument();
  });

  it("saves changed definitions without publishing them or including personal credential fields", async () => {
    vi.mocked(enterpriseMcpApi.saveDraft).mockResolvedValue({
      ...state,
      etag: "saved-etag",
      draft: { entries: [{ ...entries[0], display_name: "Updated quality" }] },
    });
    render(<EnterpriseMcpAdmin />);
    const name = await screen.findByLabelText("enterpriseMcp.displayName");
    fireEvent.change(name, { target: { value: "Updated quality" } });
    expect(
      screen.getByRole("button", { name: "enterpriseMcp.publish" }),
    ).toBeDisabled();
    fireEvent.click(
      screen.getByRole("button", { name: "enterpriseMcp.saveDraft" }),
    );
    await waitFor(() =>
      expect(enterpriseMcpApi.saveDraft).toHaveBeenCalledWith(
        [{ ...entries[0], display_name: "Updated quality" }],
        "etag-2",
      ),
    );
    expect(enterpriseMcpApi.publish).not.toHaveBeenCalled();
    expect(screen.queryByLabelText("enterpriseMcp.token")).toBeNull();
    expect(screen.queryByLabelText("enterpriseMcp.password")).toBeNull();
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "enterpriseMcp.publish" }),
      ).toBeEnabled(),
    );
  });

  it("preserves unsaved input after an etag conflict and blocks publishing it", async () => {
    vi.mocked(enterpriseMcpApi.saveDraft).mockRejectedValue(
      new Error(
        JSON.stringify({
          error: {
            code: "ENTERPRISE_MCP_CATALOG_CONFLICT",
            message: "conflict",
          },
        }),
      ),
    );
    render(<EnterpriseMcpAdmin />);
    const name = await screen.findByLabelText("enterpriseMcp.displayName");
    fireEvent.change(name, { target: { value: "My unsaved edit" } });
    fireEvent.click(
      screen.getByRole("button", { name: "enterpriseMcp.saveDraft" }),
    );
    expect(
      await screen.findByText("enterpriseMcp.conflict"),
    ).toBeInTheDocument();
    expect(name).toHaveValue("My unsaved edit");
    expect(
      screen.getByRole("button", { name: "enterpriseMcp.publish" }),
    ).toBeDisabled();
    expect(enterpriseMcpApi.adminCatalog).toHaveBeenCalledOnce();
  });

  it("rejects an invalid URL before saving", async () => {
    render(<EnterpriseMcpAdmin />);
    const url = await screen.findByLabelText("enterpriseMcp.url");
    fireEvent.change(url, { target: { value: "http://quality.example/mcp" } });
    fireEvent.click(
      screen.getByRole("button", { name: "enterpriseMcp.saveDraft" }),
    );
    await screen.findByText("enterpriseMcp.validationHint");
    expect(enterpriseMcpApi.saveDraft).not.toHaveBeenCalled();
    expect(url).toHaveValue("http://quality.example/mcp");
  });

  it("lets administrators choose member names while saving only stable subjects", async () => {
    vi.mocked(enterpriseMcpApi.saveDraft).mockResolvedValue({
      ...state,
      etag: "saved-members",
      draft: {
        entries: [
          { ...entries[0], allowed_subjects: ["member-a", "member-b"] },
        ],
      },
    });
    render(<EnterpriseMcpAdmin />);
    await screen.findByText("Member A");
    fireEvent.mouseDown(
      screen.getByRole("combobox", { name: "enterpriseMcp.audience" }),
    );
    fireEvent.click(await screen.findByText("Member B"));
    fireEvent.click(
      screen.getByRole("button", { name: "enterpriseMcp.saveDraft" }),
    );
    await waitFor(() =>
      expect(enterpriseMcpApi.saveDraft).toHaveBeenCalledWith(
        [{ ...entries[0], allowed_subjects: ["member-a", "member-b"] }],
        "etag-2",
      ),
    );
  });

  it("restores a selected historical version through a new publication", async () => {
    vi.mocked(enterpriseMcpApi.rollback).mockResolvedValue({
      ...state,
      etag: "restored-etag",
      published: { ...state.published, revision: 3 },
    });
    render(<EnterpriseMcpAdmin />);
    await screen.findByDisplayValue("Quality");
    fireEvent.mouseDown(
      screen.getByRole("combobox", { name: "enterpriseMcp.selectVersion" }),
    );
    fireEvent.click(await screen.findByText("enterpriseMcp.historyVersion:1"));
    fireEvent.click(
      screen.getByRole("button", { name: "enterpriseMcp.rollback" }),
    );
    await waitFor(() =>
      expect(enterpriseMcpApi.rollback).toHaveBeenCalledWith(1, "etag-2"),
    );
    expect(
      await screen.findByText("enterpriseMcp.publishedRevision:3"),
    ).toBeInTheDocument();
  });
});
