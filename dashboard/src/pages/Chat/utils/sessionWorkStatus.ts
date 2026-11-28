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

/** Portraits respond only to activity in the sessions owned by their own row. */
export function sessionAvatarMotion(
  sessions: ReadonlyArray<Parameters<typeof resolveSessionWorkStatus>[0]>,
  liveWorkingIds: ReadonlySet<string>,
): "work" | "wait" | undefined {
  let waiting = false;
  for (const session of sessions) {
    const status = resolveSessionWorkStatus(session, liveWorkingIds);
    if (status === "working") return "work";
    if (status === "waiting") waiting = true;
  }
  return waiting ? "wait" : undefined;
}
