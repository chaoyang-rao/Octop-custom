import { request, requestUpload } from "../request";

export const octopAgentsApi = {
  copyExpert: (agentId: string, name?: string) =>
    request<{ agent_id: string; name: string }>(
      `/agents/${encodeURIComponent(agentId)}/copy`,
      { method: "POST", body: JSON.stringify(name ? { name } : {}) },
    ),
  reuseCli: (agentId: string, agent_ids: string[]) =>
    request<{ agent_ids: string[] }>(
      `/agents/${encodeURIComponent(agentId)}/cli/reuse`,
      { method: "POST", body: JSON.stringify({ agent_ids }) },
    ),
  markRead: (agentId: string) =>
    request<void>(`/agents/${encodeURIComponent(agentId)}/read`, {
      method: "POST",
    }),

  uploadAvatar: (agentId: string, file: File) => {
    const body = new FormData();
    body.append("file", file);
    return requestUpload<{ icon_url: string }>(
      `/agents/${encodeURIComponent(agentId)}/avatar`,
      body,
    );
  },

  deleteAvatar: (agentId: string) =>
    request<void>(`/agents/${encodeURIComponent(agentId)}/avatar`, {
      method: "DELETE",
    }),
};
