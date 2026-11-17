import {
  normalizeHitlRequest,
  type HitlPendingPayload,
} from "../../dashboard/src/api/types/hitl.ts";
import type { Attachment } from "./core.ts";

export type QueuedInput = { id: string; text: string; files: Attachment[] };
export type Approval = HitlPendingPayload & {
  agentId: string;
  status: "pending" | "submitting" | "approved" | "rejected";
  error?: string;
};
export function chatCommand(
  board: string,
  room: { binding: { agentId: string }; conversationId: string },
  frame: Record<string, unknown>,
) {
  return {
    board,
    agentId: room.binding.agentId,
    contextKey: room.conversationId,
    frame,
  };
}
export function pendingApproval(
  raw: unknown,
  agentId: string,
): Approval | undefined {
  const value = normalizeHitlRequest(raw);
  if (!Array.isArray(value.action_requests) || !value.action_requests.length)
    return;
  return {
    ...value,
    action_requests: value.action_requests,
    pending_id:
      typeof value.pending_id === "string" ? value.pending_id : undefined,
    agentId,
    status: "pending",
  } as Approval;
}
export function attachmentMime(name: string, type: string): string | null {
  const extension = name.split(".").at(-1)?.toLowerCase();
  const docs: Record<string, string> = {
    pdf: "application/pdf",
    csv: "text/csv",
    xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    xls: "application/vnd.ms-excel",
  };
  if (extension && docs[extension]) return docs[extension];
  return /^image\/(png|jpeg|webp|gif)$/.test(type) ? type : null;
}
export function safeQueuedInputs(raw: unknown): QueuedInput[] {
  if (!Array.isArray(raw)) return [];
  return raw.filter(
    (v): v is QueuedInput =>
      !!v &&
      typeof v.id === "string" &&
      typeof v.text === "string" &&
      Array.isArray(v.files) &&
      v.files.every(
        (f: Attachment) =>
          !!f &&
          typeof f.path === "string" &&
          typeof f.filename === "string" &&
          typeof f.media_type === "string",
      ),
  );
}
export function canFlushQueue(room: {
  busy: boolean;
  activeTurnId?: string;
  approvalStreamActive?: boolean;
  awaitingApproval?: boolean;
  stopping?: boolean;
  queuePaused?: boolean;
  approvals: Approval[];
  error?: string;
  queue: QueuedInput[];
  teamSpeakers?:string[];
}): boolean {
  return (
    !!room.queue.length &&
    !room.busy &&
    !room.teamSpeakers?.length &&
    !room.activeTurnId &&
    !room.approvalStreamActive &&
    !room.awaitingApproval &&
    !room.stopping &&
    !room.queuePaused &&
    !room.error &&
    !room.approvals.some((a) => ["pending", "submitting"].includes(a.status))
  );
}
