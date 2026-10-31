import { beforeEach, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("../../api/modules/nativeCli", () => ({
  nativeCliApi: { models: vi.fn(), save: vi.fn() },
}));

import { nativeCliApi } from "../../api/modules/nativeCli";
import { NativeModelPicker } from "./NativeModelPicker";

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(nativeCliApi.models).mockResolvedValue({
    runner: "fake",
    configured_model_id: "fake-a",
    effective_model_id: "fake-a",
    models: [
      { value: "fake-a", name: "Fake A" },
      { value: "fake-b", name: "Fake B" },
    ],
    has_capabilities: true,
  });
});

it("selects a draft before the first message and retains it when the conversation receives its ID", async () => {
  const change = vi.fn();
  const { rerender } = render(
    <NativeModelPicker agentId="expert" value={null} onChange={change} />,
  );
  await waitFor(() =>
    expect(nativeCliApi.models).toHaveBeenCalledWith("expert", undefined),
  );
  await waitFor(() => expect(screen.getByRole("combobox")).not.toBeDisabled());
  await userEvent.click(screen.getByRole("combobox"));
  await userEvent.click(await screen.findByText("Fake B"));
  expect(change).toHaveBeenCalledExactlyOnceWith("fake-b");
  expect(nativeCliApi.save).not.toHaveBeenCalled();
  rerender(
    <NativeModelPicker
      agentId="expert"
      threadId="new-thread"
      value="fake-b"
      onChange={change}
    />,
  );
  await waitFor(() =>
    expect(nativeCliApi.models).toHaveBeenCalledWith("expert", "new-thread"),
  );
  expect(screen.getAllByText("Fake B").length).toBeGreaterThan(0);
  expect(change).toHaveBeenCalledTimes(1);
  expect(nativeCliApi.save).not.toHaveBeenCalled();
});
