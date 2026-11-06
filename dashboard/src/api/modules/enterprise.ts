import { request } from "../request";
import type { OctopUser } from "./auth";

export interface EnterpriseChallenge {
  login_id: string;
  user_code: string;
  verification_uri: string;
  expires_at: number;
  interval: number;
}

export interface EnterpriseLoginResult {
  status: "pending" | "approved" | "expired" | "confirm";
  company_name?: string;
  local_name?: string;
  access_token?: string;
  user?: OctopUser;
}

export interface CompanyDevice {
  device_id: string;
  name: string;
  revoked_at: number | null;
}

export const enterpriseApi = {
  begin: (name: string, bind_current = false) =>
    request<EnterpriseChallenge>("/auth/enterprise/start", {
      method: "POST",
      body: JSON.stringify({ name, bind_current }),
    }),
  poll: (login_id: string, confirmed = false) =>
    request<EnterpriseLoginResult>("/auth/enterprise/poll", {
      method: "POST",
      body: JSON.stringify({ login_id, confirmed }),
    }),
  inspect: (code: string) =>
    request<{ name: string }>("/enterprise/pairings/inspect", {
      method: "POST",
      body: JSON.stringify({ code }),
    }),
  approve: (code: string) =>
    request<CompanyDevice>("/enterprise/pairings/approve", {
      method: "POST",
      body: JSON.stringify({ code }),
    }),
  devices: (userId?: number) =>
    request<CompanyDevice[]>(
      `/enterprise/devices${userId ? `?user_id=${userId}` : ""}`,
    ),
  revoke: (id: string, userId?: number) =>
    request<void>(
      `/enterprise/devices/${encodeURIComponent(id)}${
        userId ? `?user_id=${userId}` : ""
      }`,
      { method: "DELETE" },
    ),
};
