import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { request } from "../../../api/request";
import CompanyModelUsage from "./CompanyModelUsage";

const { t } = vi.hoisted(() => ({ t: (key: string) => key }));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t }) }));
vi.mock("../../../api/request", () => ({ request: vi.fn() }));
vi.mock("./UsageStats", () => ({ UsageStats: () => null }));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("company model usage", () => {
  it("labels company scope and estimated requests without hiding the server member identity", async () => {
    vi.mocked(request).mockResolvedValue({
      scope: "company",
      range_start: 1,
      range_end: 2,
      rows: [
        {
          user_id: 7,
          member_name: "Alice",
          model: "company-model",
          requests: 2,
          input_tokens: 12,
          output_tokens: 3,
          total_tokens: 15,
          estimated_requests: 1,
          last_used: 2,
        },
      ],
    });
    render(<CompanyModelUsage />);
    expect(await screen.findByText("Alice")).toBeInTheDocument();
    expect(screen.getByText("companyUsage.company")).toBeInTheDocument();
    expect(screen.getByText("companyUsage.estimated")).toBeInTheDocument();
    expect(request).toHaveBeenCalledWith("/enterprise/models/usage?days=30");
  });

  it("shows a server-reported personal scope rather than assuming machine admins see the company", async () => {
    vi.mocked(request).mockResolvedValue({
      scope: "self",
      range_start: 1,
      range_end: 2,
      rows: [],
    });
    render(<CompanyModelUsage />);
    expect(await screen.findByText("companyUsage.self")).toBeInTheDocument();
    expect(screen.queryByText("companyUsage.company")).not.toBeInTheDocument();
  });
});
