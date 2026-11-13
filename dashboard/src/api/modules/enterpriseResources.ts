import { request } from "../request";
import type {
  EnterpriseMcpMember,
  EnterpriseMcpVersion,
} from "./enterpriseMcp";

export interface ResourceDefinition {
  resource_id: string;
  kind: "expert" | "skill";
  display_name: string;
  description: string;
  enabled: boolean;
  allowed_subjects: string[];
  avatar?: { shape: string; color: string } | null;
  skill_refs: string[];
  mcp_refs: string[];
  files: { path: string; content_base64: string }[];
}
export interface ResourceEntry {
  resource_id: string;
  kind: "expert" | "skill";
  display_name: string;
  description: string;
  enabled: boolean;
  allowed_subjects: string[];
  digest: string;
}
export interface ResourceAdminState {
  etag: string;
  draft: ResourceEntry[];
  published: {
    revision: number;
    published_at: number;
    entries: ResourceEntry[];
  };
  history: EnterpriseMcpVersion[];
}
export interface ResourceLocalState {
  resource_id: string;
  kind: "expert" | "skill";
  display_name: string;
  enabled: boolean;
  digest: string | null;
  target_id: string | null;
  applied_digest: string | null;
  status: string;
  paused: boolean;
  local_modified?: boolean;
  conflicts: string[];
  error: string | null;
}
export interface ResourceNodeState {
  enabled: boolean;
  revision: number;
  last_synced_at: number | null;
  error: string | null;
  resources: ResourceLocalState[];
}
export interface ResourceDetail {
  resource_id: string;
  ticket: string;
  local_files: Record<string, string>;
  conflicts: {
    path: string;
    base: string | null;
    local: string | null;
    remote: string | null;
  }[];
}
export interface ResourceExportOption {
  kind: "expert" | "skill";
  id: string;
  name: string;
  slug: string;
}
const center = "/enterprise/resources/admin";
const node = "/enterprise-resources";
const send = <T>(url: string, method: string, body: unknown) =>
  request<T>(url, { method, body: JSON.stringify(body) });
export const resourcesApi = {
  admin: () => request<ResourceAdminState>(`${center}/catalog`),
  members: () => request<EnterpriseMcpMember[]>(`${center}/members`),
  bundle: (hash: string) =>
    request<ResourceDefinition>(`/enterprise/resources/bundles/${hash}`),
  save: (resource: ResourceDefinition, expected_etag: string) =>
    send<ResourceAdminState>(`${center}/entry`, "PUT", {
      resource,
      expected_etag,
    }),
  remove: (resource_id: string, expected_etag: string) =>
    send<ResourceAdminState>(`${center}/remove`, "POST", {
      resource_id,
      expected_etag,
    }),
  publish: (expected_etag: string) =>
    send<ResourceAdminState>(`${center}/publish`, "POST", { expected_etag }),
  rollback: (revision: number, expected_etag: string) =>
    send<ResourceAdminState>(`${center}/rollback`, "POST", {
      revision,
      expected_etag,
    }),
  status: () => request<ResourceNodeState>(node),
  sync: () => send<ResourceNodeState>(`${node}/sync`, "POST", {}),
  detail: (id: string) =>
    request<ResourceDetail>(`${node}/${encodeURIComponent(id)}`),
  resolve: (
    id: string,
    ticket: string,
    decisions: Record<string, "local" | "remote">,
  ) =>
    send<ResourceNodeState>(
      `${node}/${encodeURIComponent(id)}/resolve`,
      "POST",
      { ticket, decisions },
    ),
  pause: (id: string, paused: boolean) =>
    send<ResourceNodeState>(`${node}/${encodeURIComponent(id)}`, "PATCH", {
      paused,
    }),
  exports: () => request<ResourceExportOption[]>(`${node}/exports`),
  export: (item: ResourceExportOption) =>
    request<ResourceDefinition>(
      `${node}/export/${item.kind}/${encodeURIComponent(
        item.id,
      )}?slug=${encodeURIComponent(item.slug)}`,
    ),
};
export function decodeText(value: string | null): string | null {
  if (value === null) return null;
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(
      Uint8Array.from(atob(value), (c) => c.charCodeAt(0)),
    );
  } catch {
    return null;
  }
}
export function encodeText(value: string): string {
  return btoa(
    Array.from(new TextEncoder().encode(value), (c) =>
      String.fromCharCode(c),
    ).join(""),
  );
}
export function downloadResource(value: ResourceDefinition) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = `${value.resource_id}.json`;
  a.click();
  URL.revokeObjectURL(url);
}
