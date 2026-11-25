const test = require("node:test");
const assert = require("node:assert/strict");
const http = require("node:http");
const { WebSocketServer } = require("ws");
const { BackendClient } = require("../backend.cjs");
async function fixture(t) {
  const received = [],
    events = [];
  let mcp = ["profit"],
    release401;
  const server = http.createServer((req, res) => {
    if (req.url === "/api/late") {
      release401 = () => {
        res.writeHead(401);
        res.end("{}");
      };
      return;
    }
    if (
      req.headers.authorization !== "Bearer valid" &&
      req.headers.authorization !== "Bearer newer"
    ) {
      res.writeHead(401);
      res.end("{}");
      return;
    }
    res.setHeader("content-type", "application/json");
    if (req.url === "/api/auth/me")
      res.end(
        JSON.stringify({
          id: 1,
          username: "fixture",
          secrets: "must-not-escape",
        }),
      );
    else if (req.url === "/api/companion/agents")
      res.end('[{"agent_id":"expert"}]');
    else if (req.url === "/api/agents/expert")
      res.end(JSON.stringify({ kind: "personal", mcp_servers: mcp }));
    else if (req.url.includes("/hitl/resume")) {
      res.setHeader("content-type", "text/event-stream");
      res.end(
        'data: {"type":"text","text":"已确认"}\n\ndata: {"type":"done"}\n\n',
      );
    } else {
      res.writeHead(404);
      res.end("{}");
    }
  });
  const ws = new WebSocketServer({ server });
  ws.on("connection", (socket) =>
    socket.on("message", (data) => received.push(JSON.parse(data))),
  );
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const client = new BackendClient(
    "http://127.0.0.1:" + server.address().port,
    (e) => events.push(e),
  );
  t.after(async () => {
    client.logout();
    for (const s of ws.clients) s.terminate();
    ws.close();
    await new Promise((resolve) => server.close(resolve));
  });
  return {
    client,
    received,
    events,
    setMCP: (value) => {
      mcp = value;
    },
    release: () => release401?.(),
  };
}
const turn = {
  board: "profit",
  agentId: "expert",
  contextKey: "context",
  frame: {
    type: "user_turn",
    thread_id: "thread",
    message: "你好",
    mcp_servers: ["forged"],
  },
};
test("each turn reloads current saved MCP bindings", async (t) => {
  const f = await fixture(t);
  const user = await f.client.acceptToken("valid");
  assert.equal(user.secrets, undefined);
  await f.client.send(turn);
  await new Promise((r) => setTimeout(r, 15));
  assert.deepEqual(f.received[0].mcp_servers, ["profit"]);
  f.setMCP(["new-grant"]);
  await f.client.send(turn);
  await new Promise((r) => setTimeout(r, 15));
  assert.deepEqual(f.received[1].mcp_servers, ["new-grant"]);
});
test("late unauthorized response cannot sign out a newer login", async (t) => {
  const f = await fixture(t);
  await f.client.acceptToken("valid");
  const late = f.client.json("/api/late");
  await new Promise((r) => setTimeout(r, 15));
  await f.client.acceptToken("newer");
  f.release();
  await late;
  assert.equal(f.client.token, "newer");
  assert.equal(
    f.events.some((e) => e.type === "authExpired"),
    false,
  );
});
test("approval resume preserves subscription and projects SSE with context", async (t) => {
  const f = await fixture(t);
  await f.client.acceptToken("valid");
  await f.client.send(turn);
  await f.client.resume({
    board: "profit",
    agentId: "expert",
    contextKey: "context",
    threadId: "thread",
    pendingId: "approval",
    decisions: [{ type: "approve" }],
  });
  await new Promise((r) => setTimeout(r, 30));
  assert.equal(
    f.received.some((v) => v.type === "subscribe"),
    false,
  );
  assert.ok(
    f.events.some(
      (e) => e.contextKey === "context" && e.data?.text === "已确认",
    ),
  );
  assert.ok(f.events.some((e) => e.data?.type === "done"));
});
