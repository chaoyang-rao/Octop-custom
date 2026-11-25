import { request } from "../request";

export type FeedbackStatus = "new" | "in_progress" | "resolved";
export type FeedbackKind = "problem" | "suggestion" | "other";
export interface FeedbackSection {
  key: string;
  label_key: string;
  path: string;
}
export interface FeedbackOptions {
  sections: FeedbackSection[];
  destination: "company" | "local";
  local_admin: boolean;
}
export interface FeedbackRecord {
  feedback_id: string;
  author_name: string;
  section: string;
  kind: FeedbackKind;
  title: string;
  content: string;
  client_version: string;
  client_platform: string;
  status: FeedbackStatus;
  reply: string;
  revision: number;
  created_at: number;
  updated_at: number;
}
export interface FeedbackList {
  items: FeedbackRecord[];
  total: number;
  limit: number;
  offset: number;
}
export interface FeedbackDraft {
  submission_key: string;
  section: string;
  kind: FeedbackKind;
  title: string;
  content: string;
  client_version: string;
  client_platform: string;
}
export interface FeedbackFilter {
  section?: string;
  status?: FeedbackStatus;
  q?: string;
  limit?: number;
  offset?: number;
}
const root = (company: boolean) =>
  company ? "/enterprise/feedback" : "/feedback";
export const feedbackApi = {
  options: (company = false) =>
    request<FeedbackOptions>(`${root(company)}/options`),
  submit: (draft: FeedbackDraft) =>
    request<FeedbackRecord>("/feedback", {
      method: "POST",
      body: JSON.stringify(draft),
    }),
  mine: () => request<FeedbackList>("/feedback/mine?limit=20"),
  list: (filter: FeedbackFilter, company = false) => {
    const query = new URLSearchParams();
    Object.entries(filter).forEach(([key, value]) => {
      if (value !== undefined && value !== "") query.set(key, String(value));
    });
    return request<FeedbackList>(`${root(company)}/admin?${query.toString()}`);
  },
  update: (
    row: FeedbackRecord,
    status: FeedbackStatus,
    reply: string,
    company = false,
  ) =>
    request<FeedbackRecord>(
      `${root(company)}/admin/${encodeURIComponent(row.feedback_id)}`,
      {
        method: "PATCH",
        body: JSON.stringify({
          expected_revision: row.revision,
          status,
          reply,
        }),
      },
    ),
};

/** Specific sections such as channels win over the generic personalization pane. */
export function sectionForPath(
  sections: FeedbackSection[],
  pathname: string,
): string {
  return (
    [...sections]
      .filter(
        (section) =>
          section.path !== "/" &&
          (pathname === section.path ||
            pathname.startsWith(section.path + "/")),
      )
      .sort((a, b) => b.path.length - a.path.length)[0]?.key ?? "general"
  );
}
