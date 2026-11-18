// Uses an isolated native bridge; no real account, model, MCP or user data.
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
for (let i = 0; i < 100; i++) {
  if (
    window.__control &&
    document.querySelector(".messages") &&
    document.querySelector("textarea")
  )
    break;
  await wait(50);
}
if (!window.__control || !document.querySelector(".messages"))
  throw Error("Native fixture did not initialize");
const control = window.__control;
control.holdThread = false;
control.holdToken = true;
await wait(300);
const results = [];
function metrics() {
  const list = document.querySelector(".messages");
  const user = Array.from(list.querySelectorAll(".message.user")).at(-1);
  return {
    top: user
      ? user.getBoundingClientRect().top - list.getBoundingClientRect().top
      : null,
    height: list.clientHeight,
    scrollTop: list.scrollTop,
    space: list.querySelector("[data-chat-reply-space]")?.style.height,
  };
}
async function settingsRoundTrip() {
  document.querySelector('button[aria-label="功能与设置"]').click();
  await wait(100);
  document.querySelector('button[aria-label="关闭设置"]').click();
  await wait(100);
}
async function resizeWindow() {
  await new Promise((resolve) => {
    window.__nativeResizeDone = resolve;
    window.webkit.messageHandlers.fixtureControl.postMessage({
      width: innerWidth,
      height: innerHeight + 60,
    });
  });
  await wait(180);
}
const firstUser = { id: "server-u1", role: "user", content: "隔离验收第1问" };
const backgroundReply = Array.from(
  { length: 30 },
  (_, i) => `原生滚动长会话背景第 ${i + 1} 行。`,
).join("\n\n");
const firstReply = {
  id: "server-a1",
  role: "assistant",
  content: backgroundReply,
};
const secondUser = { id: "server-u2", role: "user", content: "隔离验收第2问" };
let historySnapshot = null;
const post = window.__fixturePostMessage;
window.__fixturePostMessage = (message) => {
  if (
    historySnapshot &&
    message.op === "api" &&
    message.args.path.includes("/history")
  ) {
    setTimeout(
      () =>
        window.__companionReply({
          id: message.id,
          result: {
            status: 200,
            data: { messages: historySnapshot, turn_active: control.active },
          },
        }),
      5,
    );
    return;
  }
  post(message);
};
for (let i = 1; i <= 2; i++) {
  if (i === 2) await settingsRoundTrip();
  const input = document.querySelector("textarea");
  Object.getOwnPropertyDescriptor(
    HTMLTextAreaElement.prototype,
    "value",
  ).set.call(input, "隔离验收第" + i + "问");
  input.dispatchEvent(new Event("input", { bubbles: true }));
  await wait(80);
  const send = document.querySelector('button[aria-label="发送消息"]');
  if (!send || send.disabled) throw Error("Send unavailable");
  if (i === 2)
    input.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "Enter",
        code: "Enter",
        bubbles: true,
        cancelable: true,
      }),
    );
  else send.click();
  await wait(220);
  results.push({
    phase: i === 2 ? "enter-send-existing-history" : "click-send",
    ...metrics(),
  });
  if (i === 2) {
    await resizeWindow();
    results.push({ phase: "enter-send-native-resize", ...metrics() });
    historySnapshot = [firstUser, firstReply, secondUser];
    window.__companionEvent({ type: "authChanged" });
    await wait(600);
    results.push({
      phase: "enter-send-history-sync-before-token",
      ...metrics(),
    });
  }
  control.begin();
  control.emit({
    type: "token",
    content:
      i === 1 ? backgroundReply : "隔离验收第2答。\n\n仅测试原生滚动位置。",
  });
  await wait(150);
  control.finish();
  await wait(180);
  results.push({
    phase: i === 1 ? "background-complete" : "complete-2",
    ...metrics(),
  });
}
historySnapshot.push({
  id: "server-a2",
  role: "assistant",
  content: "隔离验收第2答。\n\n仅测试原生滚动位置。",
});
window.__companionEvent({ type: "authChanged" });
await wait(600);
results.push({ phase: "history-rekey", ...metrics() });
await settingsRoundTrip();
results.push({ phase: "settings-return", ...metrics() });
await resizeWindow();
results.push({ phase: "viewport-resize", ...metrics() });
for (const result of results)
  if (
    result.phase !== "background-complete" &&
    !(result.top >= 0 && result.top <= 12)
  )
    throw Error(
      "Question lost native viewport anchor: " + JSON.stringify(result),
    );
const list = document.querySelector(".messages");
list.dispatchEvent(new WheelEvent("wheel", { deltaY: -60, bubbles: true }));
list.scrollTop = Math.max(0, list.scrollTop - 60);
list.dispatchEvent(new Event("scroll"));
await wait(80);
const readerTop = list.scrollTop;
control.emit({ type: "token", content: "\n\n后续内容保留上翻阅读位置。" });
await wait(160);
if (Math.abs(list.scrollTop - readerTop) > 1)
  throw Error("Manual native scroll was overridden");
if (window.__nativeErrors?.length)
  throw Error(window.__nativeErrors.join("; "));
return JSON.stringify({
  native_webkit: true,
  passed: true,
  viewport: { width: innerWidth, height: innerHeight },
  results,
  errors: window.__nativeErrors || [],
});
