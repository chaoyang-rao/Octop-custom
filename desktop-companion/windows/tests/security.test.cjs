const test = require("node:test");
const assert = require("node:assert/strict");
const { generateKeyPairSync, sign } = require("node:crypto");
const policy = require("../security.cjs");
const { safeEntry } = require("../archive.cjs");
const g = require("../geometry.cjs");
test("loopback-only bearer paths reject traversal, credentials and external URLs", () => {
  for (const base of [
    "https://example.com",
    "file:///tmp/x",
    "http://user@localhost",
    "http://localhost/path",
  ])
    assert.throws(() => policy.origin(base));
  for (const value of [
    "//example.com/api/x",
    "/api/../auth",
    "/api/%252e%252e/x",
    "/api/\\evil",
    "/api/%00/x",
  ])
    assert.throws(() => policy.apiPath(value, "http://127.0.0.1:18588"));
  assert.equal(
    policy.apiPath("/api/agents/a?cursor=next", "http://127.0.0.1:18588")
      .origin,
    "http://127.0.0.1:18588",
  );
});
test("renderer cannot override saved expert MCP binding or auto approve", () => {
  const c = policy.chatCommand({
    board: "profit",
    agentId: "a",
    contextKey: "c",
    frame: {
      type: "user_turn",
      mcp_servers: ["unrelated"],
      hitl_policy: "auto",
    },
  });
  assert.equal(c.frame.mcp_servers, undefined);
  assert.equal(c.frame.hitl_policy, undefined);
  assert.throws(() => policy.decisions([{ type: "respond", message: "" }]));
  assert.throws(() =>
    policy.chatCommand({
      board: "team",
      agentId: "../x",
      contextKey: "c",
      frame: { type: "cancel", thread_id: "a" },
    }),
  );
});
test("signed packages reject tampering and extra fields", () => {
  const { publicKey, privateKey } = generateKeyPairSync("ed25519");
  const key = publicKey
    .export({ format: "der", type: "spki" })
    .subarray(-32)
    .toString("base64");
  const data = {
    filename: "artwork-1.0.0.zip",
    version: "1.0.0",
    size: 100,
    sha256: "a".repeat(64),
  };
  const metadata = {
    ...data,
    signature: sign(
      null,
      Buffer.from(policy.canonical(data)),
      privateKey,
    ).toString("base64"),
  };
  assert.equal(policy.verifyPackage(metadata, key), metadata);
  assert.throws(() => policy.verifyPackage({ ...metadata, size: 101 }, key));
  assert.throws(() =>
    policy.verifyPackage({ ...metadata, platform: "win" }, key),
  );
});
test("safe Windows ZIP filenames reject drive paths, devices, collisions aliases and symlinks", () => {
  for (const name of [
    "../x",
    "Dora/../x",
    "C:/x",
    "Dora/a\\b",
    "Dora/NUL.txt",
    "Dora/name.",
    "Dora/foo:bar",
    "/Dora/a",
  ])
    assert.throws(() => safeEntry(name));
  assert.deepEqual(safeEntry("Dora/resources/app/main.cjs"), [
    "Dora",
    "resources",
    "app",
    "main.cjs",
  ]);
});
test("SSE splits, CRLF and multiline JSON retain Chinese text", () => {
  const decoder = new policy.SSEDecoder();
  assert.deepEqual(decoder.feed('data: {"type":"text",\r\n'), []);
  assert.deepEqual(
    decoder.feed('data: "text":"你好"}\r\n\r\ndata: [DONE]\n\n'),
    [{ type: "text", text: "你好" }],
  );
});
test("inward facing, adjacent monitor exclusions and small right edge peek", () => {
  const a = { x: 0, y: 0, width: 1920, height: 1080 },
    f = { x: 1762, y: 800, width: 158, height: 158 };
  assert.equal(g.facing(f, a, false), true);
  assert.equal(g.facing({ ...f, x: 0 }, a, true), false);
  assert.equal(g.dock(f, a, [a]), "right");
  assert.equal(
    g.dock(f, a, [a, { x: 1920, y: 0, width: 1920, height: 1080 }]),
    null,
  );
  const peek = g.peekFrame(
    f,
    a,
    "right",
    { crop: [0.49, 0.14, 0.42, 0.75], headWidth: 0.6, grip: 0.882 },
    { headWidth: 0.526 },
  );
  assert.ok(peek.width < 65);
  assert.ok(peek.x < 1920 && peek.x + peek.width > 1920);
  const resized = g.fullFrame(f, 237, a);
  assert.equal(resized.y + resized.height, f.y + f.height);
  assert.ok(resized.x + resized.width <= 1920);
});
