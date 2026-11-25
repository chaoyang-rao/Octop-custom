import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import type { ReactNode } from "react";
import EnterpriseResources from "./index";
import ResourceAdmin from "./Admin";
import {
  resourcesApi,
  type ResourceNodeState,
  type ResourceAdminState,
} from "../../api/modules/enterpriseResources";
import { enterpriseMcpApi } from "../../api/modules/enterpriseMcp";
vi.mock("react-i18next", () => {
  const t = (key: string, values?: Record<string, unknown>) =>
    values?.time ? `${key}:${values.time}` : key;
  return { useTranslation: () => ({ t }) };
});
vi.mock("../../layouts/PageShell", () => ({
  default: ({
    children,
    actions,
  }: {
    children: ReactNode;
    actions: ReactNode;
  }) => (
    <main>
      {actions}
      {children}
    </main>
  ),
}));
vi.mock("../../hooks/useServerTimezone", () => ({
  useServerTimezone: () => "Asia/Shanghai",
}));
vi.mock("../../utils/formatMessageTime", () => ({
  formatServerDateTime: (v: number, zone: string) => `${v}:${zone}`,
}));
vi.mock("../../api/modules/enterpriseResources", async (original) => ({
  ...(await original<object>()),
  resourcesApi: {
    status: vi.fn(),
    sync: vi.fn(),
    detail: vi.fn(),
    resolve: vi.fn(),
    pause: vi.fn(),
    exports: vi.fn(),
    export: vi.fn(),
    admin: vi.fn(),
    members: vi.fn(),
    bundle: vi.fn(),
    save: vi.fn(),
    assign: vi.fn(),
    publish: vi.fn(),
    remove: vi.fn(),
    rollback: vi.fn(),
  },
}));
vi.mock("../../api/modules/enterpriseMcp", () => ({
  enterpriseMcpApi: { adminCatalog: vi.fn() },
}));
const state: ResourceNodeState = {
  enabled: true,
  revision: 2,
  last_synced_at: 1800000000,
  error: null,
  resources: [
    {
      resource_id: "quality",
      kind: "expert",
      display_name: "Quality",
      enabled: true,
      digest: "b".repeat(64),
      applied_digest: "a".repeat(64),
      target_id: "alice-quality",
      status: "conflict",
      paused: false,
      conflicts: ["SOUL.md"],
      error: null,
    },
  ],
};
const admin: ResourceAdminState = {
  etag: "a".repeat(64),
  draft: [],
  published: { revision: 0, published_at: 0, entries: [] },
  history: [],
};
beforeEach(() => {
  for (const method of Object.values(resourcesApi))
    vi.mocked(method).mockReset();
  vi.mocked(resourcesApi.status).mockResolvedValue(state);
  vi.mocked(resourcesApi.exports).mockResolvedValue([]);
  vi.mocked(resourcesApi.admin).mockResolvedValue(admin);
  vi.mocked(resourcesApi.members).mockResolvedValue([]);
  vi.mocked(enterpriseMcpApi.adminCatalog).mockResolvedValue({
    draft: { entries: [] },
  } as never);
});
describe("company resource member review", { timeout: 15000 }, () => {
  it("requires explicit conflict choices and keeps the comparison open after a stale rejection", async () => {
    vi.mocked(resourcesApi.detail).mockResolvedValue({
      resource_id: "quality",
      ticket: "observed-ticket",
      local_files: { "SOUL.md": btoa("personal") },
      conflicts: [
        {
          path: "SOUL.md",
          base: btoa("original"),
          local: btoa("personal"),
          remote: btoa("company update"),
        },
      ],
    });
    vi.mocked(resourcesApi.resolve).mockRejectedValue(
      new Error("stale observation"),
    );
    render(
      <MemoryRouter>
        <EnterpriseResources />
      </MemoryRouter>,
    );
    await screen.findByText("Quality");
    expect(screen.getByText(/1800000000:Asia\/Shanghai/)).toBeInTheDocument();
    expect(resourcesApi.sync).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "enterpriseResources.resolve" }),
    );
    await screen.findByText("company update");
    const apply = screen.getByRole("button", {
      name: "enterpriseResources.applyChoices",
    });
    expect(apply).toBeDisabled();
    fireEvent.click(screen.getByLabelText("enterpriseResources.keepLocal"));
    fireEvent.click(apply);
    await waitFor(() =>
      expect(resourcesApi.resolve).toHaveBeenCalledWith(
        "quality",
        "observed-ticket",
        { "SOUL.md": "local" },
      ),
    );
    await screen.findAllByText("stale observation");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("personal")).toBeInTheDocument();
  });
  it("pauses only the selected resource and keeps its local target", async () => {
    vi.mocked(resourcesApi.pause).mockResolvedValue({
      ...state,
      resources: [{ ...state.resources[0], paused: true }],
    });
    render(
      <MemoryRouter>
        <EnterpriseResources />
      </MemoryRouter>,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "enterpriseResources.pause" }),
    );
    await waitFor(() =>
      expect(resourcesApi.pause).toHaveBeenCalledWith("quality", true),
    );
    expect(
      await screen.findByText("enterpriseResources.status.paused"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "enterpriseResources.openLocal" }),
    ).toHaveAttribute("href", "/chat/alice-quality");
  });
});
describe("company resource draft publishing", { timeout: 15000 }, () => {
  it("saves portable expert content using the current etag without automatic publication", async () => {
    vi.mocked(resourcesApi.save).mockResolvedValue({
      ...admin,
      etag: "b".repeat(64),
    });
    render(<ResourceAdmin resourceKind="expert" />);
    await screen.findByText("enterpriseResources.emptyDraft");
    fireEvent.click(
      screen.getByRole("button", { name: "enterpriseResources.addExpert" }),
    );
    fireEvent.change(
      await screen.findByLabelText("enterpriseResources.resourceId"),
      { target: { value: "quality" } },
    );
    fireEvent.change(screen.getByLabelText("enterpriseResources.name"), {
      target: { value: "Quality" },
    });
    fireEvent.change(screen.getByLabelText("SOUL.md"), {
      target: { value: "company instructions" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "enterpriseResources.saveDraft" }),
    );
    await waitFor(() => expect(resourcesApi.save).toHaveBeenCalled());
    expect(resourcesApi.save).toHaveBeenCalledWith(
      expect.objectContaining({
        resource_id: "quality",
        kind: "expert",
        display_name: "Quality",
        files: [
          { path: "SOUL.md", content_base64: btoa("company instructions") },
        ],
      }),
      admin.etag,
    );
    expect(resourcesApi.publish).not.toHaveBeenCalled();
  });
});

it("requires a deliberate choice for a file named constructor", async () => {
  vi.mocked(resourcesApi.status).mockResolvedValue({
    ...state,
    resources: [
      { ...state.resources[0], kind: "skill", conflicts: ["constructor"] },
    ],
  });
  vi.mocked(resourcesApi.detail).mockResolvedValue({
    resource_id: "quality",
    ticket: "observed",
    local_files: { constructor: btoa("personal") },
    conflicts: [
      {
        path: "constructor",
        base: btoa("base"),
        local: btoa("personal"),
        remote: btoa("company update"),
      },
    ],
  });
  render(
    <MemoryRouter>
      <EnterpriseResources />
    </MemoryRouter>,
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "enterpriseResources.resolve" }),
  );
  await screen.findByText("company update");
  expect(screen.getByText("constructor")).toBeInTheDocument();
  const apply = screen.getByRole("button", {
    name: "enterpriseResources.applyChoices",
  });
  expect(apply).toBeDisabled();
  expect(resourcesApi.resolve).not.toHaveBeenCalled();
  fireEvent.click(screen.getByLabelText("enterpriseResources.keepLocal"));
  expect(apply).not.toBeDisabled();
});

describe("company resource member assignment", { timeout: 15000 }, () => {
  it.each(["expert", "skill"] as const)(
    "assigns a published %s from its card without publishing content drafts",
    async (kind) => {
      const entry = {
        resource_id: "quality",
        kind,
        display_name: "Quality",
        description: "",
        enabled: true,
        allowed_subjects: [],
        digest: "a".repeat(64),
      };
      const catalog = {
        ...admin,
        draft: [entry],
        published: { ...admin.published, revision: 1, entries: [entry] },
      };
      vi.mocked(resourcesApi.admin).mockResolvedValue(catalog);
      vi.mocked(resourcesApi.members).mockResolvedValue([
        { subject: "alice", display_name: "Alice" },
        { subject: "bob", display_name: "Bob" },
      ]);
      vi.mocked(resourcesApi.assign).mockResolvedValue({
        ...catalog,
        etag: "b".repeat(64),
      });
      render(<ResourceAdmin resourceKind={kind} />);
      fireEvent.click(
        await screen.findByRole("button", {
          name: "enterpriseResources.assignMembers Quality",
        }),
      );
      const dialog = screen.getByRole("dialog");
      fireEvent.click(
        within(dialog).getByRole("radio", {
          name: "enterpriseResources.assignmentSelected",
        }),
      );
      expect(
        within(dialog).getByRole("button", {
          name: "enterpriseResources.assignmentSave",
        }),
      ).toBeDisabled();
      fireEvent.mouseDown(
        within(dialog).getByRole("combobox", {
          name: "enterpriseResources.assignmentRecipients",
        }),
      );
      fireEvent.click(await screen.findByText("Alice"));
      fireEvent.click(
        within(dialog).getByRole("button", {
          name: "enterpriseResources.assignmentSave",
        }),
      );
      await waitFor(() =>
        expect(resourcesApi.assign).toHaveBeenCalledWith(
          "quality",
          { scope: "selected", subjects: ["alice"] },
          catalog.etag,
        ),
      );
      expect(resourcesApi.publish).not.toHaveBeenCalled();
      expect(resourcesApi.save).not.toHaveBeenCalled();
      expect(resourcesApi.bundle).not.toHaveBeenCalled();
    },
  );

  it("opens the published audience and clears selected IDs when choosing all members", async () => {
    const entry = {
      resource_id: "quality",
      kind: "expert" as const,
      display_name: "Quality",
      description: "",
      enabled: true,
      digest: "a".repeat(64),
      allowed_subjects: ["alice"],
    };
    const catalog = {
      ...admin,
      draft: [{ ...entry, allowed_subjects: ["bob"] }],
      published: { ...admin.published, revision: 1, entries: [entry] },
    };
    vi.mocked(resourcesApi.admin).mockResolvedValue(catalog);
    vi.mocked(resourcesApi.members).mockResolvedValue([
      { subject: "alice", display_name: "Alice" },
      { subject: "bob", display_name: "Bob" },
    ]);
    vi.mocked(resourcesApi.assign).mockResolvedValue(catalog);
    render(<ResourceAdmin resourceKind="expert" />);
    fireEvent.click(
      await screen.findByRole("button", {
        name: "enterpriseResources.assignMembers Quality",
      }),
    );
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("Alice")).toBeInTheDocument();
    expect(within(dialog).queryByText("Bob")).toBeNull();
    fireEvent.click(
      within(dialog).getByRole("radio", {
        name: "enterpriseResources.allMembers",
      }),
    );
    fireEvent.click(
      within(dialog).getByRole("button", {
        name: "enterpriseResources.assignmentSave",
      }),
    );
    await waitFor(() =>
      expect(resourcesApi.assign).toHaveBeenCalledWith(
        "quality",
        { scope: "all", subjects: [] },
        catalog.etag,
      ),
    );
  });

  it("retains selected people and keeps the assignment open after a stale rejection", async () => {
    const entry = {
      resource_id: "quality",
      kind: "skill" as const,
      display_name: "Quality",
      description: "",
      enabled: true,
      digest: "a".repeat(64),
      allowed_subjects: ["alice"],
    };
    const catalog = {
      ...admin,
      draft: [entry],
      published: { ...admin.published, revision: 1, entries: [entry] },
    };
    vi.mocked(resourcesApi.admin).mockResolvedValue(catalog);
    vi.mocked(resourcesApi.members).mockResolvedValue([
      { subject: "alice", display_name: "Alice" },
    ]);
    vi.mocked(resourcesApi.assign).mockRejectedValue(
      new Error("stale assignment"),
    );
    render(<ResourceAdmin resourceKind="skill" />);
    fireEvent.click(
      await screen.findByRole("button", {
        name: "enterpriseResources.assignMembers Quality",
      }),
    );
    const dialog = screen.getByRole("dialog");
    fireEvent.click(
      within(dialog).getByRole("button", {
        name: "enterpriseResources.assignmentSave",
      }),
    );
    await within(dialog).findByRole("alert");
    expect(within(dialog).getByText("Alice")).toBeInTheDocument();
    expect(
      within(dialog).getByRole("radio", {
        name: "enterpriseResources.assignmentSelected",
      }),
    ).toBeChecked();
  });
});
