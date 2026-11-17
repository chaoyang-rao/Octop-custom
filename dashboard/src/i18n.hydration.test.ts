import { beforeEach, expect, it, vi } from "vitest";

vi.mock("i18next", () => ({
  default: { language: "zh", addResourceBundle: vi.fn() },
}));
vi.mock("./api/config", () => ({ getApiUrl: (path: string) => "/api" + path }));
vi.mock("./api/modules/i18n", () => ({
  i18nApi: { getToolLabels: vi.fn(), getSkillLabels: vi.fn() },
}));

import { refreshServerLabels } from "./i18n";
import { i18nApi } from "./api/modules/i18n";
import { setAuthToken, clearSetupRequired } from "./api/request";

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  sessionStorage.clear();
  clearSetupRequired();
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ setup_required: false }), {
        status: 200,
      }),
    ),
  );
  vi.mocked(i18nApi.getToolLabels).mockResolvedValue({ labels: {} });
  vi.mocked(i18nApi.getSkillLabels).mockResolvedValue({ labels: {} });
});

it("keeps unauthenticated login on bundled labels without triggering setup lockdown", async () => {
  await refreshServerLabels("zh");
  expect(fetch).not.toHaveBeenCalled();
  expect(i18nApi.getToolLabels).not.toHaveBeenCalled();
  expect(i18nApi.getSkillLabels).not.toHaveBeenCalled();
});

it("refreshes server labels after successful authentication", async () => {
  setAuthToken("fixture-local-access");
  await refreshServerLabels("zh");
  expect(i18nApi.getToolLabels).toHaveBeenCalledOnce();
  expect(i18nApi.getSkillLabels).toHaveBeenCalledOnce();
});
