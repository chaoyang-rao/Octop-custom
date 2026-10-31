// Octop-owned Pi extension. All operations execute through the existing Graph bridge.
import fs from "node:fs";

async function boundedJson(response) {
  if (!response.ok || !response.body) throw new Error("Octop tool bridge unavailable");
  const reader = response.body.getReader();
  const chunks = [];
  let size = 0;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > 33554432) {
      await reader.cancel();
      throw new Error("Octop tool result exceeded its limit");
    }
    chunks.push(Buffer.from(value));
  }
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

export default function octopTools(pi) {
  const filename = process.env.OCTOP_PI_TOOL_CONFIG;
  if (!filename) throw new Error("Octop tool configuration required");
  const config = JSON.parse(fs.readFileSync(filename, "utf8"));
  const names = config.tools.map((tool) => tool.name);
  for (const tool of config.tools) {
    pi.registerTool({
      name: tool.name,
      label: tool.name,
      description: tool.description,
      parameters: tool.inputSchema,
      exposure: "direct",
      async execute(toolCallId, parameters, signal) {
        const reply = await boundedJson(await fetch(config.url, {
          method: "POST",
          headers: { ...config.headers, "Content-Type": "application/json" },
          body: JSON.stringify({ jsonrpc: "2.0", id: toolCallId, method: "tools/call",
            params: { name: tool.name, arguments: parameters } }),
          redirect: "error",
          signal,
        }));
        if (reply.error || !reply.result || !Array.isArray(reply.result.content)) {
          throw new Error("Octop tool execution failed");
        }
        const result = reply.result;
        return { content: result.content, details: result.structuredContent,
          ...(result.structuredContent ? { structuredContent: result.structuredContent } : {}),
          isError: result.isError === true };
      },
    });
  }
  // --no-tools prevents discovery from selecting builtins/MCP tools. Only these
  // explicitly registered names may become active, including after resume.
  pi.on("session_start", () => { pi.setActiveTools(names); });
  pi.on("before_agent_start", () => { pi.setActiveTools(names); });
  pi.on("tool_call", (event) => names.includes(event.toolName)
    ? undefined : { block: true, reason: "Tool is not registered with Octop" });
}
