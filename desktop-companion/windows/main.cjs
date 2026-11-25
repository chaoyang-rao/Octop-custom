"use strict";
const {
  app,
  BrowserWindow,
  ipcMain,
  Menu,
  Tray,
  nativeImage,
  shell,
  dialog,
  clipboard,
  globalShortcut,
  screen,
  session,
} = require("electron");
const fs = require("node:fs");
const fsp = fs.promises;
const path = require("node:path");
const { spawn } = require("node:child_process");
const { pathToFileURL } = require("node:url");
const readline = require("node:readline");
const { Engine } = require("./engine.cjs");
const { BackendClient } = require("./backend.cjs");
const { ensureArtwork, readModel } = require("./artwork.cjs");
const policy = require("./security.cjs");
const geometry = require("./geometry.cjs");

const home =
  !app.isPackaged && process.env.DORA_TEST_HOME
    ? path.resolve(process.env.DORA_TEST_HOME)
    : process.platform === "win32"
    ? path.join(app.getPath("appData"), "..", "Local", "OctopCompanion")
    : path.join(app.getPath("userData"), "WindowsAcceptance");
app.setPath("userData", path.join(home, "WebProfile"));
const resources = app.isPackaged
  ? process.resourcesPath
  : path.resolve(
      process.env.DORA_TEST_RESOURCES ||
        path.join(__dirname, "../build/windows-resources"),
    );
const chatFile = path.join(resources, "web", "index.html"),
  petFile = path.join(__dirname, "pet.html");
let chat,
  pet,
  login,
  sizeWindow,
  tray,
  client,
  engine,
  artwork,
  model,
  quitting = false,
  startupError = "",
  progress = "",
  dragging = null,
  dockEdge = null,
  collapsed = false,
  savedFrame,
  collapseAt = 0,
  phaseTimer,
  speech;
let pose = { animation: "idle", phase: "rest", facingLeft: false },
  preferences = { edgeHiding: true, scale: 1, voice: true };
const logDirectory = path.join(home, "Logs");
function log(value) {
  try {
    fs.mkdirSync(logDirectory, { recursive: true });
    const file = path.join(logDirectory, "dora.log");
    if (fs.existsSync(file) && fs.statSync(file).size > 5 * 1024 ** 2)
      fs.renameSync(file, file + ".previous");
    fs.appendFileSync(file, String(value));
  } catch {}
}
function send(window, value) {
  if (window && !window.isDestroyed())
    window.webContents.send("companion-event", value);
}
function event(value) {
  if (value.type === "authExpired") {
    stopSpeech();
    artwork = model = null;
    pet?.hide();
  }
  send(chat, value);
}
function savePreferences() {
  try {
    fs.writeFileSync(
      path.join(home, "preferences.json"),
      JSON.stringify({
        ...preferences,
        petFrame: savedFrame || pet?.getBounds(),
        chatFrame: chat?.getBounds(),
      }),
    );
  } catch (e) {
    log(e.message);
  }
}
function configure(window, document) {
  window.webContents.setWindowOpenHandler(({ url }) => {
    void shell.openExternal(policy.externalUrl(url)).catch(log);
    return { action: "deny" };
  });
  window.webContents.on("will-navigate", (e, url) => {
    if (url !== pathToFileURL(document).href) e.preventDefault();
  });
  window.webContents.on("will-attach-webview", (e) => e.preventDefault());
}
function webPreferences(preload = "preload.cjs") {
  return {
    preload: path.join(__dirname, preload),
    sandbox: true,
    contextIsolation: true,
    nodeIntegration: false,
    webSecurity: true,
    spellcheck: false,
  };
}
function area() {
  return screen.getDisplayMatching(savedFrame || pet.getBounds()).workArea;
}
function publishPose() {
  send(pet, { type: "petState", data: { ...pose, edge: dockEdge, collapsed } });
}
function phase(value) {
  clearTimeout(phaseTimer);
  pose.phase = value;
  publishPose();
  if (value === "takeoff" || value === "landing")
    phaseTimer = setTimeout(
      () => phase(value === "takeoff" ? "flying" : "rest"),
      value === "takeoff" ? 320 : 360,
    );
}
function reveal() {
  if (!collapsed || !savedFrame) return;
  collapsed = false;
  pet.setBounds(savedFrame);
  publishPose();
  collapseAt = Date.now() + 1200;
}
function collapse() {
  if (!dockEdge || collapsed || dragging || !model || !preferences.edgeHiding)
    return;
  savedFrame = pet.getBounds();
  const peek =
    model.manifest.peek[
      ["left", "right"].includes(dockEdge) ? "right" : "bottom"
    ];
  pet.setBounds(
    geometry.peekFrame(
      savedFrame,
      area(),
      dockEdge,
      peek,
      model.manifest.registration,
    ),
  );
  collapsed = true;
  publishPose();
}
function placeInitial() {
  const a = screen.getPrimaryDisplay().workArea,
    side = Math.round(
      158 * geometry.clamp(Number(preferences.scale) || 1, 0.5, 2.5),
    );
  const old = preferences.petFrame || {
    x: a.x + a.width - side - 30,
    y: a.y + a.height - side - 28,
    width: side,
    height: side,
  };
  pet.setBounds(
    geometry.fullFrame(old, side, screen.getDisplayMatching(old).workArea),
  );
  savedFrame = pet.getBounds();
}
function showChat() {
  if (!chat) return;
  if (chat.isMinimized()) chat.restore();
  if (!chat.isVisible()) {
    if (!preferences.chatFrame && pet) {
      const p = savedFrame || pet.getBounds(),
        a = screen.getDisplayMatching(p).workArea,
        s = chat.getBounds();
      chat.setPosition(
        Math.round(
          geometry.clamp(
            p.x > a.x + a.width / 2 ? p.x - s.width - 16 : p.x + p.width + 16,
            a.x,
            a.x + a.width - s.width,
          ),
        ),
        Math.round(
          geometry.clamp(
            p.y + p.height - s.height,
            a.y,
            a.y + a.height - s.height,
          ),
        ),
      );
    }
    chat.show();
  }
  chat.focus();
}
function movePet(edge) {
  reveal();
  const a = area(),
    f = pet.getBounds();
  f.x = edge === "left" ? a.x : a.x + a.width - f.width;
  f.y = a.y + a.height - f.height;
  pet.setBounds(f);
  savedFrame = f;
  dockEdge = edge;
  collapseAt = Date.now() + 1000;
  savePreferences();
}
function petMenu() {
  Menu.buildFromTemplate([
    { label: "打开聊天", accelerator: "Control+Alt+Space", click: showChat },
    {
      label: pet.isVisible() ? "隐藏哆啦" : "显示哆啦",
      click: () => (pet.isVisible() ? pet.hide() : pet.showInactive()),
    },
    { label: "靠左停放", click: () => movePet("left") },
    { label: "靠右停放", click: () => movePet("right") },
    { label: "连续调整大小…", click: showSize },
    {
      label: "桌宠大小",
      submenu: [50, 75, 100, 125, 150, 200, 250].map((percent) => ({
        label: percent + "%",
        type: "radio",
        checked: Math.round(preferences.scale * 100) === percent,
        click: () => resize(percent / 100),
      })),
    },
    {
      label: "边缘躲藏",
      type: "checkbox",
      checked: preferences.edgeHiding,
      click: (item) => {
        preferences.edgeHiding = item.checked;
        reveal();
        savePreferences();
      },
    },
    {
      label: "自动朗读",
      type: "checkbox",
      checked: preferences.voice,
      click: (item) => {
        preferences.voice = item.checked;
        event({ type: "toggleVoice" });
        savePreferences();
      },
    },
    { type: "separator" },
    {
      label: "资源与模型",
      click: () => void openLogin("/companion/manage?section=models"),
    },
    { label: "刷新专家", click: () => event({ type: "refreshResources" }) },
    {
      label: "使用说明",
      click: () => void shell.openPath(path.join(resources, "使用说明.txt")),
    },
    { label: "运行日志", click: () => void shell.openPath(logDirectory) },
    {
      label: client?.token ? "退出登录" : "企业登录",
      click: () => (client?.token ? void logout() : void openLogin()),
    },
    { type: "separator" },
    { label: "退出哆啦", click: () => app.quit() },
  ]).popup();
}
function showSize() {
  if (sizeWindow && !sizeWindow.isDestroyed()) {
    sizeWindow.show();
    sizeWindow.focus();
    return;
  }
  sizeWindow = new BrowserWindow({
    title: "哆啦大小",
    width: 340,
    height: 166,
    resizable: false,
    autoHideMenuBar: true,
    alwaysOnTop: true,
    webPreferences: webPreferences(),
  });
  configure(sizeWindow, path.join(__dirname, "size.html"));
  void sizeWindow.loadFile(path.join(__dirname, "size.html"));
  sizeWindow.once("closed", () => {
    sizeWindow = null;
  });
}
function resize(scale) {
  reveal();
  preferences.scale = geometry.clamp(scale, 0.5, 2.5);
  pet.setBounds(
    geometry.fullFrame(pet.getBounds(), 158 * preferences.scale, area()),
  );
  savedFrame = pet.getBounds();
  dockEdge = null;
  publishPose();
  savePreferences();
}
async function ready() {
  if (startupError) throw new Error(startupError);
  if (!client) throw new Error(progress || "问答引擎正在启动，请稍候。");
  return client;
}
async function loadArtwork() {
  const revision = client.revision;
  try {
    const directory = await ensureArtwork(client, home);
    const value = await readModel(directory);
    if (revision !== client.revision) return;
    artwork = directory;
    model = value;
    publishPose();
    send(pet, { type: "petReload" });
    pet.showInactive();
  } catch (e) {
    if (revision !== client.revision) return;
    event({ type: "notice", text: e.message });
    log(e.message + "\n");
  }
}
let loginPurpose = "";
async function openLogin(relative = "/login") {
  const c = await ready();
  if (login && !login.isDestroyed()) {
    login.show();
    login.focus();
    return;
  }
  loginPurpose = relative;
  login = new BrowserWindow({
    title: "哆啦 · 企业登录",
    width: 920,
    height: 740,
    autoHideMenuBar: true,
    webPreferences: webPreferences("login-preload.cjs"),
  });
  login.webContents.setWindowOpenHandler(({ url }) => {
    void shell.openExternal(policy.externalUrl(url)).catch(log);
    return { action: "deny" };
  });
  login.webContents.on("will-navigate", (e, url) => {
    try {
      if (!["http:", "https:", "about:"].includes(new URL(url).protocol))
        e.preventDefault();
    } catch {
      e.preventDefault();
    }
  });
  login.once("closed", () => {
    login = null;
  });
  await login.loadURL(c.origin + relative);
}
async function logout() {
  client?.logout();
  stopSpeech();
  artwork = model = null;
  pet.hide();
  send(pet, { type: "petReload" });
  if (login && !login.isDestroyed()) login.close();
  await session.defaultSession.clearStorageData({
    storages: ["localstorage"],
    origin: client?.origin,
  });
  event({ type: "authChanged" });
}
function loginSender(e) {
  return (
    login &&
    e.sender === login.webContents &&
    e.senderFrame === login.webContents.mainFrame &&
    client &&
    policy.sameOrigin(e.senderFrame.url, client.origin)
  );
}
function speechCommand(op, text = "") {
  if (!speech) {
    if (process.platform !== "win32")
      throw new Error("语音功能需要 Windows 语音服务。");
    speech = spawn(path.join(resources, "DoraSpeech.exe"), [], {
      windowsHide: true,
      stdio: ["pipe", "pipe", "pipe"],
    });
    const current = speech;
    readline.createInterface({ input: current.stdout }).on("line", (line) => {
      if (speech !== current) return;
      try {
        const value = JSON.parse(line);
        if (value.type === "recognized")
          event({ type: "voice", text: value.text });
        else if (value.type === "listeningEnded")
          event({ type: "voice", data: "stopped" });
        else if (value.type === "speechError")
          event({ type: "voice", error: value.text });
        else if (value.type === "speechEnded") {
          event({ type: "speech", data: "stopped" });
          publishPose();
        }
      } catch {}
    });
    current.stderr.on("data", log);
    current.on("error", (e) => {
      if (speech === current) event({ type: "voice", error: e.message });
    });
    current.once("exit", () => {
      if (speech === current) speech = null;
    });
  }
  speech.stdin.write(JSON.stringify({ op, text }) + "\n");
  if (op === "startListening") event({ type: "voice", data: "started" });
  if (op === "speak") {
    event({ type: "speech", data: "started" });
    send(pet, {
      type: "petState",
      data: { ...pose, animation: "speaking", edge: dockEdge, collapsed },
    });
  }
}
function stopSpeech() {
  if (speech) {
    speech.stdin.end();
    speech.kill();
    speech = null;
  }
}
async function imageBytes(source) {
  if (typeof source !== "string") throw new Error("图片链接无效。");
  let bytes, mime;
  if (source.startsWith("/api/")) {
    const r = await (await ready()).request(source);
    if (r.status !== 200) throw new Error("图片加载失败。");
    bytes = r.bytes;
    mime = r.headers["content-type"];
  } else if (/^data:image\/(png|jpeg|webp|gif);base64,/.test(source)) {
    const end = source.indexOf(",");
    bytes = Buffer.from(source.slice(end + 1), "base64");
    mime = source.slice(5, end - 7);
  } else {
    const url = new URL(policy.externalUrl(source));
    if (url.protocol !== "https:") throw new Error("外部图片需要 HTTPS。");
    const response = await fetch(url, {
      redirect: "error",
      signal: AbortSignal.timeout(30000),
    });
    if (!response.ok) throw new Error("图片下载失败。");
    mime = response.headers.get("content-type");
    const chunks = [];
    let size = 0;
    for await (const c of response.body) {
      if ((size += c.length) > 32 * 1024 ** 2) throw new Error("图片过大。");
      chunks.push(c);
    }
    bytes = Buffer.concat(chunks);
  }
  if (
    !/^image\/(png|jpeg|webp|gif)(;|$)/.test(mime || "") ||
    bytes.length > 32 * 1024 ** 2
  )
    throw new Error("图片格式或大小不受支持。");
  return { bytes, mime: mime.split(";")[0] };
}
async function native(op, args) {
  switch (op) {
    case "status": {
      if (!client)
        return {
          authenticated: false,
          origin: "",
          backendRunning: false,
          standalone: true,
          storageScope: "companion-local-v1",
          platform: "win32",
          startupError,
          progress,
        };
      const revision = client.revision;
      let user = null,
        allowed = false;
      if (client.token) {
        try {
          user = await client.user();
          allowed = (await client.data("/api/companion/access")).allowed;
          if (revision === client.revision && !allowed) pet.hide();
        } catch (e) {
          log(e.message);
        }
      }
      if (revision !== client.revision)
        throw new Error("登录状态已变化，请刷新。");
      return {
        authenticated: !!user,
        origin: client.origin,
        user,
        backendRunning: true,
        standalone: true,
        storageScope: "companion-local-v1",
        platform: "win32",
        companionAllowed: allowed,
      };
    }
    case "api": {
      const c = await ready();
      if (args.method && args.method !== "GET")
        throw new Error("仅允许读取这个接口。");
      return c.json(
        args.path === "/api/agents" ? "/api/companion/agents" : args.path,
      );
    }
    case "login":
      await openLogin();
      return true;
    case "logout":
      await logout();
      return true;
    case "startOctop":
    case "openOctop":
      await openLogin(
        args.path === "/knowledge-bases"
          ? "/companion/manage?section=knowledge"
          : "/companion/manage?section=models",
      );
      return true;
    case "setOrigin":
      throw new Error("哆啦自动管理独立的本机问答引擎。");
    case "openLink": {
      const value = args.path || args.url;
      if (typeof value !== "string") throw new Error("链接无效。");
      if (
        value.startsWith("/") &&
        !value.startsWith("//") &&
        !value.includes("\\")
      )
        await openLogin(value);
      else await shell.openExternal(policy.externalUrl(value));
      return true;
    }
    case "chatSend":
      return (await ready()).send(args);
    case "saveTeam":
      return (await ready()).saveTeam(args);
    case "resumeApproval":
      return (await ready()).resume(args);
    case "chatClose":
      if (!policy.BOARDS.has(args.board)) throw new Error("会话无效。");
      client?.close(args.board);
      return true;
    case "upload":
      return (await ready()).upload(args);
    case "copy":
      clipboard.writeText(String(args.text || "").slice(0, 2000000));
      return true;
    case "image": {
      const { bytes, mime } = await imageBytes(args.path);
      return { url: "data:" + mime + ";base64," + bytes.toString("base64") };
    }
    case "saveImage": {
      const { bytes, mime } = await imageBytes(args.source);
      const value = await dialog.showSaveDialog(chat, {
        defaultPath:
          "哆啦图片." + (mime === "image/jpeg" ? "jpg" : mime.split("/")[1]),
        filters: [
          {
            name: "图片",
            extensions: [mime === "image/jpeg" ? "jpg" : mime.split("/")[1]],
          },
        ],
      });
      if (value.canceled || !value.filePath) return false;
      await fsp.writeFile(value.filePath, bytes);
      return true;
    }
    case "startListening":
      if (!(await ready()).token) throw new Error("请先登录。");
      speechCommand(op);
      return true;
    case "stopListening":
    case "stopSpeaking":
      if (speech) speechCommand(op);
      return true;
    case "speak":
      if (!(await ready()).token) throw new Error("请先登录。");
      speechCommand(op, String(args.text || "").slice(0, 20000));
      return true;
    case "voicePreference":
      preferences.voice = !!args.enabled;
      savePreferences();
      return true;
    case "petState":
      if (
        ![
          "idle",
          "walking",
          "listening",
          "thinking",
          "working",
          "speaking",
          "success",
          "error",
          "sleep",
        ].includes(args.state)
      )
        throw new Error("动作无效。");
      pose.animation = args.state;
      publishPose();
      return true;
    case "petPreferences":
      return { edgeHiding: preferences.edgeHiding };
    case "setEdgeHiding":
      preferences.edgeHiding = !!args.enabled;
      reveal();
      savePreferences();
      return true;
    case "petSize":
      showSize();
      return true;
    case "help":
      await shell.openPath(path.join(resources, "使用说明.txt"));
      return true;
    case "hideChat":
      chat.hide();
      return true;
    case "minimizeChat":
      chat.minimize();
      return true;
    default:
      throw new Error("不支持这个操作。");
  }
}
ipcMain.handle("login-context", (e) =>
  loginSender(e) ? { origin: client.origin, token: client.token } : null,
);
ipcMain.handle("login-token", async (e, token) => {
  if (!loginSender(e)) throw new Error("登录来源无效。");
  const current = login,
    purpose = loginPurpose;
  if (token === client.token) {
    if (purpose === "/login" && current && !current.isDestroyed()) {
      current.close();
      showChat();
      void loadArtwork();
    }
    return true;
  }
  await client.acceptToken(token);
  stopSpeech();
  artwork = model = null;
  pet.hide();
  event({ type: "authChanged" });
  if (current && !current.isDestroyed() && purpose === "/login")
    current.close();
  showChat();
  void loadArtwork();
  return true;
});
ipcMain.handle("companion", async (e, op, args = {}) => {
  if (policy.trustedDocument(e.senderFrame, chat?.webContents, chatFile))
    return native(op, args);
  if (
    policy.trustedDocument(
      e.senderFrame,
      sizeWindow?.webContents,
      path.join(__dirname, "size.html"),
    )
  ) {
    if (op === "getScale") return preferences.scale;
    if (op === "setScale" && Number.isFinite(args.scale)) {
      resize(args.scale);
      return true;
    }
    throw new Error("操作无效。");
  }
  if (!policy.trustedDocument(e.senderFrame, pet?.webContents, petFile))
    throw new Error("窗口来源无效。");
  switch (op) {
    case "petModel":
      return model;
    case "showChat":
      showChat();
      return true;
    case "petMenu":
      petMenu();
      return true;
    case "petHit":
      pet.setIgnoreMouseEvents(!args.hit && !dragging, { forward: true });
      if (args.hit) {
        if (collapsed) reveal();
        collapseAt = Date.now() + 1200;
      }
      return true;
    case "petDragStart":
      reveal();
      dockEdge = null;
      dragging = {
        pointer: screen.getCursorScreenPoint(),
        frame: pet.getBounds(),
      };
      pet.setIgnoreMouseEvents(false);
      phase("takeoff");
      return true;
    case "petDragEnd":
      if (!dragging) return true;
      dragging = null;
      phase("landing");
      savedFrame = pet.getBounds();
      dockEdge = geometry.dock(
        savedFrame,
        area(),
        screen.getAllDisplays().map((d) => d.bounds),
      );
      collapseAt = Date.now() + 1000;
      savePreferences();
      return true;
    default:
      throw new Error("不支持这个桌宠操作。");
  }
});
if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on("second-instance", (_event, argv) => {
    if (argv.some((value) => policy.launchAction(value) === "size")) showSize();
    else showChat();
  });
  app.on("before-quit", () => {
    quitting = true;
    savePreferences();
    engine?.stop();
    client?.closeAll();
    stopSpeech();
    globalShortcut.unregisterAll();
  });
  app.on("window-all-closed", () => {});
  void app
    .whenReady()
    .then(async () => {
      await fsp.mkdir(home, { recursive: true });
      try {
        preferences = {
          ...preferences,
          ...JSON.parse(
            await fsp.readFile(path.join(home, "preferences.json"), "utf8"),
          ),
        };
      } catch {}
      session.defaultSession.setPermissionRequestHandler(
        (_wc, _permission, callback) => callback(false),
      );
      session.defaultSession.setPermissionCheckHandler(() => false);
      chat = new BrowserWindow({
        title: "哆啦",
        width: preferences.chatFrame?.width || 456,
        height: preferences.chatFrame?.height || 706,
        minWidth: 350,
        minHeight: 510,
        ...(preferences.chatFrame
          ? { x: preferences.chatFrame.x, y: preferences.chatFrame.y }
          : {}),
        frame: false,
        transparent: true,
        backgroundColor: "#00000000",
        alwaysOnTop: true,
        show: false,
        autoHideMenuBar: true,
        webPreferences: webPreferences(),
      });
      if (process.platform === "win32") {
        try {
          chat.setBackgroundMaterial("acrylic");
        } catch {}
      }
      chat.on("close", (e) => {
        if (!quitting) {
          e.preventDefault();
          chat.hide();
        }
      });
      chat.on("moved", savePreferences);
      chat.on("resized", savePreferences);
      configure(chat, chatFile);
      pet = new BrowserWindow({
        width: 158,
        height: 158,
        frame: false,
        transparent: true,
        backgroundColor: "#00000000",
        alwaysOnTop: true,
        skipTaskbar: true,
        resizable: false,
        focusable: false,
        show: false,
        hasShadow: false,
        webPreferences: webPreferences(),
      });
      pet.setAlwaysOnTop(true, "screen-saver");
      pet.setIgnoreMouseEvents(true, { forward: true });
      configure(pet, petFile);
      placeInitial();
      await pet.loadFile(petFile);
      await chat.loadFile(chatFile);
      showChat();
      const svg =
        '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"><rect x="2" y="3" width="28" height="23" rx="11" fill="#168ac2"/><path d="M9 22 7 29 18 24" fill="#168ac2"/><circle cx="11" cy="14" r="2" fill="white"/><circle cx="21" cy="14" r="2" fill="white"/></svg>';
      // nativeImage decodes PNG reliably on Windows; use a generated original icon.
      const iconPath = path.join(resources, "tray.png");
      tray = new Tray(
        fs.existsSync(iconPath)
          ? iconPath
          : nativeImage.createFromDataURL(
              "data:image/svg+xml;base64," +
                Buffer.from(svg).toString("base64"),
            ),
      );
      tray.setToolTip("哆啦");
      tray.on("click", showChat);
      tray.on("right-click", petMenu);
      globalShortcut.register("Control+Alt+Space", () =>
        chat.isVisible() && chat.isFocused() ? chat.hide() : showChat(),
      );
      if (!process.env.DORA_TEST_HOME && process.defaultApp)
        app.setAsDefaultProtocolClient("octop-companion", process.execPath, [
          path.resolve(__dirname),
        ]);
      else if (!process.env.DORA_TEST_HOME)
        app.setAsDefaultProtocolClient("octop-companion");
      setInterval(() => {
        if (!pet || pet.isDestroyed()) return;
        const pointer = screen.getCursorScreenPoint();
        if (dragging) {
          const x = dragging.frame.x + pointer.x - dragging.pointer.x,
            y = dragging.frame.y + pointer.y - dragging.pointer.y;
          pet.setPosition(Math.round(x), Math.round(y));
          savedFrame = pet.getBounds();
          pose.facingLeft = geometry.facing(
            savedFrame,
            area(),
            pose.facingLeft,
          );
          publishPose();
        } else if (pet.isVisible()) {
          const f = pet.getBounds();
          send(pet, {
            type: "hitTest",
            data: { x: pointer.x - f.x, y: pointer.y - f.y },
          });
          if (Date.now() >= collapseAt) collapse();
        }
      }, 35).unref();
      setInterval(() => client?.ping(), 25000).unref();
      screen.on("display-removed", () => {
        reveal();
        const f = pet.getBounds();
        pet.setBounds(
          geometry.fullFrame(f, f.width, screen.getDisplayMatching(f).workArea),
        );
        savedFrame = pet.getBounds();
      });
      try {
        engine = new Engine(resources, home, log);
        const origin = await engine.start((value) => {
          progress = value;
          event({ type: "engineStatus", text: value });
        });
        client = new BackendClient(origin, event);
        event({ type: "authChanged" });
      } catch (e) {
        startupError = e.message;
        log(e.stack + "\n");
        event({ type: "engineError", error: startupError });
      }
    })
    .catch((e) => {
      log(e.stack);
      dialog.showErrorBox("哆啦启动失败", e.message);
      app.quit();
    });
}
