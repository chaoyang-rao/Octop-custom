import { request } from "../request";
export interface NativeCliConfig {
  enabled: boolean;
  runner: string;
  model_id: string;
  mode_id: string;
}
export interface NativeCliRunner {
  runner: string;
  enabled: boolean;
  command: string;
  launcher_available: boolean;
  uses_package_launcher: boolean;
  environment_configured: boolean;
}
export interface NativeCliSession {
  thread_id: string;
  title: string;
  cwd?: string | null;
  runner?: string | null;
  state: string;
}
export interface NativeCliCapabilities {
  models: { value: string; name: string }[];
  modes: { value: string; name: string }[];
  config_options: {
    id: string;
    name: string;
    category: string;
    type: string;
    current_value: string | boolean;
    options: { value: string; name: string }[];
  }[];
  current_mode: string;
  image: boolean;
  audio: boolean;
  embedded_context: boolean;
  runner: string;
  origin_cwd: string;
  read_at: number;
}
export interface NativeCliView extends NativeCliConfig {
  can_manage: boolean;
  capabilities?: NativeCliCapabilities | null;
  runners: NativeCliRunner[];
  sessions: NativeCliSession[];
}
export interface NativeCliInspection {
  runner: string;
  launcher_available: boolean;
  version?: string | null;
  version_kind: string;
}
export interface NativeCliModelChoices {
  runner: string;
  effective_model_id: string;
  configured_model_id: string;
  models: { value: string; name: string }[];
  has_capabilities: boolean;
}
const id = encodeURIComponent;
export const nativeCliApi = {
  models: (agentId: string, threadId?: string | null) =>
    request<NativeCliModelChoices>(
      `/agents/${id(agentId)}/native-cli/models${
        threadId ? `?thread_id=${id(threadId)}` : ""
      }`,
    ),
  probe: (agentId: string, runner: string) =>
    request<NativeCliCapabilities>(`/agents/${id(agentId)}/native-cli/probe`, {
      method: "POST",
      body: JSON.stringify({ runner }),
    }),
  get: (agentId: string) =>
    request<NativeCliView>(`/agents/${id(agentId)}/native-cli`),
  save: (agentId: string, value: NativeCliConfig) =>
    request<NativeCliView>(`/agents/${id(agentId)}/native-cli`, {
      method: "PUT",
      body: JSON.stringify(value),
    }),
  inspect: (runner: string) =>
    request<NativeCliInspection>(`/native-cli/runners/${id(runner)}/inspect`, {
      method: "POST",
    }),
  close: (agentId: string, threadId: string) =>
    request(`/agents/${id(agentId)}/native-cli/sessions/${id(threadId)}`, {
      method: "DELETE",
    }),
};

export interface ManagedCliArtifact {
  version: string;
  url: string;
  sha256: string;
  integrity?: string | null;
  size: number;
  license_url: string;
  license_sha256: string;
  release_url: string;
}
export interface ManagedCliPackage {
  package: string;
  label: string;
  license: string;
  repository: string;
  runner: string;
  versions: string[];
  approved: ManagedCliArtifact[];
  latest_approved: string;
  supported: boolean;
  platform: string;
  installed: string[];
  active_version?: string | null;
  previous_version?: string | null;
  state: { phase: string; version?: string | null; error_code?: string | null };
}
export const managedCliApi = {
  status: () => request<ManagedCliPackage[]>("/native-cli/managed"),
  install: (pkg: string, version: string) =>
    request(`/native-cli/managed/${id(pkg)}/install`, {
      method: "POST",
      body: JSON.stringify({ version }),
    }),
  activate: (pkg: string, version: string) =>
    request<{ version: string; runner: string }>(
      `/native-cli/managed/${id(pkg)}/activate`,
      { method: "POST", body: JSON.stringify({ version }) },
    ),
  rollback: (pkg: string) =>
    request<{ version: string; runner: string }>(
      `/native-cli/managed/${id(pkg)}/rollback`,
      { method: "POST" },
    ),
};
