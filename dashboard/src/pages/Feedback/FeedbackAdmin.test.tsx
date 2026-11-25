import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import FeedbackAdmin from "./FeedbackAdmin";
import { feedbackApi, type FeedbackRecord } from "../../api/modules/feedback";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("../../hooks/useServerTimezone", () => ({
  useServerTimezone: () => "Asia/Shanghai",
}));
vi.mock("../../api/modules/feedback", () => ({
  feedbackApi: { options: vi.fn(), list: vi.fn(), update: vi.fn() },
}));
const record: FeedbackRecord = {
  feedback_id: "fb_01TEST",
  author_name: "Alice",
  section: "token-usage",
  kind: "problem",
  title: "统计布局异常",
  content: "<script>untrusted text</script>",
  client_version: "1.0.3b3",
  client_platform: "windows",
  status: "new",
  reply: "",
  revision: 4,
  created_at: 1795597200,
  updated_at: 1795597200,
};
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(feedbackApi.options).mockResolvedValue({
    destination: "company",
    local_admin: false,
    sections: [
      { key: "token-usage", label_key: "nav.tokenUsage", path: "/token-usage" },
    ],
  });
  vi.mocked(feedbackApi.list).mockResolvedValue({
    items: [record],
    total: 1,
    limit: 20,
    offset: 0,
  });
  vi.mocked(feedbackApi.update).mockResolvedValue({
    ...record,
    reply: "已经修复。",
    revision: 5,
  });
});
it("shows board, member and feedback details and saves an explicitly entered reply with its revision", async () => {
  render(<FeedbackAdmin company />);
  fireEvent.click(await screen.findByRole("button", { name: record.title }));
  const dialog = screen.getByRole("dialog");
  expect(within(dialog).getByText(/2026/)).toBeInTheDocument();
  expect(within(dialog).getByText(record.content)).toBeInTheDocument();
  expect(dialog.querySelector("script")).toBeNull();
  fireEvent.change(within(dialog).getByLabelText("feedback.reply"), {
    target: { value: "已经修复。" },
  });
  fireEvent.click(within(dialog).getByRole("button", { name: "common.save" }));
  await waitFor(() =>
    expect(feedbackApi.update).toHaveBeenCalledWith(
      record,
      "new",
      "已经修复。",
      true,
    ),
  );
});
it("retains the administrator's reply when the server reports a revision conflict", async () => {
  vi.mocked(feedbackApi.update).mockRejectedValue(
    new Error("revision conflict"),
  );
  render(<FeedbackAdmin company />);
  fireEvent.click(await screen.findByRole("button", { name: record.title }));
  const dialog = screen.getByRole("dialog");
  fireEvent.change(within(dialog).getByLabelText("feedback.reply"), {
    target: { value: "保留未保存的回复" },
  });
  fireEvent.click(within(dialog).getByRole("button", { name: "common.save" }));
  await within(dialog).findByRole("alert");
  expect(within(dialog).getByLabelText("feedback.reply")).toHaveValue(
    "保留未保存的回复",
  );
});
it("sends keyword filters and resets pagination", async () => {
  render(<FeedbackAdmin company />);
  await screen.findByRole("button", { name: record.title });
  const search = screen.getByRole("searchbox", { name: "feedback.search" });
  fireEvent.change(search, { target: { value: "Alice" } });
  fireEvent.keyDown(search, { key: "Enter", code: "Enter" });
  await waitFor(() =>
    expect(feedbackApi.list).toHaveBeenLastCalledWith(
      expect.objectContaining({ q: "Alice", offset: 0 }),
      true,
    ),
  );
});
