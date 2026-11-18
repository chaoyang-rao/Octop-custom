// Reuse the isolated protocol fixture without an account, model or MCP service.
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url));
const source = fs.readFileSync(
  path.join(directory, "chat-controls-ui.js"),
  "utf8",
);
const check = vm.runInNewContext(source + "\nrunControlChecks;");
const stop = new Error("fixture captured");
let fixture;
try {
  await check({
    addInitScript(callback) {
      fixture = callback.toString();
      throw stop;
    },
  });
} catch (error) {
  if (error !== stop) throw error;
}
if (!fixture) throw new Error("Native bridge fixture not captured");
const bridge = `
(function(window) { (${fixture})(); })(new Proxy(window, {
  get(target, key) { return Reflect.get(target, key, target); },
  set(target, key, value) {
    if (key === "webkit") {
      target.__fixturePostMessage = value.messageHandlers.companion.postMessage;
      return true;
    }
    return Reflect.set(target, key, value, target);
  }
}));
window.__nativeErrors = [];
window.addEventListener("error", event => window.__nativeErrors.push(event.message));
`;
fs.writeFileSync(process.argv[2], bridge);
