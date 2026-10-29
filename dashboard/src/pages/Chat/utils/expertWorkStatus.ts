/** Account-visible expert activity. Runtime "running" alone means enabled. */
export type ExpertWorkStatus =
  | "working"
  | "waiting"
  | "idle"
  | "stopped"
  | "starting"
  | "stopping"
  | "failed"
  | "unknown";

export type ExpertWorkKind =
  | ExpertWorkStatus
  | "online"
  | "remote_online"
  | "disconnected";

export interface ExpertWorkInput {
  state?: string;
  bridge?: boolean;
  bridge_disconnected?: boolean;
  work_status?: string;
  working_count?: number;
  waiting_count?: number;
}

export interface ExpertWorkBadge {
  kind: ExpertWorkKind;
  count: number | null;
}

export function deriveExpertWorkStatus(
  agent: ExpertWorkInput,
): ExpertWorkBadge[] {
  if (agent.bridge_disconnected) return [{ kind: "disconnected", count: null }];
  const status = agent.work_status;
  const lifecycle =
    agent.state === "failed" || agent.state === "error"
      ? "failed"
      : agent.state === "created" || agent.state === "stopped"
      ? "stopped"
      : agent.state === "starting" || agent.state === "stopping"
      ? agent.state
      : status === "stopped" ||
        status === "starting" ||
        status === "stopping" ||
        status === "failed"
      ? status
      : null;
  if (lifecycle) return [{ kind: lifecycle, count: null }];
  if (status === "unknown") return [{ kind: "unknown", count: null }];
  if (status !== "working" && status !== "waiting" && status !== "idle") {
    return [
      {
        kind: agent.bridge
          ? "remote_online"
          : agent.state === "running"
          ? "online"
          : "unknown",
        count: null,
      },
    ];
  }
  const count = (value: number | undefined): number | null =>
    typeof value === "number" && Number.isSafeInteger(value) && value >= 0
      ? value
      : null;
  const working = count(agent.working_count);
  const waiting = count(agent.waiting_count);
  const badges: ExpertWorkBadge[] = [];
  if (status === "working" || (working ?? 0) > 0)
    badges.push({
      kind: "working",
      count: working && working > 0 ? working : null,
    });
  if (status === "waiting" || (waiting ?? 0) > 0)
    badges.push({
      kind: "waiting",
      count: waiting && waiting > 0 ? waiting : null,
    });
  return badges.length ? badges : [{ kind: "idle", count: null }];
}
