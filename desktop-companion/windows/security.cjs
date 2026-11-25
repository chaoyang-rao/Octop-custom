"use strict";
const { createPublicKey, verify } = require("node:crypto");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

const PUBLIC_KEY = "OZtDL3eMhGZ7HaAf0s9I1oka+5B9V3suUG9ThhG/0aA=";
const BOARDS = new Set([
  "aftersales",
  "workbench",
  "profit",
  "knowledge",
  "team",
]);
const MIME_TYPES = new Set([
  "image/png",
  "image/jpeg",
  "image/webp",
  "image/gif",
  "application/pdf",
  "text/csv",
  "application/vnd.ms-excel",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
]);
function fail(message = "这个链接不属于本机问答引擎。") {
  throw new Error(message);
}
function origin(value) {
  let url;
  try {
    url = new URL(String(value).trim());
  } catch {
    return fail();
  }
  if (
    !["http:", "https:"].includes(url.protocol) ||
    !["127.0.0.1", "localhost", "[::1]"].includes(url.hostname.toLowerCase()) ||
    url.username ||
    url.password ||
    url.search ||
    url.hash ||
    url.pathname !== "/"
  )
    fail();
  return url.origin;
}
function sameOrigin(first, second) {
  const normalized = (value) => {
    const u = new URL(value);
    u.protocol =
      u.protocol === "ws:"
        ? "http:"
        : u.protocol === "wss:"
        ? "https:"
        : u.protocol;
    return u.origin;
  };
  try {
    return normalized(first) === normalized(second);
  } catch {
    return false;
  }
}
function apiPath(value, base) {
  if (typeof value !== "string" || value.length > 8192) fail();
  let decoded = value;
  try {
    for (let n = 0; n < 3; n++) decoded = decodeURIComponent(decoded);
  } catch {
    fail();
  }
  if (
    !decoded.startsWith("/api/") ||
    /[\\\x00-\x1f]/.test(decoded) ||
    decoded.includes("//") ||
    decoded
      .split("?")[0]
      .split("/")
      .some((s) => s === ".." || s === ".")
  )
    fail();
  const url = new URL(value, origin(base));
  if (!sameOrigin(url, base) || !url.pathname.startsWith("/api/")) fail();
  return url;
}
function segment(value, max = 160) {
  if (
    typeof value !== "string" ||
    !value.length ||
    value.length > max ||
    !/^[A-Za-z0-9_-]+$/.test(value)
  )
    fail();
  return value;
}
function threadId(value) {
  if (typeof value !== "string" || !/^[A-Za-z0-9_~-]{1,512}$/.test(value))
    fail();
  return value;
}
function chatCommand(args) {
  if (
    !args ||
    !BOARDS.has(args.board) ||
    !args.frame ||
    typeof args.frame !== "object" ||
    Array.isArray(args.frame)
  )
    fail();
  const frame = { ...args.frame };
  if (
    !["user_turn", "subscribe", "cancel", "ping", "steer_remove"].includes(
      frame.type,
    )
  )
    fail();
  if (frame.thread_id !== undefined) threadId(frame.thread_id);
  if (
    ["subscribe", "cancel", "steer_remove"].includes(frame.type) &&
    !frame.thread_id
  )
    fail();
  delete frame.hitl_policy;
  if (frame.type === "user_turn") delete frame.mcp_servers;
  return {
    board: args.board,
    agent: segment(args.agentId),
    context: segment(args.contextKey),
    frame,
  };
}
function decisions(value) {
  if (!Array.isArray(value) || value.length < 1 || value.length > 16) fail();
  for (const d of value) {
    if (
      !d ||
      !["approve", "reject", "respond"].includes(d.type) ||
      (d.message !== undefined &&
        (typeof d.message !== "string" || d.message.length > 8000)) ||
      (d.type === "respond" && !d.message?.trim())
    )
      fail();
  }
  return value;
}
function launchAction(value) {
  try {
    const u = new URL(value);
    return u.protocol === "octop-companion:" &&
      ["open", "size"].includes(u.hostname) &&
      !u.username &&
      !u.password &&
      !u.port &&
      !u.search &&
      !u.hash &&
      ["", "/"].includes(u.pathname)
      ? u.hostname
      : null;
  } catch {
    return null;
  }
}
function trustedDocument(frame, webContents, filename) {
  if (!frame || !webContents || frame !== webContents.mainFrame) return false;
  try {
    const u = new URL(frame.url);
    u.hash = "";
    return u.href === pathToFileURL(path.resolve(filename)).href;
  } catch {
    return false;
  }
}
function externalUrl(value) {
  let u;
  try {
    u = new URL(value);
  } catch {
    fail("无法打开这个链接。");
  }
  if (!["http:", "https:"].includes(u.protocol) || u.username || u.password)
    fail("无法打开这个链接。");
  return u.href;
}
function canonical(value) {
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  if (value && typeof value === "object")
    return (
      "{" +
      Object.keys(value)
        .sort()
        .map((k) => JSON.stringify(k) + ":" + canonical(value[k]))
        .join(",") +
      "}"
    );
  return JSON.stringify(value);
}
function verifyPackage(metadata, publicKey = PUBLIC_KEY) {
  if (
    !metadata ||
    Object.keys(metadata).sort().join(",") !==
      "filename,sha256,signature,size,version" ||
    !/^[A-Za-z0-9][A-Za-z0-9._-]*\.zip$/.test(metadata.filename) ||
    !/^\d+\.\d+\.\d+$/.test(metadata.version) ||
    !/^[a-f0-9]{64}$/.test(metadata.sha256) ||
    !Number.isSafeInteger(metadata.size) ||
    metadata.size <= 0 ||
    metadata.size > 2 * 1024 ** 3
  )
    fail("组件发布信息无效。");
  const raw = Buffer.from(publicKey, "base64");
  const key = createPublicKey({
    key: Buffer.concat([Buffer.from("302a300506032b6570032100", "hex"), raw]),
    format: "der",
    type: "spki",
  });
  const { signature, ...signed } = metadata;
  if (
    !verify(
      null,
      Buffer.from(canonical(signed)),
      key,
      Buffer.from(signature, "base64"),
    )
  )
    fail("组件签名校验失败。");
  return metadata;
}
class SSEDecoder {
  constructor() {
    this.buffer = "";
    this.lines = [];
    this.size = 0;
  }
  feed(chunk) {
    this.buffer += chunk;
    if (Buffer.byteLength(this.buffer) > 16 * 1024 * 1024) fail();
    const frames = [];
    for (;;) {
      const end = this.buffer.indexOf("\n");
      if (end < 0) break;
      const line = this.buffer.slice(0, end).replace(/\r$/, "");
      this.buffer = this.buffer.slice(end + 1);
      if (!line) {
        const data = this.lines.join("\n");
        this.lines = [];
        this.size = 0;
        if (data && data !== "[DONE]") {
          const parsed = JSON.parse(data);
          if (!parsed || typeof parsed !== "object" || Array.isArray(parsed))
            fail();
          frames.push(parsed);
        }
      } else if (line.startsWith("data:")) {
        const data = line.slice(5).replace(/^ /, "");
        this.size += Buffer.byteLength(data);
        if (this.size > 16 * 1024 * 1024) fail();
        this.lines.push(data);
      }
    }
    return frames;
  }
}
module.exports = {
  PUBLIC_KEY,
  BOARDS,
  MIME_TYPES,
  origin,
  sameOrigin,
  apiPath,
  segment,
  threadId,
  chatCommand,
  decisions,
  launchAction,
  trustedDocument,
  externalUrl,
  canonical,
  verifyPackage,
  SSEDecoder,
};
