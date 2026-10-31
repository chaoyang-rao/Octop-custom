import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, renderHook } from "@testing-library/react";
vi.mock("../../api/request", () => ({
  request: vi.fn(() => Promise.resolve()),
  getAuthToken: () => "mock-device-credential",
}));
vi.mock("../../hooks/useCurrentUser", () => ({
  useCurrentUser: () => ({ id: 1 }),
}));
import { request } from "../../api/request";
import { useNotificationPresence } from "./useNotificationPresence";

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-31T10:00:00Z"));
  vi.spyOn(document, "hasFocus").mockReturnValue(true);
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    value: "visible",
  });
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("notification presence", () => {
  it("reports focus/activity only and expires after thirty seconds without input", async () => {
    const { unmount } = renderHook(() => useNotificationPresence());
    expect(request).not.toHaveBeenCalled();
    await act(async () => {
      fireEvent.keyDown(window, { key: "private-input-must-not-travel" });
    });
    const first = vi.mocked(request).mock.calls[0];
    expect(first[0]).toBe("/mobile-access/presence");
    const body = JSON.parse(String(first[1]?.body));
    expect(body.active).toBe(true);
    expect(body.client_id.length).toBeGreaterThan(8);
    expect(String(first[1]?.body)).not.toContain("private-input");
    await act(async () => {
      vi.advanceTimersByTime(31_000);
    });
    const last = vi.mocked(request).mock.calls.at(-1)!;
    expect(JSON.parse(String(last[1]?.body)).active).toBe(false);
    unmount();
  });
});
