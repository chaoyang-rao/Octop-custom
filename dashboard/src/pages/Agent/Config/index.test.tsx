import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { createMemoryRouter, Link, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { request } from "../../../api/request";
import { useAgent } from "../../../context/AgentContext";
import { UnsavedChangesProvider } from "../../../context/UnsavedChangesContext";
import AgentConfigPage from "./index";

vi.mock("../../../api/request", () => ({
  request: vi.fn(),
}));

vi.mock("../../../context/AgentContext", () => ({
  useAgent: vi.fn(),
}));

describe("AgentConfigPage", () => {
  const refresh = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    refresh.mockResolvedValue(undefined);
    vi.mocked(request).mockResolvedValue({} as never);
    vi.mocked(useAgent).mockReturnValue({
      activeAgentId: "agent-1",
      activeAgent: {
        max_iters: 20,
        max_input_length: 32000,
        temperature: 0.2,
        top_p: 0.9,
        max_tokens: 2048,
      },
      refresh,
    } as never);
  });
  afterEach(() => vi.unstubAllGlobals());

  it("refreshes the active agent after saving runtime settings", async () => {
    render(<AgentConfigPage />);

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "common.save" }),
      ).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: "common.save" }));

    await waitFor(() => {
      expect(request).toHaveBeenCalledWith(
        "/agents/agent-1",
        expect.objectContaining({ method: "PATCH" }),
      );
      expect(refresh).toHaveBeenCalledWith({ silent: true, force: true });
    });
    expect(request.mock.invocationCallOrder[0]).toBeLessThan(
      refresh.mock.invocationCallOrder[0],
    );
  });

  it("does not refresh when saving fails", async () => {
    vi.mocked(request).mockRejectedValueOnce(new Error("save failed"));
    render(<AgentConfigPage />);

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "common.save" }),
      ).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: "common.save" }));

    await waitFor(() => {
      expect(request).toHaveBeenCalledWith(
        "/agents/agent-1",
        expect.objectContaining({ method: "PATCH" }),
      );
    });
    expect(refresh).not.toHaveBeenCalled();
  });

  it("retains unsaved settings on cancel and allows navigation after saving", async () => {
    // Node's Request rejects the AbortSignal from jsdom. These routes have no loaders.
    vi.stubGlobal(
      "Request",
      class extends Request {
        constructor(
          input: RequestInfo | URL,
          { signal: _signal, ...init }: RequestInit = {},
        ) {
          super(input, init);
        }
      },
    );
    const router = createMemoryRouter(
      [
        {
          path: "*",
          element: (
            <UnsavedChangesProvider>
              <AgentConfigPage />
              <Link to="/experts">Experts</Link>
            </UnsavedChangesProvider>
          ),
        },
      ],
      { initialEntries: ["/agent-config"] },
    );
    render(<RouterProvider router={router} />);

    const field = await screen.findByPlaceholderText(
      "agentConfig.maxItersPlaceholder",
    );
    fireEvent.change(field, { target: { value: "24" } });
    expect(
      window.dispatchEvent(new Event("beforeunload", { cancelable: true })),
    ).toBe(false);

    fireEvent.click(screen.getByRole("link", { name: "Experts" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "common.keepEditing" }));
    expect(router.state.location.pathname).toBe("/agent-config");
    expect(field).toHaveValue("24");

    fireEvent.click(screen.getByRole("link", { name: "Experts" }));
    fireEvent.click(
      screen.getByRole("button", { name: "common.discardChanges" }),
    );
    await waitFor(() =>
      expect(router.state.location.pathname).toBe("/experts"),
    );
    await act(() => router.navigate(-1));
    expect(field).toHaveValue("20");

    fireEvent.change(field, { target: { value: "24" } });
    fireEvent.click(screen.getByRole("button", { name: "common.save" }));
    await waitFor(() => {
      expect(refresh).toHaveBeenCalled();
      expect(
        window.dispatchEvent(new Event("beforeunload", { cancelable: true })),
      ).toBe(true);
    });
    expect(field).toHaveValue("24");

    fireEvent.click(screen.getByRole("link", { name: "Experts" }));
    await waitFor(() =>
      expect(router.state.location.pathname).toBe("/experts"),
    );
  });
});
