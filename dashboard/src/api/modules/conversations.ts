import { request, requestBlob, requestStream } from "../request";

export interface MessageLocator {
  message_id?: string;
  role: "user" | "assistant";
  content?: string;
  ordinal_from_end?: number;
}
export interface QuoteReference {
  source_thread_id: string;
  message: MessageLocator;
}
export interface QuotedMessage {
  source_thread_id: string;
  source_agent_id: string;
  message_key: string;
  role: "user" | "assistant";
  content: string;
  speaker_agent_id?: string | null;
  speaker_name?: string | null;
}
export interface QuoteDraft {
  reference: QuoteReference;
  resolved: QuotedMessage;
}
export interface Reaction {
  message_key: string;
  message_digest: string;
  message_role: string;
  emoji: string;
  created_at: number;
}
export interface Conversation {
  thread_id: string;
  agent_id: string;
  agent_name: string;
  title: string | null;
  kind: string;
  archived: boolean;
  last_active: number;
  created_at: number;
  project_name?: string | null;
  origin?: {
    source: string;
    external_id: string;
    source_title?: string;
    source_thread_id?: string;
    imported_at?: number;
  } | null;
}
export interface ImportPreview {
  id: string;
  kind: string;
  state: string;
  sha256: string;
  expires_at: number;
  omitted_messages: number;
  ignored_files: number;
  warnings: string[];
  bytes: number;
  items: Array<{
    key: string;
    name: string;
    messages: number;
    files: number;
    skills: number;
    duplicate: boolean;
    name_conflict: boolean;
  }>;
}
export interface ImportSelection {
  keys: string[];
  target_agent_id?: string;
  names?: Record<string, string>;
  default_model?: string;
  include_files?: boolean;
  include_skills?: boolean;
  include_workflows?: boolean;
  skip_duplicates?: boolean;
}
export interface ImportResult {
  threads: Array<{ thread_id: string; agent_id: string; title: string }>;
  agents: Array<{ agent_id: string; name: string; source_key: string }>;
  skipped: number;
  warnings: string[];
}
export interface SideQuestion {
  thread_id: string;
  agent_id: string;
  session_key: string;
  source_thread_id: string;
  copied_messages: number;
  title: string | null;
  conversation_mode: "ask";
}
const root = (id: string) => `/conversations/${encodeURIComponent(id)}`;
export const conversationsApi = {
  list: (
    params: {
      archived?: boolean;
      agent_id?: string;
      query?: string;
      offset?: number;
    } = {},
  ) =>
    request<{
      conversations: Conversation[];
      has_more: boolean;
      next_offset: number;
    }>(
      `/conversations?${new URLSearchParams(
        Object.entries(params).map(([key, value]) => [key, String(value)]),
      )}`,
    ),
  archive: (id: string, archived: boolean) =>
    request<Conversation>(`${root(id)}/archive`, {
      method: "PATCH",
      body: JSON.stringify({ archived }),
    }),
  annotations: (id: string) =>
    request<{ reactions: Reaction[]; allowed: string[] }>(
      `${root(id)}/annotations`,
    ),
  react: (
    id: string,
    message: MessageLocator,
    emoji: string,
    active: boolean,
  ) =>
    request<{ message_key: string; reactions: Reaction[] }>(
      `${root(id)}/reactions`,
      { method: "POST", body: JSON.stringify({ message, emoji, active }) },
    ),
  resolve: (id: string, message: MessageLocator) =>
    request<QuotedMessage>(`${root(id)}/resolve`, {
      method: "POST",
      body: JSON.stringify(message),
    }),
  side: (id: string, message: MessageLocator) =>
    request<SideQuestion>(`${root(id)}/side-question`, {
      method: "POST",
      body: JSON.stringify(message),
    }),
  stage: (file: File) =>
    request<ImportPreview>("/conversation-imports/preview", {
      method: "POST",
      body: file,
      headers: { "Content-Type": "application/zip" },
    }),
  confirm: (id: string, selection: ImportSelection) =>
    request<ImportResult>(
      `/conversation-imports/${encodeURIComponent(id)}/confirm`,
      { method: "POST", body: JSON.stringify(selection) },
    ),
  discard: (id: string) =>
    request<void>(`/conversation-imports/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
  export: (selection: {
    agent_ids: string[];
    include_files: boolean;
    include_skills: boolean;
    include_conversations: boolean;
    include_workflows: boolean;
  }) =>
    requestBlob("/conversation-transfer/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(selection),
    }),
  resumeSide: (
    agentId: string,
    threadId: string,
    pendingId: string | undefined,
    decisions: Array<{ type: "approve" | "reject" }>,
  ) =>
    requestStream(`/agents/${encodeURIComponent(agentId)}/chat/hitl/resume`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        thread_id: threadId,
        pending_id: pendingId,
        decisions,
      }),
    }),
};
