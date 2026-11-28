import { afterEach, beforeEach, expect, it, vi } from "vitest";
import * as store from "./chatStore";
import { clearInflightTail } from "../utils/inflightTranscriptCache";

const session = "reconnect-ordering";
class Socket {
  static instances: Socket[] = [];
  static OPEN = 1;
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  sent: string[] = [];
  constructor() {
    Socket.instances.push(this);
    queueMicrotask(() => {
      this.readyState = 1;
      this.onopen?.();
    });
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    this.readyState = 3;
    this.onclose?.();
  }
  frame(data: object) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }
}

beforeEach(() => {
  Socket.instances = [];
  vi.stubGlobal("WebSocket", Socket);
});
afterEach(() => {
  store.removeSession(session);
  clearInflightTail(session);
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

it("finishes each coordinator turn on a retained team send socket", async () => {
  store.setSessionTeamRoom(session, true);
  const onEnd = vi.fn();
  const sent = store.sendTurn(
    session,
    "question",
    "room",
    "",
    undefined,
    onEnd,
    null,
    session,
  );
  await Promise.resolve();
  const ws = Socket.instances[0];
  for (const turnId of ["user-turn", "coordinator-review"]) {
    ws.frame({ type: "turn.started", turn_id: turnId });
    ws.frame({
      type: "token",
      content: turnId,
      agent_id: "room",
      speaker_agent_id: "lead",
      turn_owner_agent_id: "room",
      team_wrapup: turnId === "coordinator-review",
    });
    ws.frame({
      type: "done",
      agent_id: "room",
      speaker_agent_id: "lead",
      turn_owner_agent_id: "room",
      team_wrapup: turnId === "coordinator-review",
    });
    ws.frame({ type: "turn.ended", turn_id: turnId });
    expect(store.getSnapshot(session).isStreaming).toBe(false);
    expect(store.getSnapshot(session).activeTurnId).toBeNull();
    expect(store.getSnapshot(session).liveSpeakers).toEqual([]);
    expect(
      store.getSnapshot(session).messages.some((m) => m.status === "streaming"),
    ).toBe(false);
    expect(ws.readyState).toBe(Socket.OPEN);
  }
  await sent;
  expect(onEnd).toHaveBeenCalledTimes(2);
  ws.frame({ type: "turn.ended", turn_id: "coordinator-review" });
  expect(onEnd).toHaveBeenCalledTimes(2);
});

it("finishes repeated turns on a retained subscription socket", async () => {
  store.setSessionTeamRoom(session, true);
  const onEnd = vi.fn();
  await store.attachThread(session, "room", session, onEnd);
  const ws = Socket.instances[0];
  for (const turnId of ["review-one", "review-two"]) {
    ws.frame({ type: "turn.started", turn_id: turnId });
    ws.frame({ type: "token", content: turnId, agent_id: "room" });
    ws.frame({ type: "done", agent_id: "room" });
    ws.frame({ type: "turn.ended", turn_id: turnId });
    expect(store.getSnapshot(session).isStreaming).toBe(false);
  }
  expect(onEnd).toHaveBeenCalledTimes(2);
  expect(ws.sent.map((row) => JSON.parse(row).type)).toEqual(["subscribe"]);
});

it("unlocks the host on authoritative idle while keeping a member live", async () => {
  store.setSessionTeamRoom(session, true);
  const onEnd = vi.fn();
  await store.attachThread(session, "room", session, onEnd);
  const ws = Socket.instances[0];
  ws.frame({ type: "turn_status", active: true });
  ws.frame({ type: "token", content: "host conclusion", agent_id: "room" });
  ws.frame({ type: "token", content: "member output", agent_id: "member" });
  ws.frame({ type: "turn_status", active: false });
  const snap = store.getSnapshot(session);
  expect(snap.isStreaming).toBe(false);
  expect(snap.messages.find((m) => m.speakerAgentId === "room")?.status).toBe(
    "done",
  );
  expect(snap.messages.find((m) => m.speakerAgentId === "member")?.status).toBe(
    "streaming",
  );
  expect(snap.liveSpeakers).toEqual(["member"]);
  expect(ws.readyState).toBe(Socket.OPEN);
  expect(ws.sent.some((row) => JSON.parse(row).type === "cancel")).toBe(false);
});

it("ignores late frames and close events from a replaced socket", async () => {
  const first = store.sendTurn(
    session,
    "first",
    "agent",
    "",
    undefined,
    undefined,
    null,
    session,
  );
  await Promise.resolve();
  const old = Socket.instances[0];
  old.frame({ type: "turn.started", turn_id: "old" });
  old.frame({ type: "token", content: "first reply" });
  old.frame({ type: "turn.ended", turn_id: "old" });
  await first;
  store.appendUserMessage(session, {
    id: "new-user",
    role: "user",
    content: "next",
    timestamp: 1,
  });
  const second = store.sendTurn(
    session,
    "second",
    "agent",
    "",
    undefined,
    undefined,
    null,
    session,
  );
  await Promise.resolve();
  const current = Socket.instances[1];
  current.frame({
    type: "turn.started",
    turn_id: "new",
  });
  old.frame({ type: "token", content: "ghost old reply" });
  old.frame({ type: "turn.ended", turn_id: "old" });
  old.close();
  current.frame({ type: "turn.ended", turn_id: "old" });
  expect(store.getSnapshot(session).activeTurnId).toBe("new");
  expect(store.getSnapshot(session).isStreaming).toBe(true);
  expect(
    store.getSnapshot(session).messages.find((m) => m.id === "new-user")
      ?.localPending,
  ).toBe(true);
  current.frame({ type: "token", content: "second reply" });
  current.frame({ type: "turn.ended", turn_id: "new" });
  await second;
  expect(store.getSnapshot(session).messages.map((m) => m.content)).toEqual([
    "first reply",
    "next",
    "second reply",
  ]);
});

it("reconnects by subscribing without resending the user message", async () => {
  vi.useFakeTimers();
  const sent = store.sendTurn(
    session,
    "question",
    "agent",
    "",
    undefined,
    undefined,
    null,
    session,
  );
  await Promise.resolve();
  const old = Socket.instances[0];
  old.frame({ type: "token", content: "first" });
  old.close();
  await sent;
  await vi.advanceTimersByTimeAsync(400);
  const resumed = Socket.instances[1];
  expect(resumed).toBeDefined();
  expect(resumed.sent.map((row) => JSON.parse(row).type)).toEqual([
    "subscribe",
  ]);
  resumed.frame({
    type: "turn_status",
    active: true,
    thread_id: session,
  });
  old.frame({ type: "token", content: "ghost" });
  resumed.frame({ type: "token", content: " second" });
  resumed.frame({ type: "done" });
  expect(store.getSnapshot(session).messages.at(-1)?.content).toBe(
    "first second",
  );
  expect(store.getSnapshot(session).isStreaming).toBe(false);
});
