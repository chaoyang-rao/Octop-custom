import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("../../context/AgentContext", () => ({
  useAgent: () => ({
    agents: [
      {
        agent_id: "expert",
        name: "Expert",
        is_owner: true,
        is_shared: false,
        kind: "expert",
        bridge: null,
      },
    ],
    activeAgentId: "expert",
    refresh: vi.fn(),
  }),
}));

vi.mock("../../layouts/PageShell", () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("../../utils/antdMessage", () => ({
  message: { error: vi.fn(), success: vi.fn() },
}));

vi.mock("../../api/modules/nativeCli", () => ({
  nativeCliApi: { get: vi.fn(), save: vi.fn() },
}));

vi.mock("./ManagedCliPanel", () => ({
  ManagedCliPanel: () => null,
}));

import { nativeCliApi } from "../../api/modules/nativeCli";
import { NativeCliPanel } from "./index";

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(nativeCliApi.get).mockResolvedValue({
    agent_id: "expert",
    can_manage: true,
    enabled: false,
    runner: undefined,
    model_id: undefined,
    mode_id: undefined,
    config_options: {},
    runners: [],
    capabilities: null,
  } as never);
});

it("renders an unprobed expert without dereferencing missing capabilities", async () => {
  render(
    <MemoryRouter>
      <NativeCliPanel />
    </MemoryRouter>,
  );

  await waitFor(() => expect(nativeCliApi.get).toHaveBeenCalledWith("expert"));
  expect(await screen.findByText("nativeCli.execution")).toBeInTheDocument();
  expect(
    screen.queryByRole("combobox", { name: /nativeCli.model/ }),
  ).toBeNull();
});
