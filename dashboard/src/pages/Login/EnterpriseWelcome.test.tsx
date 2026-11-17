import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import EnterpriseWelcome from "./EnterpriseWelcome";
import { providerApi } from "../../api/modules/provider";
import { octopAgentsApi } from "../../api/modules/octopAgents";

const navigate = vi.hoisted(() => vi.fn());
vi.mock("react-router-dom", () => ({ useNavigate: () => navigate }));
vi.mock("react-i18next", () => {
  const t = (key: string) => key;
  return { useTranslation: () => ({ t }) };
});
vi.mock("../../hooks/useCurrentUser", () => ({
  useCurrentUser: () => ({ display_name: "Colleague", role: "user" }),
}));
vi.mock("../../api/modules/provider", () => ({
  providerApi: { listResolvedModels: vi.fn() },
}));
vi.mock("../../api/modules/octopAgents", () => ({
  octopAgentsApi: { ensurePrimary: vi.fn(), preparationStatus: vi.fn() },
}));

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers();
  vi.mocked(providerApi.listResolvedModels).mockResolvedValue([
    { id: "company-model" },
  ] as never);
  vi.mocked(octopAgentsApi.ensurePrimary).mockResolvedValue({
    agent_id: "primary",
  } as never);
  vi.mocked(octopAgentsApi.preparationStatus).mockResolvedValue({
    agent_id: "primary",
    name: "Primary",
    state: "running",
  });
});
afterEach(() => vi.useRealTimers());

it("enters chat only after the company model and primary expert are ready", async () => {
  vi.mocked(octopAgentsApi.preparationStatus).mockResolvedValueOnce({
    agent_id: "primary",
    name: "Primary",
    state: "starting",
  });
  await act(async () => {
    render(<EnterpriseWelcome />);
  });
  expect(navigate).not.toHaveBeenCalled();
  expect(octopAgentsApi.ensurePrimary).toHaveBeenCalledTimes(1);
  expect(providerApi.listResolvedModels).toHaveBeenCalledTimes(2);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1000);
  });
  expect(navigate).toHaveBeenCalledExactlyOnceWith("/chat/primary", {
    replace: true,
  });
});

it("retries model synchronization without asking the employee for an API key", async () => {
  vi.mocked(providerApi.listResolvedModels).mockResolvedValueOnce([]);
  await act(async () => {
    render(<EnterpriseWelcome />);
  });
  expect(octopAgentsApi.ensurePrimary).not.toHaveBeenCalled();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(3000);
  });
  expect(navigate).toHaveBeenCalledExactlyOnceWith("/chat/primary", {
    replace: true,
  });
});

it("shows recovery guidance on a failed expert and allows retry", async () => {
  vi.mocked(octopAgentsApi.preparationStatus).mockResolvedValueOnce({
    agent_id: "primary",
    name: "Primary",
    state: "failed",
  });
  await act(async () => {
    render(<EnterpriseWelcome />);
  });
  expect(screen.getByRole("alert").textContent).toContain(
    "enterprise.prepareExpertUnavailable",
  );
  expect(navigate).not.toHaveBeenCalled();
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "common.retry" }));
  });
  expect(navigate).toHaveBeenCalledExactlyOnceWith("/chat/primary", {
    replace: true,
  });
});

it("bounds model waiting and stops retries after leaving the page", async () => {
  vi.mocked(providerApi.listResolvedModels).mockResolvedValue([]);
  let unmount: () => void = () => {};
  await act(async () => {
    ({ unmount } = render(<EnterpriseWelcome />));
  });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(93_000);
  });
  expect(screen.getByRole("alert").textContent).toContain(
    "enterprise.prepareModelsUnavailable",
  );
  const calls = vi.mocked(providerApi.listResolvedModels).mock.calls.length;
  unmount();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(10_000);
  });
  expect(providerApi.listResolvedModels).toHaveBeenCalledTimes(calls);
  expect(navigate).not.toHaveBeenCalled();
});
