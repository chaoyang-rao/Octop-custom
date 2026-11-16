import { request } from "../request";

export type ManagedMcpId =
  | "aftersales-quality"
  | "quota-workbench"
  | "negative-profit";
export interface MemberAccessRow {
  user_id: number;
  username: string;
  display_name: string;
  disabled: boolean;
  verified: boolean;
  mcp_ids: ManagedMcpId[];
  companion: boolean;
}
export interface MemberAccessState {
  etag: string;
  configured: boolean;
  revision: number;
  members: MemberAccessRow[];
  services: {
    entry_id: ManagedMcpId;
    configured: boolean;
    owner_name: string | null;
  }[];
}
const path = "/enterprise/access/admin";
export const memberAccessApi = {
  read: () => request<MemberAccessState>(path),
  save: (members: MemberAccessRow[], expected_etag: string) =>
    request<MemberAccessState>(path, {
      method: "PUT",
      body: JSON.stringify({
        expected_etag,
        members: members.map(({ user_id, mcp_ids, companion }) => ({
          user_id,
          mcp_ids,
          companion,
        })),
      }),
    }),
  choices: (id: ManagedMcpId) =>
    request<{
      identity_name: string;
      accounts: { account_id: string; label: string }[];
    }>(`${path}/services/${id}/accounts`),
  connect: (id: ManagedMcpId, account_id: string, expected_etag: string) =>
    request<MemberAccessState>(`${path}/services/${id}`, {
      method: "PUT",
      body: JSON.stringify({ account_id, expected_etag }),
    }),
};
