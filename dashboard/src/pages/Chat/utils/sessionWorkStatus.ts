/** Sidebar thread work status. Idle has no indicator. */
export type SessionWorkStatus = "working" | "waiting" | "complete" | "idle";

export function resolveSessionWorkStatus(
  session: {
    id: string;
    turnActive?: boolean;
    awaitingUser?: boolean;
    turnCompleted?: boolean;
  },
  liveWorkingIds: ReadonlySet<string>,
): SessionWorkStatus {
  if (session.awaitingUser) return "waiting";
  if (liveWorkingIds.has(session.id) || session.turnActive) return "working";
  return session.turnCompleted ? "complete" : "idle";
}
