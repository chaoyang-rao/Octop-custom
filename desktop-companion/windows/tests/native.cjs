// Real Electron windows and production IPC/HTTP/WS code, isolated synthetic service/artwork.
// This fixture never signs in to a real employee account or ships in the application.
const { app, BrowserWindow, nativeImage, Menu } = require("electron");
const fs = require("node:fs");
const path = require("node:path");
const http = require("node:http");
const assert = require("node:assert/strict");
const { WebSocketServer } = require("ws");
const root = path.resolve(__dirname, "../.."),
  build = path.join(root, "build");
process.env.DORA_TEST_HOME = path.join(build, "native-profile");
process.env.DORA_TEST_RESOURCES = path.join(build, "windows-native-resources");
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(fn) {
  for (let i = 0; i < 200; i++) {
    const value = await fn();
    if (value) return value;
    await wait(50);
  }
  throw new Error("Native acceptance timed out");
}
const received = [];
let active = false;
const service = http.createServer((req, res) => {
  if (req.url === "/login") {
    res.setHeader("content-type", "text/html");
    res.end("<!doctype html><title>Isolated login fixture</title>本地隔离验收");
    return;
  }
  if (req.headers.authorization !== "Bearer isolated-fixture") {
    res.writeHead(401);
    res.end("{}");
    return;
  }
  res.setHeader("content-type", "application/json");
  if (req.url === "/api/client-updates/status")
    res.end(
      JSON.stringify({
        supported: true,
        available: true,
        current_version: "0.10.1",
        version: "0.11.0",
        notes: "隔离更新界面验收，不是实际发布。",
        busy: false,
        job: null,
        revision: 1,
        last_check: 1795672000,
        error_code: null,
      }),
    );
  else if (req.url === "/api/auth/me")
    res.end(
      '{"id":711,"username":"isolated-fixture","display_name":"Windows隔离验收"}',
    );
  else if (req.url === "/api/companion/access")
    res.end('{"allowed":true,"supported":true}');
  else if (req.url === "/api/companion/agents")
    res.end(
      '[{"agent_id":"owned","name":"售后质量专家","user_id":711,"is_running":true}]',
    );
  else if (req.url === "/api/agents/owned")
    res.end('{"kind":"personal","mcp_servers":["aftersales_quality"]}');
  else if (req.url === "/api/connector-instances")
    res.end(
      '[{"mcp_server_name":"aftersales_quality","display_name":"售后质量","usable":true}]',
    );
  else if (req.url.includes("/history"))
    res.end(JSON.stringify({ messages: [], turn_active: active }));
  else if (req.url === "/api/teams" || req.url === "/api/knowledge-bases")
    res.end("[]");
  else {
    res.writeHead(404);
    res.end("{}");
  }
});
const sockets = new WebSocketServer({ server: service });
sockets.on("connection", (socket) =>
  socket.on("message", (bytes) => {
    const value = JSON.parse(bytes);
    received.push(value);
    if (value.type === "user_turn") {
      active = true;
      const emit = (v) =>
        socket.send(
          JSON.stringify({
            thread_id: value.thread_id || "fixture-thread",
            ...v,
          }),
        );
      emit({ type: "turn.started", turn_id: "fixture-turn" });
      emit({ type: "token", content: "Windows 原生窗口隔离回答。" });
    }
    if (value.type === "cancel") {
      active = false;
      socket.send(JSON.stringify({ thread_id: value.thread_id, type: "done" }));
      socket.send(
        JSON.stringify({
          thread_id: value.thread_id,
          type: "turn.ended",
          turn_id: "fixture-turn",
        }),
      );
    }
  }),
);
(async () => {
  await new Promise((resolve) => service.listen(0, "127.0.0.1", resolve));
  const base = "http://127.0.0.1:" + service.address().port;
  const { Engine } = require("../engine.cjs");
  Engine.prototype.boot = async () => base;
  await app.whenReady();
  fs.mkdirSync(process.env.DORA_TEST_RESOURCES, { recursive: true });
  fs.cpSync(
    path.join(root, "dist/web"),
    path.join(process.env.DORA_TEST_RESOURCES, "web"),
    { recursive: true },
  );
  // A one-colour original fixture, unrelated to internal pet artwork.
  const { crc32, deflateSync } = require("node:zlib");
  const chunk = (kind, data) => {
    const name = Buffer.from(kind),
      size = Buffer.alloc(4),
      crc = Buffer.alloc(4);
    size.writeUInt32BE(data.length);
    crc.writeUInt32BE(crc32(Buffer.concat([name, data])));
    return Buffer.concat([size, name, data, crc]);
  };
  const header = Buffer.alloc(13);
  header.writeUInt32BE(32, 0);
  header.writeUInt32BE(32, 4);
  header[8] = 8;
  header[9] = 6;
  const pixels = Buffer.alloc(32 * 129);
  for (let y = 0; y < 32; y++)
    for (let x = 0; x < 32; x++) {
      const n = y * 129 + 1 + x * 4;
      pixels[n] = 22;
      pixels[n + 1] = 138;
      pixels[n + 2] = 194;
      pixels[n + 3] = 255;
    }
  const png = nativeImage.createFromBuffer(
    Buffer.concat([
      Buffer.from("89504e470d0a1a0a", "hex"),
      chunk("IHDR", header),
      chunk("IDAT", deflateSync(pixels)),
      chunk("IEND", Buffer.alloc(0)),
    ]),
  );
  assert.equal(png.isEmpty(), false);
  fs.writeFileSync(
    path.join(process.env.DORA_TEST_RESOURCES, "tray.png"),
    png.toPNG(),
  );
  fs.copyFileSync(
    path.join(build, "kurocat-windows/Release/DoraKuroCat.exe"),
    path.join(process.env.DORA_TEST_RESOURCES, "DoraKuroCat.exe"),
  );
  require("../main.cjs");
  const chat = await until(() =>
    BrowserWindow.getAllWindows().find((w) => w.getTitle() === "哆啦"),
  );
  await until(
    () =>
      chat.webContents.getURL().endsWith("index.html") &&
      !chat.webContents.isLoading(),
  );
  await wait(300);
  const call = (op, args = {}) =>
    chat.webContents.executeJavaScript(
      `window.companionNative.invoke(${JSON.stringify(op)},${JSON.stringify(
        args,
      )})`,
    );
  await until(async () => (await call("status")).backendRunning);
  await call("login");
  const login = await until(() =>
    BrowserWindow.getAllWindows().find(
      (w) => w.getTitle() === "Isolated login fixture",
    ),
  );
  await login.webContents.executeJavaScript(
    "localStorage.setItem('auth_token','isolated-fixture')",
  );
  await until(async () => (await call("status")).authenticated);
  await until(async () =>
    chat.webContents.executeJavaScript("!!document.querySelector('textarea')"),
  );
  const pet = BrowserWindow.getAllWindows().find((w) => w !== chat);
  await until(() =>
    chat.webContents.executeJavaScript(
      "[...document.querySelectorAll('button')].some(b=>b.textContent==='下载更新')",
    ),
  );
  fs.writeFileSync(
    path.join(build, "windows-native-update.png"),
    (await chat.webContents.capturePage()).toPNG(),
  );
  assert.ok(pet);
  await until(
    async () =>
      (
        await pet.webContents.executeJavaScript(
          "window.companionNative.invoke('petModel')",
        )
      ).ready,
  );
  const cat = await pet.webContents.executeJavaScript(
    "window.companionNative.invoke('petModel')",
  );
  assert.equal(cat.renderer, "kurocat");
  assert.equal(cat.ready.rawInput, true);
  assert.equal(cat.ready.keyboardHook, true);
  assert.deepEqual(await call("petPreferences"), { edgeHiding: false });
  await until(async () =>
    pet.webContents.executeJavaScript(
      "(()=>{const c=document.querySelector('canvas');return c.width>0&&[...c.getContext('2d').getImageData(0,0,c.width,c.height).data].some((v,i)=>i%4===3&&v>20)})()",
    ),
  );
  fs.writeFileSync(
    path.join(build, "windows-native-kurocat.png"),
    (await pet.webContents.capturePage()).toPNG(),
  );
  const togglePet = async (label) => {
    const original = Menu.buildFromTemplate;
    let template;
    Menu.buildFromTemplate = (items) => {
      template = items;
      return { popup() {} };
    };
    try {
      await pet.webContents.executeJavaScript(
        "window.companionNative.invoke('petMenu')",
      );
    } finally {
      Menu.buildFromTemplate = original;
    }
    template.find((item) => item.label === label).click();
  };
  await togglePet("隐藏哆啦");
  await call("status");
  await wait(250);
  assert.equal(pet.isVisible(), false);
  assert.equal(
    (
      await pet.webContents.executeJavaScript(
        "window.companionNative.invoke('petModel')",
      )
    ).ready,
    null,
  );
  await togglePet("显示哆啦");
  await until(() => pet.isVisible());
  assert.equal(pet.isAlwaysOnTop(), true);
  assert.equal(chat.isAlwaysOnTop(), true);
  assert.equal(
    await chat.webContents.executeJavaScript("window.require"),
    undefined,
  );
  assert.equal(
    await chat.webContents.executeJavaScript("window.companionNative.platform"),
    process.platform,
  );
  await assert.rejects(
    pet.webContents.executeJavaScript(
      "window.companionNative.invoke('api',{path:'/api/auth/me'})",
    ),
  );
  await chat.webContents.executeJavaScript(
    `(()=>{const input=document.querySelector('textarea');Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(input,'原生隔离测试');input.dispatchEvent(new Event('input',{bubbles:true}));})()`,
  );
  await wait(100);
  await chat.webContents.executeJavaScript(
    `document.querySelector('button[aria-label="发送消息"]').click()`,
  );
  await until(() => received.some((v) => v.type === "user_turn"));
  assert.deepEqual(received.find((v) => v.type === "user_turn").mcp_servers, [
    "aftersales_quality",
  ]);
  await until(async () =>
    chat.webContents.executeJavaScript(
      `!!document.querySelector('button[aria-label="停止回答"]')`,
    ),
  );
  await chat.webContents.executeJavaScript(
    `document.querySelector('button[aria-label="停止回答"]').click()`,
  );
  await until(() => received.some((v) => v.type === "cancel"));
  chat.setSize(350, 510);
  await wait(120);
  const overflow = await chat.webContents.executeJavaScript(
    "document.documentElement.scrollWidth>innerWidth",
  );
  assert.equal(overflow, false);
  fs.writeFileSync(
    path.join(build, "windows-native-small.png"),
    (await chat.webContents.capturePage()).toPNG(),
  );
  await call("hideChat");
  assert.equal(chat.isVisible(), false);
  await pet.webContents.executeJavaScript(
    "window.companionNative.invoke('showChat')",
  );
  assert.equal(chat.isVisible(), true);
  await call("logout");
  assert.equal((await call("status")).authenticated, false);
  assert.equal(pet.isVisible(), false);
  const report = {
    native_windows: true,
    transparent_pet: true,
    renderer: "chanke17/KuroCat native Windows",
    native_input_registered: true,
    default_no_edge_snapping: true,
    always_on_top: true,
    isolated_login_roundtrip: true,
    fresh_mcp_binding: true,
    stop_answer: true,
    small_window_no_horizontal_overflow: true,
    close_hides_chat: true,
    logout_hides_pet: true,
    explicit_hide_survives_status_refresh: true,
    enterprise_update_notice: true,
    real_employee_sso_tested: false,
  };
  fs.writeFileSync(
    path.join(build, "windows-native-check.json"),
    JSON.stringify(report, null, 2),
  );
  console.log(JSON.stringify(report));
  app.quit();
})()
  .catch((error) => {
    console.error(error);
    fs.mkdirSync(build, { recursive: true });
    fs.writeFileSync(
      path.join(build, "windows-native-error.json"),
      JSON.stringify({ error: error.stack }),
    );
    app.exit(1);
  })
  .finally(() => {
    for (const s of sockets.clients) s.terminate();
    sockets.close();
    service.close();
  });
