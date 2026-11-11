import { request } from "../request";

export type EnterpriseMcpAuthKind = "none" | "bearer" | "basic";

export interface EnterpriseMcpEntry {
  entry_id: string;
  display_name: string;
  description: string;
  url: string;
  auth_kind: EnterpriseMcpAuthKind;
  enabled: boolean;
  allowed_subjects: string[];
}

export interface EnterpriseMcpSnapshot {
  schema_version: number;
  revision: number;
  checksum: string;
  published_at: number;
  entries: EnterpriseMcpEntry[];
}

export interface EnterpriseMcpVersion {
  revision: number;
  published_at: number;
  published_by: string;
  checksum: string;
}

export interface EnterpriseMcpAdminState {
  etag: string;
  draft: { entries: EnterpriseMcpEntry[] };
  published: EnterpriseMcpSnapshot;
  history: EnterpriseMcpVersion[];
}

export interface EnterpriseMcpMember {
  subject: string;
  display_name: string;
}

export interface EnterpriseMcpMemberEntry extends EnterpriseMcpEntry {
  server_name: string;
  fingerprint: string;
  authorized: boolean;
  needs_reauthorization: boolean;
  configuration_error?: string | null;
  local_disabled?: boolean;
}

export interface EnterpriseMcpNodeState {
  enabled: boolean;
  authority_url: string | null;
  revision: number;
  last_synced_at: number | null;
  sync_error: string | null;
  pending_apply: boolean;
  configuration_error?: string | null;
  entries: EnterpriseMcpMemberEntry[];
}

export interface EnterpriseMcpCredentials {
  token?: string;
  username?: string;
  password?: string;
}

export interface EnterpriseMcpAuthorization extends EnterpriseMcpCredentials {
  expected_fingerprint: string;
}

const center = "/enterprise/mcp/admin";
const node = "/connectors/enterprise-mcp";

export const enterpriseMcpApi = {
  adminCatalog: () => request<EnterpriseMcpAdminState>(`${center}/catalog`),
  members: () => request<EnterpriseMcpMember[]>(`${center}/members`),
  saveDraft: (entries: EnterpriseMcpEntry[], expected_etag: string) =>
    request<EnterpriseMcpAdminState>(`${center}/draft`, {
      method: "PUT",
      body: JSON.stringify({ entries, expected_etag }),
    }),
  publish: (expected_etag: string) =>
    request<EnterpriseMcpAdminState>(`${center}/publish`, {
      method: "POST",
      body: JSON.stringify({ expected_etag }),
    }),
  rollback: (revision: number, expected_etag: string) =>
    request<EnterpriseMcpAdminState>(`${center}/rollback`, {
      method: "POST",
      body: JSON.stringify({ revision, expected_etag }),
    }),
  nodeStatus: () => request<EnterpriseMcpNodeState>(node),
  sync: () =>
    request<EnterpriseMcpNodeState>(`${node}/sync`, { method: "POST" }),
  authorize: (entryId: string, credentials: EnterpriseMcpAuthorization) =>
    request<EnterpriseMcpNodeState>(
      `${node}/entries/${encodeURIComponent(entryId)}/credentials`,
      { method: "PUT", body: JSON.stringify(credentials) },
    ),
  clearAuthorization: (entryId: string) =>
    request<EnterpriseMcpNodeState>(
      `${node}/entries/${encodeURIComponent(entryId)}/credentials`,
      { method: "DELETE" },
    ),
};
