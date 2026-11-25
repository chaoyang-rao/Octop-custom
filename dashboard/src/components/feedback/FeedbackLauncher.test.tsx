import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import FeedbackLauncher from "./FeedbackLauncher";
import {
  feedbackApi,
  sectionForPath,
  type FeedbackOptions,
  type FeedbackRecord,
} from "../../api/modules/feedback";
const account = vi.hoisted(() => ({ id: 2 }));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("../../hooks/useCurrentUser", () => ({
  useCurrentUser: () => account,
}));
vi.mock("../../hooks/useServerTimezone", () => ({
  useServerTimezone: () => "Asia/Shanghai",
}));
vi.mock("../../api/modules/feedback", async (original) => ({
  ...(await original<typeof import("../../api/modules/feedback")>()),
  feedbackApi: { options: vi.fn(), mine: vi.fn(), submit: vi.fn() },
}));
const options: FeedbackOptions = {
  destination: "company",
  local_admin: false,
  sections: [
    { key: "general", label_key: "feedback.general", path: "/" },
    { key: "chat", label_key: "nav.chat", path: "/chat" },
    {
      key: "personalization",
      label_key: "nav.personalization",
      path: "/personalization",
    },
    {
      key: "channels",
      label_key: "nav.channels",
      path: "/personalization/channels",
    },
    { key: "token-usage", label_key: "nav.tokenUsage", path: "/token-usage" },
  ],
};
const record: FeedbackRecord = {
  feedback_id: "fb_01TEST",
  author_name: "Alice",
  section: "token-usage",
  kind: "problem",
  title: "统计布局",
  content: "筛选栏没有对齐",
  client_version: "",
  client_platform: "web",
  status: "new",
  reply: "",
  revision: 1,
  created_at: 1795597200,
  updated_at: 1795597200,
};
beforeEach(() => {
  account.id = 2;
  vi.clearAllMocks();
  vi.mocked(feedbackApi.options).mockResolvedValue(options);
  vi.mocked(feedbackApi.mine).mockResolvedValue({
    items: [],
    total: 0,
    limit: 20,
    offset: 0,
  });
  vi.mocked(feedbackApi.submit).mockResolvedValue(record);
});
async function open(path = "/token-usage") {
  render(
    <MemoryRouter initialEntries={[path]}>
      <FeedbackLauncher />
    </MemoryRouter>,
  );
  fireEvent.click(screen.getByRole("button", { name: "feedback.title" }));
  await screen.findByText("nav.tokenUsage");
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "feedback.submit" }),
    ).toBeEnabled(),
  );
}
it("preselects the current sidebar board without sending any report until submitted", async () => {
  await open();
  expect(screen.getByText("nav.tokenUsage")).toBeInTheDocument();
  expect(feedbackApi.submit).not.toHaveBeenCalled();
  expect(screen.queryByText("feedback.adminTitle")).toBeNull();
});
it("follows the current sidebar board on reopening an empty form and preserves a written draft", async () => {
  const view = (section: string) => (
    <MemoryRouter initialEntries={["/chat"]}>
      <FeedbackLauncher currentSection={section} />
    </MemoryRouter>
  );
  const { rerender } = render(view("chat"));
  fireEvent.click(screen.getByRole("button", { name: "feedback.title" }));
  await screen.findByText("nav.chat");
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  rerender(view("token-usage"));
  fireEvent.click(screen.getByRole("button", { name: "feedback.title" }));
  await screen.findByText("nav.tokenUsage");
  fireEvent.change(screen.getByLabelText("feedback.content"), {
    target: { value: "draft to preserve" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  rerender(view("chat"));
  fireEvent.click(screen.getByRole("button", { name: "feedback.title" }));
  await waitFor(() =>
    expect(screen.getByLabelText("feedback.content")).toHaveValue(
      "draft to preserve",
    ),
  );
  expect(screen.getByText("nav.tokenUsage")).toBeInTheDocument();
});
it("retains text and the same submission key when a failed request is retried", async () => {
  vi.mocked(feedbackApi.submit).mockRejectedValueOnce(new Error("offline"));
  await open();
  fireEvent.change(screen.getByLabelText("feedback.subject"), {
    target: { value: record.title },
  });
  fireEvent.change(screen.getByLabelText("feedback.content"), {
    target: { value: record.content },
  });
  fireEvent.click(screen.getByRole("button", { name: "feedback.submit" }));
  await waitFor(() => expect(feedbackApi.submit).toHaveBeenCalledTimes(1));
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "feedback.submit" }),
    ).toBeEnabled(),
  );
  expect(screen.getByLabelText("feedback.content")).toHaveValue(record.content);
  const first = vi.mocked(feedbackApi.submit).mock.calls[0][0];
  fireEvent.click(screen.getByRole("button", { name: "feedback.submit" }));
  await waitFor(() => expect(feedbackApi.submit).toHaveBeenCalledTimes(2));
  expect(vi.mocked(feedbackApi.submit).mock.calls[1][0].submission_key).toBe(
    first.submission_key,
  );
  expect(Object.keys(first).sort()).toEqual([
    "client_platform",
    "client_version",
    "content",
    "kind",
    "section",
    "submission_key",
    "title",
  ]);
});
it("shows the member's administrator reply in the history tab", async () => {
  vi.mocked(feedbackApi.mine).mockResolvedValue({
    items: [{ ...record, status: "resolved", reply: "已修复，请刷新页面。" }],
    total: 1,
    limit: 20,
    offset: 0,
  });
  await open();
  fireEvent.click(screen.getByRole("tab", { name: "feedback.mine" }));
  expect(await screen.findByText("已修复，请刷新页面。")).toBeInTheDocument();
  expect(screen.getByText("feedback.status.resolved")).toBeInTheDocument();
  expect(screen.getByText(/2026/)).toBeInTheDocument();
});
it("maps specific and private subroutes to a stable board ID", () => {
  expect(
    sectionForPath(options.sections, "/personalization/channels/private-agent"),
  ).toBe("channels");
  expect(
    sectionForPath(options.sections, "/chat/private-agent/private-thread"),
  ).toBe("chat");
  expect(sectionForPath(options.sections, "/unlisted")).toBe("general");
});

it("ignores a previous account's history if it arrives after switching accounts", async () => {
  let finish!: (value: {
    items: FeedbackRecord[];
    total: number;
    limit: number;
    offset: number;
  }) => void;
  vi.mocked(feedbackApi.mine).mockReturnValueOnce(
    new Promise((resolve) => {
      finish = resolve;
    }),
  );
  const view = () => (
    <MemoryRouter>
      <FeedbackLauncher />
    </MemoryRouter>
  );
  const { rerender } = render(view());
  fireEvent.click(screen.getByRole("button", { name: "feedback.title" }));
  await waitFor(() => expect(feedbackApi.mine).toHaveBeenCalledTimes(1));
  account.id = 3;
  rerender(view());
  finish({
    items: [{ ...record, content: "previous-account-private-text" }],
    total: 1,
    limit: 20,
    offset: 0,
  });
  fireEvent.click(screen.getByRole("tab", { name: "feedback.mine" }));
  await waitFor(() =>
    expect(screen.queryByText("previous-account-private-text")).toBeNull(),
  );
});
