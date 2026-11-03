import { describe, expect, it } from "vitest";
import { createInstance } from "i18next";
import zh from "../../locales/zh.json";
import {
  originReturned,
  coordinationNeedsRefresh,
  pullRequestUrl,
  taskActionError,
  taskCreateFromDraft,
} from "./dispatchPresentation";

describe("task creation transport", () => {
  it("keeps general tasks independent of stale coding form values", () => {
    expect(
      taskCreateFromDraft(
        {
          agent_id: "writer",
          title: "Report",
          prompt: "Analyze the report",
          task_kind: "general",
          project_path: "/workspace/old",
          test_commands: "make all",
          publish_pr: true,
        },
        [],
        "source-thread",
      ),
    ).toEqual({
      agent_id: "writer",
      title: "Report",
      prompt: "Analyze the report",
      options: { quiet: false },
      origin_thread_id: "source-thread",
    });
  });

  it("sends trimmed verification commands and explicit PR choice", () => {
    expect(
      taskCreateFromDraft(
        {
          agent_id: "writer",
          title: "Fix",
          prompt: "Fix output",
          task_kind: "coding",
          project_path: "/workspace/app",
          test_commands: " npm test \r\n\n npm run build ",
          publish_pr: true,
        },
        [],
      ).coding,
    ).toEqual({
      project_path: "/workspace/app",
      test_commands: ["npm test", "npm run build"],
      publish_pr: true,
    });
  });

  it("accepts only credential-free GitHub pull-request addresses", () => {
    for (const value of [
      "https://evil.example/project/pull/1",
      "https://user:secret@github.com/example/project/pull/1",
      "javascript:alert(1)",
      "https://github.com/example/project/issues/1",
    ])
      expect(pullRequestUrl(value)).toBeNull();
    expect(pullRequestUrl("https://github.com/example/project/pull/1")).toBe(
      "https://github.com/example/project/pull/1",
    );
  });
});

describe("task return receipts and action errors", () => {
  it("uses event versions for repeated waiting states in the same attempt", () => {
    const dispatch = {
      coding_run: {},
      returned_attempt: 1,
      returned_state: "waiting",
      current_event_id: 12,
      returned_event_id: 11,
    };
    expect(originReturned(dispatch, 1, "waiting")).toBe(false);
    expect(
      originReturned({ ...dispatch, returned_event_id: 12 }, 1, "waiting"),
    ).toBe(true);
  });

  it("uses the old attempt/state receipt only when event versions are absent", () => {
    const dispatch = {
      coding_run: {},
      returned_attempt: 1,
      returned_state: "completed",
    };
    expect(originReturned(dispatch, 1, "completed")).toBe(true);
    expect(originReturned(dispatch, 2, "completed")).toBe(false);
    expect(
      originReturned(
        { ...dispatch, returned_state: "waiting" },
        1,
        "completed",
      ),
    ).toBe(false);
  });

  it("localizes new permission errors and does not expose untranslated keys", async () => {
    const locale = createInstance();
    await locale.init({ lng: "zh", resources: { zh: { translation: zh } } });
    const error = (reason: string, message: string) =>
      new Error(
        JSON.stringify({
          error: {
            code: "SLASH_BAD_ARGS",
            message,
            details: { task_reason: reason },
          },
        }),
      );
    expect(
      taskActionError(
        error("coding_host_permission", "tasks.errors.coding_host_permission"),
        locale.t,
      ),
    ).toBe(zh.taskQueue.errors.coding_host_permission);
    expect(
      taskActionError(error("unknown", "tasks.errors.unknown"), locale.t),
    ).toBe(zh.taskQueue.failed);
    expect(taskActionError(error("unknown", "请刷新后重试。"), locale.t)).toBe(
      "请刷新后重试。",
    );
  });

  it("continues refreshing coordination that still has work or needs human input", () => {
    const base = {
      scope_id: "scope",
      user_id: 1,
      origin_agent_id: "host",
      origin_thread_id: "original",
      review_turns: 1,
      decision: "continue",
      summary: "",
      question: "",
      allow_publish: false,
    };
    for (const state of [
      "pending",
      "running",
      "needs_user",
      "interrupted",
      "idle",
    ] as const)
      expect(coordinationNeedsRefresh({ ...base, state })).toBe(true);
    expect(
      coordinationNeedsRefresh({ ...base, state: "idle", decision: "ready" }),
    ).toBe(false);
    expect(coordinationNeedsRefresh({ ...base, state: "stopped" })).toBe(false);
    expect(coordinationNeedsRefresh(null)).toBe(false);
  });
});
