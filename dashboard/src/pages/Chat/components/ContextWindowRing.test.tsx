import { render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ContextWindowRing from "./ContextWindowRing";

const { contextUsage } = vi.hoisted(() => ({ contextUsage: vi.fn() }));
vi.mock("../../../api/modules/octopThreads", () => ({
  octopThreadsApi: { contextUsage },
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, args?: { used?: string }) =>
      args?.used ? `${key}: ${args.used}` : key,
  }),
}));

describe("actual model context capacity", () => {
  beforeEach(() => contextUsage.mockReset());

  it("uses the actual route capacity for the live token hint", async () => {
    contextUsage.mockResolvedValue({
      max_tokens: 1_000_000,
      used_tokens: 220_000,
      segments: [],
    });
    render(
      <ContextWindowRing
        usedTokens={220_000}
        maxTokens={128_000}
        agentId="team"
        threadId="room"
      />,
    );
    await waitFor(() =>
      expect(
        screen.getByRole("progressbar").getAttribute("aria-valuenow"),
      ).toBe("22"),
    );
  });

  it("shows unknown capacity without inventing a 100 percent reading", async () => {
    contextUsage.mockResolvedValue({
      max_tokens: 0,
      used_tokens: 220_000,
      segments: [],
    });
    render(
      <ContextWindowRing
        usedTokens={220_000}
        maxTokens={128_000}
        agentId="team"
        threadId="room"
      />,
    );
    await waitFor(() => {
      const ring = screen.getByRole("progressbar");
      expect(ring.getAttribute("aria-valuenow")).toBeNull();
      expect(ring.getAttribute("aria-label")).toContain(
        "capacityUnknownTooltip: 220k",
      );
      expect(within(ring).getByText("?")).toBeTruthy();
    });
  });

  it("keeps the primary snapshot separate from a member's streaming hint", async () => {
    contextUsage.mockResolvedValue({
      max_tokens: 1_000_000,
      used_tokens: 220_000,
      segments: [],
    });
    render(
      <ContextWindowRing
        usedTokens={3000}
        maxTokens={128_000}
        agentId="team"
        threadId="room"
      />,
    );
    await waitFor(() =>
      expect(
        screen.getByRole("progressbar").getAttribute("aria-valuenow"),
      ).toBe("22"),
    );
  });

  it("refreshes a changed model budget when streaming ends with unchanged token usage", async () => {
    contextUsage
      .mockResolvedValueOnce({
        max_tokens: 1_000_000,
        used_tokens: 16_000,
        segments: [],
      })
      .mockResolvedValue({
        max_tokens: 32_000,
        used_tokens: 16_000,
        segments: [],
      });
    const view = render(
      <ContextWindowRing
        usedTokens={16_000}
        maxTokens={128_000}
        agentId="team"
        threadId="room"
        isStreaming
      />,
    );
    await waitFor(() =>
      expect(
        screen.getByRole("progressbar").getAttribute("aria-valuenow"),
      ).toBe("2"),
    );
    view.rerender(
      <ContextWindowRing
        usedTokens={16_000}
        maxTokens={128_000}
        agentId="team"
        threadId="room"
        isStreaming={false}
      />,
    );
    await waitFor(() =>
      expect(
        screen.getByRole("progressbar").getAttribute("aria-valuenow"),
      ).toBe("50"),
    );
  });
});
