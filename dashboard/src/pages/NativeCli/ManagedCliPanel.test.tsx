import { beforeEach, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("../../api/modules/nativeCli", () => ({
  managedCliApi: {
    status: vi.fn(),
    install: vi.fn(),
    activate: vi.fn(),
    rollback: vi.fn(),
  },
}));
import { managedCliApi } from "../../api/modules/nativeCli";
import { ManagedCliPanel } from "./ManagedCliPanel";

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(managedCliApi.status).mockResolvedValue([
    {
      package: "grok",
      label: "Grok",
      license: "Apache-2.0",
      repository: "https://docs.x.ai/build/overview",
      runner: "managed_grok",
      versions: ["1.0.69", "1.0.70"],
      latest_approved: "1.0.70",
      approved: [
        {
          version: "1.0.70",
          url: "https://registry.npmjs.org/pinned.tgz",
          size: 10,
          sha256: "",
          integrity: "sha512-synthetic-official-integrity",
          license_url: "https://www.apache.org/licenses/LICENSE-2.0.txt",
          license_sha256: "fixed-license",
          release_url:
            "https://www.npmjs.com/package/@xai-official/grok/v/1.0.70",
        },
      ],
      supported: true,
      platform: "darwin-arm64",
      installed: [],
      state: { phase: "idle" },
    },
  ]);
  vi.mocked(managedCliApi.install).mockResolvedValue({});
});

it("shows official npm integrity and installs only the explicitly selected reviewed package", async () => {
  const chooseRunner = vi.fn();
  render(<ManagedCliPanel onRunner={chooseRunner} />);
  expect(
    await screen.findByText("sha512-synthetic-official-integrity"),
  ).toBeInTheDocument();
  expect(managedCliApi.install).not.toHaveBeenCalled();
  expect(managedCliApi.activate).not.toHaveBeenCalled();
  await userEvent.click(
    screen.getByRole("button", { name: "nativeCli.installSelected" }),
  );
  await waitFor(() =>
    expect(managedCliApi.install).toHaveBeenCalledExactlyOnceWith(
      "grok",
      "1.0.70",
    ),
  );
  expect(managedCliApi.activate).not.toHaveBeenCalled();
  expect(chooseRunner).not.toHaveBeenCalled();
});
