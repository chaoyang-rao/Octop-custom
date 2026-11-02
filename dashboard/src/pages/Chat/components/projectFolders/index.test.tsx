import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { OctopAgent } from "../../../../context/AgentContext";
import { projectFoldersRequest } from "../../../../api/modules/projectFolders";
import { toSession } from "../../hooks/useSessions";
import { projectSessionListFor } from ".";
import type { ProjectRowProps } from "./project-folders.mjs";

vi.mock("../../../../api/modules/projectFolders", () => ({
  projectFoldersRequest: vi.fn(),
}));
vi.mock("../../../../i18n", async () => {
  const zh = (await import("../../../../locales/zh.json")).default;
  return {
    default: {
      t: (key: string, values?: Record<string, string>) => {
        const label =
          zh.chat.projectFolders[
            key.split(".").pop() as keyof typeof zh.chat.projectFolders
          ];
        return label.replace(
          /\{\{(\w+)\}\}/g,
          (_, name: string) => values?.[name] ?? "",
        );
      },
    },
  };
});
function Row({ session, projectMenuItems }: ProjectRowProps) {
  return (
    <div>
      <span>{session.name}</span>
      {projectMenuItems?.length ? (
        <button
          onClick={() => {
            const item = projectMenuItems[0];
            if (item && "onClick" in item)
              item.onClick?.({ domEvent: { stopPropagation() {} } } as never);
          }}
        >
          move {session.name}
        </button>
      ) : null}
    </div>
  );
}
const ProjectList = projectSessionListFor(Row);
const project = {
  project_path: "/work/project-a",
  project_name: "项目 A",
  created_at: 1,
  thread_count: 1,
};
const thread = {
  thread_id: "one",
  title: "项目会话",
  channel_type: "dashboard",
  last_active: 1,
  created_at: 1,
  project_path: project.project_path,
  project_name: project.project_name,
};
const owner = {
  agent_id: "expert",
  is_owner: true,
  kind: "expert",
} as OctopAgent;
const base = {
  sessions: [toSession(thread)],
  activeId: "one",
  liveWorkingIds: new Set<string>(),
  onSelect: vi.fn(),
  onDelete: vi.fn(),
  onRename: vi.fn(),
  onPin: vi.fn(),
  onFork: vi.fn(),
};

beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  vi.mocked(projectFoldersRequest).mockImplementation(async (url, options) => {
    if (url.endsWith("/projects")) return [project] as never;
    if (options?.method === "POST" && url.endsWith("/threads"))
      return { thread_id: "created" } as never;
    if (url.includes("/threads?")) return [thread] as never;
    return {} as never;
  });
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute("open");
  };
});

describe("canonical project folders", () => {
  it.each([false, true])(
    "preserves groups and project context when compact=%s",
    async (compact) => {
      render(<ProjectList agent={owner} {...base} compact={compact} />);
      await screen.findByRole("region", { name: "项目 A" });
      expect(screen.getByText("项目会话")).toBeInTheDocument();
      fireEvent.click(
        screen.getByRole("button", { name: "在 项目 A 新建对话" }),
      );
      await waitFor(() =>
        expect(base.onSelect).toHaveBeenCalledWith("created", "expert"),
      );
      expect(projectFoldersRequest).toHaveBeenCalledWith(
        "/agents/expert/threads",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ project_path: project.project_path }),
        }),
      );
    },
  );

  it("keeps unsupported bridge experts on ordinary conversations", () => {
    render(<ProjectList agent={{ ...owner, bridge: true }} {...base} />);
    expect(screen.getByText("项目会话")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "添加项目" })).toBeNull();
    expect(projectFoldersRequest).not.toHaveBeenCalled();
  });

  it.each([{ kind: "team" }, { is_owner: false, is_shared: true }])(
    "retains current-user projects for %j without actor overrides",
    async (overrides) => {
      render(<ProjectList agent={{ ...owner, ...overrides }} {...base} />);
      await screen.findByRole("region", { name: "项目 A" });
      expect(projectFoldersRequest).toHaveBeenCalledWith(
        "/agents/expert/projects",
      );
      expect(projectFoldersRequest).toHaveBeenCalledWith(
        "/agents/expert/threads?limit=10000",
      );
      expect(
        vi
          .mocked(projectFoldersRequest)
          .mock.calls.every(([url]) => !String(url).includes("user_id")),
      ).toBe(true);
    },
  );

  it("moves an idle conversation without losing history", async () => {
    render(<ProjectList agent={owner} {...base} />);
    await screen.findByRole("region", { name: "项目 A" });
    fireEvent.click(screen.getByRole("button", { name: "move 项目会话" }));
    const select = screen.getByRole("combobox");
    fireEvent.change(select, { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() =>
      expect(projectFoldersRequest).toHaveBeenCalledWith(
        "/agents/expert/threads/one/project",
        expect.objectContaining({
          method: "PATCH",
          body: JSON.stringify({ project_path: null }),
        }),
      ),
    );
  });

  it("opens the read-only canonical folder picker", async () => {
    vi.mocked(projectFoldersRequest).mockImplementation(async (url) => {
      if (url === "/filesystem/defaults")
        return { browse_roots: ["/work"] } as never;
      if (url.startsWith("/filesystem/dirs"))
        return { path: "/work", entries: [] } as never;
      if (url.endsWith("/projects")) return [project] as never;
      return [thread] as never;
    });
    render(<ProjectList agent={owner} {...base} />);
    await screen.findByRole("region", { name: "项目 A" });
    fireEvent.click(screen.getByRole("button", { name: "添加项目" }));
    fireEvent.click(screen.getByRole("button", { name: "选择文件夹" }));
    await screen.findByText("没有子文件夹，可直接选择当前文件夹。");
    fireEvent.click(screen.getByRole("button", { name: "选择此文件夹" }));
    expect(screen.getByLabelText("本机文件夹路径")).toHaveValue("/work");
    expect(projectFoldersRequest).toHaveBeenCalledWith("/filesystem/defaults");
    expect(projectFoldersRequest).toHaveBeenCalledWith(
      "/filesystem/dirs?path=%2Fwork%2Fproject-a",
    );
  });
});
