import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import ClientUpdateNotice from "./ClientUpdateNotice";
import {
  clientUpdatesApi,
  installNativeClientUpdate,
  type ClientUpdateStatus,
} from "../../api/modules/clientUpdates";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("../../hooks/useCurrentUser", () => ({
  useCurrentUser: () => ({ id: 1 }),
}));
vi.mock("../../utils/desktopChrome", () => ({ isDesktopShell: () => true }));
vi.mock("../../api/modules/clientUpdates", () => ({
  clientUpdatesApi: {
    status: vi.fn(),
    check: vi.fn(),
    download: vi.fn(),
    prepare: vi.fn(),
    abort: vi.fn(),
    cancel: vi.fn(),
  },
  installNativeClientUpdate: vi.fn(),
}));
const state: ClientUpdateStatus = {
  supported: true,
  platform: "darwin-arm64",
  current_version: "1.0.3b3.post2026111703",
  revision: 1,
  available: true,
  version: "1.0.3b3.post2026111801",
  notes: "Company release",
  busy: false,
  job: null,
  error_code: null,
  last_check: 1,
};
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(clientUpdatesApi.status).mockResolvedValue(state);
  vi.mocked(clientUpdatesApi.check).mockResolvedValue(state);
});

it("does not install a published update without member confirmation", async () => {
  render(<ClientUpdateNotice />);
  fireEvent.click(
    await screen.findByRole("button", { name: "clientUpdates.viewUpdate" }),
  );
  await screen.findByRole("button", { name: "clientUpdates.upgrade" });
  expect(clientUpdatesApi.download).not.toHaveBeenCalled();
  expect(clientUpdatesApi.prepare).not.toHaveBeenCalled();
  expect(installNativeClientUpdate).not.toHaveBeenCalled();
});

it("keeps installation disabled while expert work is active", async () => {
  vi.mocked(clientUpdatesApi.status).mockResolvedValue({
    ...state,
    busy: true,
    job: {
      id: "a".repeat(32),
      phase: "downloaded",
      downloaded_bytes: 4,
      total_bytes: 4,
      target_version: state.version!,
      error_code: null,
    },
  });
  render(<ClientUpdateNotice />);
  fireEvent.click(
    await screen.findByRole("button", { name: "clientUpdates.viewUpdate" }),
  );
  expect(
    await screen.findByRole("button", { name: "clientUpdates.installRestart" }),
  ).toBeDisabled();
  expect(clientUpdatesApi.prepare).not.toHaveBeenCalled();
});

it("releases the backend reservation when the native installer refuses", async () => {
  const id = "a".repeat(32);
  vi.mocked(clientUpdatesApi.status).mockResolvedValue({
    ...state,
    job: {
      id,
      phase: "downloaded",
      downloaded_bytes: 4,
      total_bytes: 4,
      target_version: state.version!,
      error_code: null,
    },
  });
  vi.mocked(clientUpdatesApi.prepare).mockResolvedValue({ job_id: id });
  vi.mocked(installNativeClientUpdate).mockRejectedValue(
    new Error("native unavailable"),
  );
  vi.mocked(clientUpdatesApi.abort).mockResolvedValue(state);
  render(<ClientUpdateNotice />);
  fireEvent.click(
    await screen.findByRole("button", { name: "clientUpdates.viewUpdate" }),
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "clientUpdates.installRestart" }),
  );
  await waitFor(() => expect(clientUpdatesApi.abort).toHaveBeenCalledWith(id));
  expect(clientUpdatesApi.prepare).toHaveBeenCalledWith(id);
});

it("can reopen the dismissed notice from settings and recheck publication", async () => {
  render(<ClientUpdateNotice />);
  fireEvent.click(
    await screen.findByRole("button", { name: "clientUpdates.later" }),
  );
  expect(
    screen.queryByRole("button", { name: "clientUpdates.viewUpdate" }),
  ).toBeNull();
  fireEvent(window, new Event("octop:show-client-update"));
  await screen.findByRole("button", { name: "clientUpdates.upgrade" });
  expect(clientUpdatesApi.check).toHaveBeenCalledOnce();
});
