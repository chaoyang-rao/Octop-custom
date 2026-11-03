import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useDashboardPushToast } from "./useDashboardPushToast";

const effects = vi.hoisted(() => ({
  open: vi.fn(),
  destroy: vi.fn(),
  navigate: vi.fn(),
  refresh: vi.fn(),
  invalidateHistory: vi.fn(),
  emitSessionEvent: vi.fn(),
}));
vi.mock("antd", () => ({
  App: {
    useApp: () => ({
      notification: { open: effects.open, destroy: effects.destroy },
    }),
  },
}));
vi.mock("react-router-dom", () => ({ useNavigate: () => effects.navigate }));
vi.mock("../api/request", () => ({
  getAuthToken: () => "synthetic-test-session",
}));
vi.mock("../api/modules/wsNotifications", () => ({
  buildDashboardNotifyWsUrl: () => "ws://localhost/notifications",
}));
vi.mock("../context/AgentContext", () => ({
  useAgent: () => ({ agents: [], refresh: effects.refresh }),
}));
vi.mock("../pages/Experts/components/iconForName", () => ({
  ExpertIcon: () => null,
}));
vi.mock("../pages/Chat/hooks/chatStore", () => ({
  invalidateHistory: effects.invalidateHistory,
  emitSessionEvent: effects.emitSessionEvent,
}));

class TestSocket {
  static OPEN = 1;
  static instances: TestSocket[] = [];
  readyState = 1;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  send = vi.fn();
  close = vi.fn();
  constructor() {
    TestSocket.instances.push(this);
  }
  emit(value: unknown) {
    this.onmessage?.({ data: JSON.stringify(value) });
  }
}

beforeEach(() => {
  vi.clearAllMocks();
  TestSocket.instances = [];
  vi.stubGlobal("WebSocket", TestSocket);
});
afterEach(() => vi.unstubAllGlobals());

describe("dashboard push toast delivery", () => {
  it("refreshes original conversation history without showing a quiet-success toast", () => {
    renderHook(() => useDashboardPushToast());
    act(() =>
      TestSocket.instances[0].emit({
        type: "dashboard_push",
        agent_id: "host",
        thread_id: "original",
        text: "Worker finished",
        toast: false,
        notify: false,
      }),
    );
    expect(effects.refresh).toHaveBeenCalledWith({ silent: true });
    expect(effects.invalidateHistory).toHaveBeenCalledWith("original");
    expect(effects.emitSessionEvent).toHaveBeenCalledWith({
      kind: "sessionsChanged",
      sessionId: "original",
      agentId: "host",
    });
    expect(effects.open).not.toHaveBeenCalled();
  });

  it("keeps the existing visible-toast behavior of notify=false frames", () => {
    renderHook(() => useDashboardPushToast());
    act(() =>
      TestSocket.instances[0].emit({
        type: "dashboard_push",
        agent_id: "host",
        thread_id: "original",
        text: "Approval required",
        notify: false,
      }),
    );
    expect(effects.invalidateHistory).toHaveBeenCalledWith("original");
    expect(effects.open).toHaveBeenCalledOnce();
  });
});
