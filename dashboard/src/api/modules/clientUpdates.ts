import { request } from "../request";

export type ClientUpdatePhase =
  | "idle"
  | "available"
  | "downloading"
  | "downloaded"
  | "waiting_idle"
  | "applying"
  | "backing_up"
  | "ready_to_swap"
  | "installing"
  | "starting"
  | "candidate_ready"
  | "accepted"
  | "failed"
  | "rolled_back"
  | "rolling_back"
  | "cancelled";
export interface ClientUpdateJob {
  id: string;
  phase: ClientUpdatePhase;
  downloaded_bytes: number;
  total_bytes: number;
  target_version: string;
  error_code: string | null;
}
export interface ClientUpdateStatus {
  supported: boolean;
  platform: string | null;
  current_version: string | null;
  revision: number;
  available: boolean;
  version: string | null;
  notes: string;
  busy: boolean;
  job: ClientUpdateJob | null;
  error_code: string | null;
  last_check: number | null;
}
export interface ClientReleaseOption {
  tag: string;
  version: string;
  source_commit: string;
  notes: string;
  companion_version?: string | null;
}
export interface ClientRelease extends ClientReleaseOption {
  revision: number;
  published_at: number;
  enabled: boolean;
  allowed_subjects: string[];
}
export interface ClientDeviceReport {
  product: "octop-desktop" | "octop-companion";
  device_id: string;
  user_id: number;
  display_name: string;
  device_name: string;
  platform: string;
  current_version: string;
  target_version: string | null;
  phase: ClientUpdatePhase;
  last_seen_at: number;
  error_code: string | null;
}
export interface ClientUpdateAdmin {
  etag: string;
  revision: number;
  signing_configured: boolean;
  draft:
    | (ClientReleaseOption & { companion?: ClientReleaseOption | null })
    | null;
  published: {
    release: ClientRelease;
    companion?: { release: ClientRelease } | null;
  } | null;
  history: { release: ClientRelease; published_by: string }[];
  devices: ClientDeviceReport[];
}

const adminPath = "/enterprise/client-updates/admin";
export const clientUpdatesApi = {
  status: () => request<ClientUpdateStatus>("/client-updates/status"),
  check: () =>
    request<ClientUpdateStatus>("/client-updates/check", { method: "POST" }),
  download: () =>
    request<ClientUpdateStatus>("/client-updates/download", { method: "POST" }),
  prepare: (id: string) =>
    request<{ job_id: string }>(
      `/client-updates/jobs/${encodeURIComponent(id)}/prepare`,
      { method: "POST" },
    ),
  abort: (id: string) =>
    request<ClientUpdateStatus>(
      `/client-updates/jobs/${encodeURIComponent(id)}/abort-install`,
      { method: "POST" },
    ),
  cancel: (id: string) =>
    request<ClientUpdateStatus>(
      `/client-updates/jobs/${encodeURIComponent(id)}/cancel`,
      { method: "POST" },
    ),
  admin: () => request<ClientUpdateAdmin>(adminPath),
  releases: () => request<ClientReleaseOption[]>(`${adminPath}/releases`),
  import: (tag: string, expected_etag: string) =>
    request<ClientUpdateAdmin>(`${adminPath}/import`, {
      method: "POST",
      body: JSON.stringify({ tag, expected_etag }),
    }),
  publish: (expected_etag: string, allowed_subjects: string[]) =>
    request<ClientUpdateAdmin>(`${adminPath}/publish`, {
      method: "POST",
      body: JSON.stringify({ expected_etag, allowed_subjects }),
    }),
  withdraw: (expected_etag: string) =>
    request<ClientUpdateAdmin>(`${adminPath}/withdraw`, {
      method: "POST",
      body: JSON.stringify({ expected_etag }),
    }),
};

export function installNativeClientUpdate(jobId: string): Promise<void> {
  const invoke = (
    window as Window & { _wails?: { invoke?: (value: string) => void } }
  )._wails?.invoke;
  if (!invoke) return Promise.reject(new Error("CLIENT_UPDATE_UNSUPPORTED"));
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  const requestId = Array.from(bytes, (value) =>
    value.toString(16).padStart(2, "0"),
  ).join("");
  return new Promise((resolve, reject) => {
    const finish = (error?: string) => {
      window.clearTimeout(timer);
      window.removeEventListener("octop:client-update-result", listener);
      if (error) reject(new Error(error));
      else resolve();
    };
    const listener = (event: Event) => {
      const value = (
        event as CustomEvent<{
          request_id: string;
          ok: boolean;
          error_code?: string;
        }>
      ).detail;
      if (value?.request_id !== requestId) return;
      finish(value.ok ? undefined : value.error_code || "CLIENT_UPDATE_FAILED");
    };
    const timer = window.setTimeout(
      () => finish("CLIENT_UPDATE_FAILED"),
      15000,
    );
    window.addEventListener("octop:client-update-result", listener);
    try {
      invoke(
        "wails:event:emit:desktop:client-update:" +
          encodeURIComponent(
            JSON.stringify({ request_id: requestId, job_id: jobId }),
          ),
      );
    } catch {
      finish("CLIENT_UPDATE_FAILED");
    }
  });
}
