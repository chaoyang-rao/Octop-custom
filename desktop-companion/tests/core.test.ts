import assert from "node:assert/strict";
import test from "node:test";
import {
  acceptsRoomEvent,
  consumeFrame,
  contentImages,
  historyMessages,
  initialBinding,
  normalizeAgents,
  resolveImageSource,
  safeImageSource,
  sessionKey,
  settingsKey,
  turnPayload,
} from "../web/core.ts";

test("fresh installs bind each board to its corresponding published expert", () => {
  const agents = [
    { id: "quality-copy", name: "售后质量专家" },
    { id: "knowledge-copy", name: "知识库助手" },
    { id: "quota-copy", name: "词元管理专家" },
    { id: "profit-copy", name: "负利润专家" },
  ];
  assert.equal(
    initialBinding("aftersales", agents, []).agentId,
    "quality-copy",
  );
  assert.equal(initialBinding("workbench", agents, []).agentId, "quota-copy");
  assert.equal(
    initialBinding("profit", agents, [
      { id: "negative-profit", name: "负利润 MCP" },
    ]).agentId,
    "profit-copy",
  );
  assert.deepEqual(
    initialBinding("profit", agents, [
      { id: "negative-profit", name: "负利润 MCP" },
      { id: "quality", name: "售后质量" },
    ]).connectors,
    ["negative-profit"],
  );
  assert.equal(
    initialBinding("knowledge", agents, []).agentId,
    "knowledge-copy",
  );
});

test("knowledge questions inherit saved expert resources without manual selection", () => {
  const binding = initialBinding(
    "knowledge",
    [{ id: "knowledge-copy", name: "知识库助手" }],
    [{ id: "knowledge-mcp", name: "知识库 MCP" }],
  );
  const payload = turnPayload(
    binding,
    "own-context",
    "只解释本轮提供的资料",
    [],
  );
  assert.equal("mcp_servers" in payload, false);
  assert.equal("knowledge_base_ids" in payload, false);
});

test("board and identity sessions cannot overwrite dashboard default or each other", () => {
  const keys = [
    sessionKey("main", 2, "aftersales", "one"),
    sessionKey("main", 2, "workbench", "one"),
    sessionKey("main", 3, "aftersales", "one"),
    sessionKey("other", 2, "aftersales", "one"),
    sessionKey("main", 2, "profit", "one"),
  ];
  assert.equal(new Set(keys).size, 5);
  assert.ok(keys.every((key) => key !== "main:dashboard:2:dm"));
  assert.notEqual(
    settingsKey("http://127.0.0.1:8088", 2),
    settingsKey("http://127.0.0.1:8088", 3),
  );
});
test("companion inherits expert MCPs even when legacy boards selected another connector", () => {
  const body = turnPayload(
    { agentId: "a", connectors: ["legacy-other-mcp"], knowledgeBases: ["kb"] },
    "scoped",
    " question ",
    [{ path: "inbound/p.png", filename: "p.png", media_type: "image/png" }],
    "owned",
  );
  assert.equal("mcp_servers" in body, false);
  assert.deepEqual(body.knowledge_base_ids, ["kb"]);
  assert.equal("hitl_policy" in body, false);
  assert.equal("conversation_mode" in body, false);
  assert.equal(body.thread_id, "owned");
  assert.equal(body.messages[0].content[1].type, "image_url");
  assert.equal(body.messages[0].content[1].workspace_path, "inbound/p.png");
});
test("empty knowledge selection preserves the expert's saved knowledge defaults", () => {
  const body = turnPayload(
    { agentId: "a", connectors: [], knowledgeBases: [] },
    "scoped",
    "hello",
    [],
  );
  assert.equal("mcp_servers" in body, false);
  assert.equal("knowledge_base_ids" in body, false);
});
test("only owned agents are offered even when an admin response includes other users", () => {
  assert.deepEqual(
    normalizeAgents(
      [
        { agent_id: "mine", owner_user_id: 2 },
        { agent_id: "other", user_id: 3 },
      ],
      2,
    ).map((v) => v.id),
    ["mine"],
  );
});
test("image sources reject local file, script and network-path URLs", () => {
  for (const value of [
    "file:///etc/passwd",
    "javascript:alert(1)",
    "//example.org/a.png",
    "data:text/html;base64,YQ==",
    "/api/../secret",
  ])
    assert.equal(safeImageSource(value), null);
  assert.deepEqual(
    contentImages({
      messages: [
        {
          content: [
            {
              type: "image_url",
              image_url: { url: "/api/agents/a/files/result.png" },
            },
          ],
        },
      ],
    }),
    ["/api/agents/a/files/result.png"],
  );
});
test("member responses retain authors and process details stay separate from visible text", () => {
  let messages = consumeFrame(
    [],
    { type: "token", content: "First", agent_id: "a" },
    (id) => id,
  );
  messages = consumeFrame(
    messages,
    { type: "reasoning", content: "private process", agent_id: "a" },
    (id) => id,
  );
  messages = consumeFrame(
    messages,
    { type: "token", content: "Second", agent_id: "b" },
    (id) => id,
  );
  assert.equal(messages.length, 2);
  assert.equal(messages[0].text, "First");
  assert.equal(messages[0].reasoning, "private process");
  assert.equal(messages[1].speaker, "b");
});
test("late stream events cannot enter a newly opened conversation or changed expert", () => {
  const room = { conversationId: "new", threadId: "thread-new" };
  assert.equal(
    acceptsRoomEvent(room, { contextKey: "old", threadId: "thread-new" }),
    false,
  );
  assert.equal(
    acceptsRoomEvent(room, { contextKey: "new", threadId: "thread-old" }),
    false,
  );
  assert.equal(
    acceptsRoomEvent({ conversationId: "new" }, { contextKey: "old" }),
    false,
  );
  assert.equal(
    acceptsRoomEvent(room, { contextKey: "new", threadId: "thread-new" }),
    true,
  );
});
test("real image-generation tool envelopes survive JSON tool messages and history reloads", () => {
  const payload = JSON.stringify({
    schema_version: 1,
    type: "image_gen_tool_result",
    status: "completed",
    images: [
      {
        path: "outbound/generated/image/check.png",
        localPath: "/private/agent/outbound/generated/image/check.png",
        mediaType: "image/png",
        sizeBytes: 10,
      },
    ],
  });
  const expected =
    "/api/agents/main/media/preview?source=outbound%2Fgenerated%2Fimage%2Fcheck.png&mime_type=image%2Fpng";
  assert.deepEqual(
    contentImages({ messages: [{ content: payload }] }, "main"),
    [expected],
  );
  const history = historyMessages(
    {
      messages: [
        { role: "assistant", content: "" },
        { role: "tool", content: payload },
        { role: "assistant", content: "图片已生成" },
      ],
    },
    "main",
  );
  assert.deepEqual(history[0].images, [expected]);
  assert.equal(history[1].text, "图片已生成");
  assert.equal(resolveImageSource("outbound/../secret.png", "main"), null);
  assert.equal(resolveImageSource("file:///etc/private.png", "main"), null);
  assert.deepEqual(
    contentImages({ type: "attachment", mime_type: "image/png", data: "eA==" }),
    ["data:image/png;base64,eA=="],
  );
});
