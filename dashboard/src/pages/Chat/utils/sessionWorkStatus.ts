/** Sidebar thread work status. Idle has no indicator. */
export type SessionWorkStatus = "working" | "waiting" | "complete" | "idle";

export function resolveSessionWorkStatus(
  session: {
    id: string;
    turnActive?: boolean;
    awaitingUser?: boolean;
    unreadReplyId?: string | null;
  },
  liveWorkingIds: ReadonlySet<string>,
  activeId?: string | null,
): SessionWorkStatus {
  if (session.awaitingUser) return "waiting";
  if (liveWorkingIds.has(session.id) || session.turnActive) return "working";
  return session.unreadReplyId && session.id !== activeId ? "complete" : "idle";
}
