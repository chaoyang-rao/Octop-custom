"use strict";

// Process-local ingress adapter. Business routes and application source remain unchanged.
const http = require("node:http");
const allowed = new Set(["127.0.0.1", "::1", ...(process.env.OCTOP_MCP_GATEWAY_IPS || "120.79.0.171").split(",").map(v => v.trim()).filter(Boolean)]);
function mcpPath(raw) {
  try {
    const target = raw || "/";
    let path = new URL(target.startsWith("/") ? "http://localhost" + target : target, "http://localhost").pathname;
    for (let i = 0; i < 3; i += 1) {
      const next = decodeURIComponent(path);
      if (next === path) break;
      path = next;
    }
    return /^\/mcp(?:\/|$)/i.test(path.replace(/\/+/g, "/"));
  } catch { return /^\/mcp/i.test(raw || ""); }
}
function allowedRequest(request) {
  if (!mcpPath(request.url)) return true;
  const peer = String(request.socket?.remoteAddress || "").replace(/^::ffff:/i, "");
  if (!allowed.has(peer)) return false;
  // Proxied public requests must not inherit a loopback source identity.
  return !["forwarded", "x-forwarded-for", "x-real-ip"].some(name => Object.hasOwn(request.headers || {}, name));
}
const installed = Symbol.for("octop.negative.mcp.ingress");
if (!http.Server.prototype[installed]) {
  const original = http.Server.prototype.emit;
  http.Server.prototype.emit = function (event, request, response, ...rest) {
    if (event === "request" && !allowedRequest(request)) {
      response.writeHead(403, {"Content-Type":"application/json","Cache-Control":"no-store"});
      response.end(JSON.stringify({error:"MCP requests must use the company gateway"}));
      return true;
    }
    return original.call(this, event, request, response, ...rest);
  };
  http.Server.prototype[installed] = true;
}
module.exports = { mcpPath, allowedRequest };
