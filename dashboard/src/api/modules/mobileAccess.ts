import { request } from "../request";

export type MobileScope =
  | "chat"
  | "files"
  | "notifications"
  | "tasks"
  | "browser"
  | "desktop"
  | "terminal"
  | "phone"
  | "manage_agents";
export interface MobileDevice {
  device_id: string;
  name: string;
  platform: string;
  scopes: MobileScope[];
  created_at: number;
  expires_at: number;
  revoked_at: number | null;
  push_enabled: boolean;
}
export interface MobilePairingPreview {
  name: string;
  platform: string;
  expires_at: number;
  host_fingerprint: string;
}
export const mobileAccessApi = {
  list: () => request<MobileDevice[]>("/mobile-access/devices"),
  inspect: (code: string) =>
    request<MobilePairingPreview>("/mobile-access/pairings/inspect", {
      method: "POST",
      body: JSON.stringify({ code }),
    }),
  approve: (code: string, scopes: MobileScope[]) =>
    request<MobileDevice>("/mobile-access/pairings/approve", {
      method: "POST",
      body: JSON.stringify({ code, scopes }),
    }),
  revoke: (id: string) =>
    request<void>(`/mobile-access/devices/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
};

export interface PushProviderConfig {
  enabled: boolean;
  team_id?: string;
  key_id?: string;
  topic?: string;
  sandbox?: boolean;
  project_id?: string;
  client_email?: string;
  private_key?: string;
}
export const mobilePushApi = {
  status: () =>
    request<Record<"apns" | "fcm", boolean>>("/mobile-access/push/config"),
  configure: (provider: "apns" | "fcm", config: PushProviderConfig) =>
    request<Record<"apns" | "fcm", boolean>>(
      `/mobile-access/push/config/${provider}`,
      { method: "PUT", body: JSON.stringify(config) },
    ),
};

export interface RemoteCheck {
  url: string;
  checked_at: number;
  dns: boolean;
  tls: boolean;
  http_status: number | null;
  identity_matches: boolean;
  ok: boolean;
  reason: string;
}
export interface RemoteStatus {
  public_url: string | null;
  request_origin: string;
  listener: string;
  native_tls: boolean;
  tailscale_installed: boolean;
  last_check: RemoteCheck | null;
}
export const mobileRemoteApi = {
  status: () => request<RemoteStatus>("/mobile-access/remote/status"),
  configure: (url: string) =>
    request<{ url: string }>("/mobile-access/remote/url", {
      method: "PUT",
      body: JSON.stringify({ url }),
    }),
  check: (url: string) =>
    request<RemoteCheck>("/mobile-access/remote/check", {
      method: "POST",
      body: JSON.stringify({ url }),
    }),
  tailscaleStatus: () =>
    request<{ authenticated: boolean; url: string | null; owned: boolean }>(
      "/mobile-access/remote/tailscale",
    ),
  enableTailscale: () =>
    request<{ url: string; enabled: boolean; network: string }>(
      "/mobile-access/remote/tailscale/enable",
      { method: "POST" },
    ),
  disableTailscale: () =>
    request<{ enabled: boolean }>("/mobile-access/remote/tailscale/disable", {
      method: "POST",
    }),
};
