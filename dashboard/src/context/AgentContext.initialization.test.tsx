import * as React from "react";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AgentProvider, useAgent } from "./AgentContext";
const api = vi.hoisted(() => ({ ensure: vi.fn(), list: vi.fn() }));
vi.mock("../api/modules/octopAgents", () => ({
  octopAgentsApi: { ensurePrimary: api.ensure },
}));
vi.mock("../api/modules/agent", () => ({ agentApi: { list: api.list } }));
vi.mock("../hooks/useCurrentUser", () => ({
  useCurrentUser: () => ({ id: 7, role: "user", permissions: [] }),
}));
function Probe() {
  const { activeAgentId, refresh, error } = useAgent();
  return (
    <>
      <div data-testid="active">{activeAgentId}</div>
      <div>{error}</div>
      <button onClick={() => void refresh()}>refresh</button>
    </>
  );
}
const experts = [
  { agent_id: "other", name: "其他专家", state: "running", config: {} },
  {
    agent_id: "main",
    name: "小通",
    state: "running",
    config: {},
    is_team_primary: true,
  },
];
beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  api.list.mockResolvedValue(experts);
  api.ensure.mockResolvedValue({ agent_id: "main", name: "小通" });
});
afterEach(cleanup);
it("initializes a remembered login before listing and prefers primary only without an existing selection", async () => {
  let resolve!: (value: unknown) => void;
  api.ensure.mockImplementationOnce(
    () =>
      new Promise((r) => {
        resolve = r;
      }),
  );
  render(
    <AgentProvider>
      <Probe />
    </AgentProvider>,
  );
  expect(api.ensure).toHaveBeenCalledTimes(1);
  expect(api.list).not.toHaveBeenCalled();
  resolve({ agent_id: "main" });
  await waitFor(() =>
    expect(screen.getByTestId("active").textContent).toBe("main"),
  );
  fireEvent.click(screen.getByText("refresh"));
  await waitFor(() => expect(api.list).toHaveBeenCalledTimes(2));
  expect(api.ensure).toHaveBeenCalledTimes(1);
});
it("retains the selected conversation and keeps existing experts available when initialization fails", async () => {
  localStorage.setItem("octop:active-agent", "other");
  api.ensure.mockRejectedValueOnce(new Error("expert quota reached"));
  render(
    <AgentProvider>
      <Probe />
    </AgentProvider>,
  );
  await waitFor(() =>
    expect(screen.getByTestId("active").textContent).toBe("other"),
  );
  expect(screen.getByText("expert quota reached")).toBeTruthy();
});
