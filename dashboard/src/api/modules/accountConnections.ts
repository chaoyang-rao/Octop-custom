import { request } from "../request";

export interface VaultConnection {
  id: string;
  provider: "onepassword" | "bitwarden";
  name: string;
  allowed_hosts: string[];
  ready: boolean;
  profile_path?: string | null;
}
export interface VaultReference {
  reference: string;
  connection_id?: string | null;
  label: string;
  field_name: string;
}
export interface VaultItem {
  item_id: string;
  title: string;
  vault_id: string;
}
export interface VaultUseRequest {
  request_id: string;
  reference: string;
  url: string;
  method: string;
  purpose: string;
  expires_at: number;
  state: string;
  header_name?: string;
  prefix?: string;
  body?: Record<string, unknown> | null;
  approval_token?: string;
  status_code?: number;
}
export interface OAuthApp {
  configured: boolean;
  client_id: string;
  secret_configured: boolean;
  scopes: string;
}
export interface VaultConnectionInput {
  provider: "onepassword" | "bitwarden";
  name: string;
  allowed_hosts: string[];
  service_account_token?: string;
}

const root = "/account-connections";
const body = (value: unknown): string => JSON.stringify(value);
const id = encodeURIComponent;
export const accountConnectionsApi = {
  vaults: () => request<VaultConnection[]>(`${root}/vaults`),
  saveVault: (value: VaultConnectionInput, connectionId?: string) =>
    request<VaultConnection>(
      `${root}/vaults${connectionId ? `/${id(connectionId)}` : ""}`,
      { method: connectionId ? "PUT" : "POST", body: body(value) },
    ),
  disconnect: (connectionId: string) =>
    request(`${root}/vaults/${id(connectionId)}`, { method: "DELETE" }),
  unlock: (connectionId: string, session: string) =>
    request(`${root}/vaults/${id(connectionId)}/unlock`, {
      method: "POST",
      body: body({ session }),
    }),
  lock: (connectionId: string) =>
    request(`${root}/vaults/${id(connectionId)}/lock`, { method: "POST" }),
  items: (connectionId: string, offset = 0, search = "") =>
    request<VaultItem[]>(
      `${root}/vaults/${id(
        connectionId,
      )}/items?offset=${offset}&search=${encodeURIComponent(search)}`,
    ),
  references: () => request<VaultReference[]>(`${root}/references`),
  createReference: (value: {
    connection_id: string;
    item_id: string;
    vault_id?: string;
    field_name: string;
    label?: string;
  }) =>
    request<VaultReference>(`${root}/references`, {
      method: "POST",
      body: body(value),
    }),
  requests: () => request<VaultUseRequest[]>(`${root}/requests`),
  requestUse: (value: {
    reference: string;
    url: string;
    purpose: string;
    method?: string;
    header_name?: string;
    prefix?: string;
    body?: Record<string, unknown>;
  }) =>
    request<VaultUseRequest>(`${root}/requests`, {
      method: "POST",
      body: body(value),
    }),
  approve: (requestId: string, token: string) =>
    request<{ request_id: string; state: string; status_code: number }>(
      `${root}/requests/${id(requestId)}/approve`,
      { method: "POST", body: body({ approval_token: token }) },
    ),
  reject: (requestId: string) =>
    request(`${root}/requests/${id(requestId)}/reject`, { method: "POST" }),
  oauthApp: (kind: string) =>
    request<OAuthApp>(`${root}/oauth-apps/${id(kind)}`),
  saveOauthApp: (
    kind: string,
    value: { client_id: string; client_secret?: string; scopes?: string },
  ) =>
    request<OAuthApp>(`${root}/oauth-apps/${id(kind)}`, {
      method: "PUT",
      body: body(value),
    }),
  deleteOauthApp: (kind: string) =>
    request(`${root}/oauth-apps/${id(kind)}`, { method: "DELETE" }),
};
