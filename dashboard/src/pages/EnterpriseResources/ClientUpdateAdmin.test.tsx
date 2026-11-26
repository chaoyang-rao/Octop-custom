import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import ClientUpdateAdmin from "./ClientUpdateAdmin";
import {
  clientUpdatesApi,
  type ClientUpdateAdmin as AdminState,
} from "../../api/modules/clientUpdates";
import { enterpriseMcpApi } from "../../api/modules/enterpriseMcp";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("../../hooks/useServerTimezone", () => ({
  useServerTimezone: () => "Asia/Shanghai",
}));
vi.mock("../../api/modules/clientUpdates", () => ({
  clientUpdatesApi: {
    admin: vi.fn(),
    releases: vi.fn(),
    import: vi.fn(),
    publish: vi.fn(),
    withdraw: vi.fn(),
  },
}));
vi.mock("../../api/modules/enterpriseMcp", () => ({
  enterpriseMcpApi: { members: vi.fn() },
}));
const option = {
  tag: "custom-1.0.3b3-20261126.1",
  version: "1.0.3b3.post2026112601",
  source_commit: "a".repeat(40),
  notes: "Combined release",
};
const state: AdminState = {
  etag: "b".repeat(64),
  revision: 1,
  signing_configured: true,
  draft: { ...option, companion: { ...option, version: "0.10.0" } },
  published: null,
  history: [],
  devices: [],
};
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(clientUpdatesApi.admin).mockResolvedValue(state);
  vi.mocked(clientUpdatesApi.publish).mockResolvedValue(state);
  vi.mocked(enterpriseMcpApi.members).mockResolvedValue([]);
});
it("publishes the selected client and companion together with one audience and one revision check", async () => {
  render(<ClientUpdateAdmin />);
  expect(await screen.findByText(/0\.10\.0/)).toBeInTheDocument();
  fireEvent.click(
    await screen.findByRole("button", {
      name: "clientUpdates.publishTogether",
    }),
  );
  await waitFor(() =>
    expect(clientUpdatesApi.publish).toHaveBeenCalledExactlyOnceWith(
      state.etag,
      [],
    ),
  );
  expect(clientUpdatesApi.import).not.toHaveBeenCalled();
});
it("clearly marks a legacy client-only draft instead of claiming that it includes the companion", async () => {
  vi.mocked(clientUpdatesApi.admin).mockResolvedValue({
    ...state,
    draft: option,
  });
  render(<ClientUpdateAdmin />);
  expect(
    await screen.findByText("clientUpdates.companionMissing"),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "clientUpdates.publishTogether" }),
  ).toBeNull();
});
