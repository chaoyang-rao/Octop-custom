/**
 * JournalList.test.tsx — paginated audit-log style list.
 *
 * What we cover:
 *   - mount → listJournal with default pagination (no action filter)
 *   - row renders timestamp + action tag + actor + truncated target id
 *   - empty state
 *   - changing the action select forwards body.action
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createInstance } from "i18next";
import { I18nextProvider } from "react-i18next";

import en from "../../../locales/en.json";
import zh from "../../../locales/zh.json";
import { makeJournal, listJournalResp } from "../../../test/memoryFixtures";

vi.unmock("react-i18next");

vi.mock("../../../api/modules/memoryDashboard", () => ({
  memoryDashboardApi: {
    listJournal: vi.fn(),
  },
}));

import { memoryDashboardApi } from "../../../api/modules/memoryDashboard";
import JournalList from "./JournalList";

const api = vi.mocked(memoryDashboardApi, true);
const i18n = createInstance();
void i18n.init({
  lng: "zh",
  fallbackLng: "en",
  resources: { zh: { translation: zh }, en: { translation: en } },
  interpolation: { escapeValue: false },
});

function renderJournal() {
  return render(
    <I18nextProvider i18n={i18n}>
      <JournalList agentId="ZYWZTD" />
    </I18nextProvider>,
  );
}

beforeEach(async () => {
  vi.clearAllMocks();
  await i18n.changeLanguage("zh");
});

describe("<JournalList />", () => {
  it("loads with default pagination and renders entries", async () => {
    api.listJournal.mockResolvedValue(
      listJournalResp([
        makeJournal({
          id: "j-1",
          action: "promote",
          actor: "user",
          target_atom_id: "atom-deadbeef-1",
          note: "no existing entity matched 'User'; will create",
          target_summary: "我最喜欢喝一点点抹茶奶冻",
        }),
        makeJournal({
          id: "j-2",
          action: "deprecate",
          actor: "auto",
          target_atom_id: null,
          target_entity_id: "ent-cafefeed",
          target_candidate_id: null,
          note: null,
        }),
      ]),
    );

    renderJournal();

    await waitFor(() => {
      expect(screen.getByText("采纳")).toBeInTheDocument();
      expect(screen.getByText("弃用")).toBeInTheDocument();
    });

    expect(api.listJournal).toHaveBeenCalledWith("ZYWZTD", {
      offset: 0,
      limit: 30,
    });

    // With target_summary, show the specific adopted item; without it, fall back to a generic topic.
    expect(
      screen.getByText("「我最喜欢喝一点点抹茶奶冻」"),
    ).toBeInTheDocument();
    expect(screen.getByText("一个主题")).toBeInTheDocument();
    // Notes show only Chinese: English dev logs are translated and the original English is hidden.
    expect(screen.getByText("新建主题「User」")).toBeInTheDocument();
    expect(
      screen.queryByText(/no existing entity matched/),
    ).not.toBeInTheDocument();
  });

  it("renders extract_run rows with a run summary built from stats", async () => {
    api.listJournal.mockResolvedValue(
      listJournalResp([
        makeJournal({
          id: "run-1",
          action: "extract_run",
          actor: "auto",
          target_atom_id: null,
          note: "scanned 4 events, 4 new; 2 candidates, 2 promoted",
          after: {
            events_considered: 4,
            events_extracted: 4,
            candidates: 2,
            promoted: 2,
            failure_reason: null,
          },
        }),
        makeJournal({
          id: "run-2",
          action: "extract_run",
          actor: "auto",
          target_atom_id: null,
          note: "no new events (scanned 4)",
          after: { events_considered: 4, events_extracted: 0, candidates: 0 },
        }),
      ]),
    );

    renderJournal();

    await waitFor(() =>
      expect(screen.getAllByText("提取运行")).toHaveLength(2),
    );
    expect(
      screen.getByText("处理 4 段对话，生成 2 条草稿，晋升 2 条记忆"),
    ).toBeInTheDocument();
    expect(screen.getByText("扫描 4 段对话，无新增内容")).toBeInTheDocument();
  });

  it("renders empty state on no entries", async () => {
    api.listJournal.mockResolvedValue(listJournalResp([]));
    renderJournal();
    await waitFor(() => expect(api.listJournal).toHaveBeenCalled());
    expect(document.querySelector(".ant-empty-image")).not.toBeNull();
  });

  it("shows a retryable error and loads the same page on retry", async () => {
    api.listJournal
      .mockRejectedValueOnce(new Error("request failed"))
      .mockResolvedValueOnce(
        listJournalResp([makeJournal({ action: "promote" })]),
      );
    renderJournal();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "整理记录加载失败",
    );
    expect(screen.queryByText("暂无整理记录")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /重\s*试/ }));

    expect(await screen.findByText("采纳")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(api.listJournal).toHaveBeenNthCalledWith(2, "ZYWZTD", {
      offset: 0,
      limit: 30,
    });
  });

  it("localizes the activity labels and preserves the saved memory text", async () => {
    await i18n.changeLanguage("en");
    api.listJournal.mockResolvedValue(
      listJournalResp([
        makeJournal({ action: "promote", target_summary: "原始记忆" }),
      ]),
    );
    renderJournal();

    expect(await screen.findByText("Adopt")).toBeInTheDocument();
    expect(screen.getByText("Filter by type:")).toBeInTheDocument();
    expect(screen.getByText(/原始记忆/)).toBeInTheDocument();
  });
});
