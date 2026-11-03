import { describe, expect, it } from "vitest";
import {
  parseDashboardPushFrame,
  truncatePushText,
} from "./dashboardPushToast";

describe("parseDashboardPushFrame", () => {
  it("accepts a dashboard_push frame", () => {
    expect(
      parseDashboardPushFrame({
        type: "dashboard_push",
        agent_id: "a1",
        thread_id: "thr_1",
        text: "记得喝水",
        agent_name: "助手",
      }),
    ).toEqual({
      type: "dashboard_push",
      agent_id: "a1",
      thread_id: "thr_1",
      text: "记得喝水",
      agent_name: "助手",
    });
  });

  it("rejects other frame types and incomplete payloads", () => {
    expect(
      parseDashboardPushFrame({ type: "token", content: "hi" }),
    ).toBeNull();
    expect(
      parseDashboardPushFrame({
        type: "dashboard_push",
        agent_id: "a1",
        text: "x",
      }),
    ).toBeNull();
    expect(parseDashboardPushFrame(null)).toBeNull();
  });

  it("keeps an explicit silent-toast flag", () => {
    const frame = {
      type: "dashboard_push",
      agent_id: "a1",
      thread_id: "thr_1",
      text: "Task complete",
      toast: false,
    };
    expect(parseDashboardPushFrame(frame)).toEqual(frame);
  });

  it.each([undefined, true, null, 0, "false"])(
    "preserves the old event shape for toast=%s",
    (toast) => {
      const frame = {
        type: "dashboard_push",
        agent_id: "a1",
        thread_id: "thr_1",
        text: "Task complete",
      };
      expect(
        parseDashboardPushFrame({ ...frame, toast, notify: false }),
      ).toEqual(frame);
    },
  );
});

describe("truncatePushText", () => {
  it("keeps short text intact", () => {
    expect(truncatePushText("记得喝水")).toBe("记得喝水");
  });

  it("truncates long text with an ellipsis", () => {
    const long = "a".repeat(300);
    const out = truncatePushText(long, 80);
    expect(out.length).toBe(81);
    expect(out.endsWith("…")).toBe(true);
  });
});
