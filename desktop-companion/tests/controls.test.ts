import assert from "node:assert/strict";
import test from "node:test";
import {
  attachmentMime,
  canFlushQueue,
  chatCommand,
  pendingApproval,
  safeQueuedInputs,
} from "../web/controls.ts";
import { historyMessages, turnPayload } from "../web/core.ts";

test("every chat control preserves board, expert and conversation identity", () => {
  const room = { binding: { agentId: "owned" }, conversationId: "context-1" };
  for (const type of ["cancel", "subscribe", "steer_remove", "user_turn"]) {
    const result = chatCommand("profit", room, { type, thread_id: "thread-1" });
    assert.equal(result.contextKey, "context-1");
    assert.equal(result.agentId, "owned");
    assert.equal(result.board, "profit");
  }
});
test("queued work waits for end, explicit resume, approval and a healthy connection", () => {
  const value = {
    busy: false,
    approvals: [],
    queue: [{ id: "q", text: "next", files: [] }],
  };
  assert.equal(canFlushQueue(value), true);
  for (const extra of [
    { busy: true },
    { activeTurnId: "old-turn" },
    { stopping: true },
    { queuePaused: true },
    { awaitingApproval: true },
    { approvalStreamActive: true },
    { error: "offline" },
  ])
    assert.equal(canFlushQueue({ ...value, ...extra }), false);
  const approval = pendingApproval(
    { value: { pending_id: "p", action_requests: [{ name: "tool" }] } },
    "owned",
  )!;
  assert.equal(canFlushQueue({ ...value, approvals: [approval] }), false);
  assert.equal(
    canFlushQueue({
      ...value,
      approvals: [{ ...approval, status: "submitting" }],
    }),
    false,
  );
  assert.equal(
    canFlushQueue({
      ...value,
      approvals: [{ ...approval, status: "approved" }],
    }),
    true,
  );
});
test("saved queues reject broken records and preserve file references", () => {
  assert.deepEqual(
    safeQueuedInputs([
      null,
      {},
      {
        id: "q",
        text: "",
        files: [
          {
            path: "inbound/data.csv",
            filename: "data.csv",
            media_type: "text/csv",
          },
        ],
      },
    ]).map((q) => q.id),
    ["q"],
  );
});
test("document uploads tolerate empty platform MIME but reject executable files", () => {
  assert.equal(
    attachmentMime("REPORT.XLSX", ""),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  );
  assert.equal(attachmentMime("rows.csv", "text/plain"), "text/csv");
  assert.equal(attachmentMime("report.pdf", ""), "application/pdf");
  assert.equal(attachmentMime("run.sh", "text/plain"), null);
});
test("documents use file blocks and pictures retain vision blocks", () => {
  const attachments = [
    { path: "inbound/a.csv", filename: "a.csv", media_type: "text/csv" },
    { path: "inbound/a.png", filename: "a.png", media_type: "image/png" },
  ];
  const frame = turnPayload(
    { agentId: "own", connectors: [], knowledgeBases: [] },
    "key",
    "analyze",
    attachments,
  );
  assert.equal(frame.messages[0].content[1].type, "file");
  assert.equal(frame.messages[0].content[2].type, "image_url");
  assert.equal("hitl_policy" in frame, false);
  const restored = historyMessages(
    { messages: [{ role: "user", content: frame.messages[0].content }] },
    "own",
  );
  assert.deepEqual(restored[0].attachments, attachments);
});
