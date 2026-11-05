import { render, screen } from "@testing-library/react";
import { App } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";
import UpdateConfig from "./UpdateConfig";

const api = vi.hoisted(() => ({
  getUpdateStatus: vi.fn(),
  triggerUpgrade: vi.fn(),
  checkForUpdates: vi.fn(),
}));
vi.mock("../../../api/modules/update", () => ({ updateApi: api }));
vi.mock("../../../context/ServiceRestartContext", () => ({
  useServiceRestartContext: () => ({
    restartPhase: "idle",
    isRestarting: false,
    requestRestart: vi.fn(),
    executeRestart: vi.fn(),
  }),
}));

describe("UpdateConfig channels", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("offers the custom repository instead of an official installer, even with a stale update flag", async () => {
    api.getUpdateStatus.mockResolvedValue({
      current_version: "1.0.3b3",
      custom_version: "1.0.3b3.post20261106",
      latest_version: "1.0.3b4",
      official_latest_version: "1.0.3b4",
      has_update: true,
      is_editable: false,
      custom_build: true,
      custom_repository_url: "https://github.com/chaoyang-rao/Octop-custom",
    });
    render(
      <App>
        <UpdateConfig />
      </App>,
    );
    expect(await screen.findByText("1.0.3b3.post20261106")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "customUpdate.openRepository" }),
    ).toHaveAttribute("href", "https://github.com/chaoyang-rao/Octop-custom");
    expect(
      screen.queryByRole("button", {
        name: "advancedSettings.update.upgradeButton",
      }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/pip install -U/)).not.toBeInTheDocument();
    expect(api.triggerUpgrade).not.toHaveBeenCalled();
  });

  it("keeps normal upgrade controls for official installations", async () => {
    api.getUpdateStatus.mockResolvedValue({
      current_version: "1.0.3b2",
      latest_version: "1.0.3b3",
      has_update: true,
      is_editable: false,
      custom_build: false,
    });
    render(
      <App>
        <UpdateConfig />
      </App>,
    );
    expect(
      await screen.findByRole("button", {
        name: "advancedSettings.update.upgradeButton",
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "customUpdate.openRepository" }),
    ).not.toBeInTheDocument();
  });
});
