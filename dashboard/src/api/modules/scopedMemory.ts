import { request } from "../request";

export type MemoryScope = "auto" | "user" | "project" | "expert" | "session";
export interface ScopedMemorySource {
  thread_id: string;
  agent_id: string;
  title: string;
  created_at: string;
  origin: string;
}
export interface ScopedMemoryAtom {
  id: string;
  assertion: string;
  created_at: string;
  deprecated_at?: string | null;
  superseded_by?: string | null;
  sources: ScopedMemorySource[];
}
export interface ScopedMemoryList {
  scope: MemoryScope;
  scope_token: string;
  default_scope: MemoryScope;
  available_scopes: MemoryScope[];
  project_name: string | null;
  items: ScopedMemoryAtom[];
  total: number;
  has_more: boolean;
}
export interface MemoryRevision {
  id: string;
  timestamp: string;
  action: string;
  before?: { assertion?: string } | null;
  after?: { assertion?: string } | null;
}
const base = (agent: string, thread: string) =>
  `/agents/${encodeURIComponent(agent)}/threads/${encodeURIComponent(
    thread,
  )}/memory`;

export const scopedMemoryApi = {
  list(
    agent: string,
    thread: string,
    scope: MemoryScope,
    query: string,
    offset: number,
    includeDeprecated: boolean,
  ) {
    const params = new URLSearchParams({
      scope,
      query,
      offset: String(offset),
      include_deprecated: String(includeDeprecated),
    });
    return request<ScopedMemoryList>(`${base(agent, thread)}?${params}`);
  },
  save(
    agent: string,
    thread: string,
    scope: MemoryScope,
    content: string,
    scopeToken: string,
    replaces?: string,
  ) {
    return request<{ atom_id: string }>(base(agent, thread), {
      method: "POST",
      body: JSON.stringify({
        scope,
        content,
        replaces,
        expected_scope_token: scopeToken,
      }),
    });
  },
  retire(
    agent: string,
    thread: string,
    scope: MemoryScope,
    atomId: string,
    scopeToken: string,
  ) {
    return request(
      `${base(agent, thread)}/${encodeURIComponent(
        atomId,
      )}:deprecate?scope=${scope}&expected_scope_token=${encodeURIComponent(
        scopeToken,
      )}`,
      { method: "POST" },
    );
  },
  revisions(agent: string, thread: string, scope: MemoryScope, atomId: string) {
    return request<{ items: MemoryRevision[] }>(
      `${base(agent, thread)}/${encodeURIComponent(
        atomId,
      )}/revisions?scope=${scope}`,
    );
  },
};
