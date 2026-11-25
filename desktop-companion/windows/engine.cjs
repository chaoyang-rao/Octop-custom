"use strict";
const fs = require("node:fs/promises");
const path = require("node:path");
const net = require("node:net");
const http = require("node:http");
const { spawn } = require("node:child_process");
const { randomUUID } = require("node:crypto");
const { extract, digest } = require("./archive.cjs");
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
function portAvailable(preferred) {
  return new Promise((resolve, reject) => {
    const s = net.createServer();
    s.once("error", reject);
    s.listen(preferred, "127.0.0.1", () => {
      const p = s.address().port;
      s.close(() => resolve(p));
    });
  });
}
function health(base) {
  return new Promise((resolve) => {
    const r = http.get(
      base + "/api/health/companion",
      { agent: false },
      (response) => {
        let body = "";
        response.on("data", (c) => {
          body += c;
          if (body.length > 4096) r.destroy();
        });
        response.on("end", () => {
          try {
            resolve(JSON.parse(body));
          } catch {
            resolve(null);
          }
        });
      },
    );
    r.setTimeout(700, () => r.destroy());
    r.on("error", () => resolve(null));
  });
}
class Engine {
  constructor(resources, home, log) {
    this.resources = resources;
    this.home = home;
    this.log = log;
    this.child = null;
    this.stopping = false;
  }
  async start(progress = () => {}) {
    if (this.starting) return this.starting;
    this.starting = this.boot(progress).catch((e) => {
      this.starting = null;
      throw e;
    });
    return this.starting;
  }
  async boot(progress) {
    const manifest = JSON.parse(
      await fs.readFile(
        path.join(this.resources, "engine", "manifest.json"),
        "utf8",
      ),
    );
    const meta = manifest.architectures["windows-amd64"];
    if (
      !meta ||
      !/^[a-f0-9]{64}$/.test(meta.sha256) ||
      !/^[A-Za-z0-9._-]+\.zip$/.test(meta.file) ||
      meta.root !== "Octop-windows-amd64" ||
      manifest.authority !== "https://120.79.0.171:18443"
    )
      throw new Error("问答引擎发布信息无效。");
    await fs.mkdir(this.home, { recursive: true });
    const cache = path.join(this.home, "Engine", meta.sha256.slice(0, 16));
    try {
      await fs.access(path.join(cache, ".ready"));
    } catch {
      progress("首次启动正在准备问答引擎…");
      const archive = path.join(this.resources, "engine", meta.file);
      if ((await digest(archive)) !== meta.sha256)
        throw new Error("问答引擎校验失败，请重新下载安装包。");
      const stage = cache + "." + randomUUID();
      try {
        await extract(archive, stage, { root: meta.root });
        await fs.writeFile(path.join(stage, ".ready"), meta.sha256);
        await fs.mkdir(path.dirname(cache), { recursive: true });
        await fs.rename(stage, cache);
      } finally {
        await fs.rm(stage, { recursive: true, force: true });
      }
    }
    const runtime = path.join(cache, meta.root),
      python = path.join(runtime, "runtime", "python.exe");
    await fs.access(python);
    let saved = 18588;
    try {
      saved = Number(await fs.readFile(path.join(this.home, "port"), "utf8"));
    } catch {}
    if (!Number.isInteger(saved) || saved < 1024 || saved > 65535)
      saved = 18588;
    let port;
    for (let attempt = 0; attempt < 12; attempt++) {
      try {
        port = await portAvailable(attempt < 10 ? saved : 0);
        break;
      } catch {
        await delay(150);
      }
    }
    if (!port) throw new Error("无法启动桌宠专属问答端口。");
    this.origin = "http://127.0.0.1:" + port;
    this.instance = randomUUID();
    const env = Object.fromEntries(
      Object.entries(process.env).filter(
        ([k]) => !/^(OCTOP_|PYTHON|DYLD_|VIRTUAL_ENV)/i.test(k),
      ),
    );
    Object.assign(env, {
      OCTOP_HOME: path.join(this.home, "Data"),
      OCTOP_GREEN_PACKAGES: path.join(runtime, "packages"),
      OCTOP_CUSTOM_BUILD: "1",
      OCTOP_COMPANION_MODE: "1",
      OCTOP_COMPANION_INSTANCE: this.instance,
      OCTOP_ENTERPRISE_AUTHORITY_URL: manifest.authority,
      PYTHONNOUSERSITE: "1",
      PYTHONDONTWRITEBYTECODE: "1",
      PYTHONUTF8: "1",
    });
    await fs.mkdir(path.join(this.home, "Data"), { recursive: true });
    progress("正在启动问答引擎…");
    this.child = spawn(
      python,
      [
        path.join(this.resources, "engine_entry.py"),
        runtime,
        "run",
        "--host",
        "127.0.0.1",
        "--port",
        String(port),
      ],
      {
        cwd: path.join(this.home, "Data"),
        env,
        windowsHide: true,
        stdio: ["pipe", "pipe", "pipe"],
      },
    );
    let failure;
    this.child.once("error", (e) => {
      failure = e;
    });
    this.child.once("exit", (code) => {
      failure = new Error("问答引擎已退出（" + code + "），请查看运行日志。");
      this.child = null;
    });
    for (const stream of [this.child.stdout, this.child.stderr])
      stream.on("data", (c) => this.log(c));
    for (let n = 0; n < 240; n++) {
      if (failure) throw failure;
      if (this.stopping) throw new Error("程序正在退出。");
      const h = await health(this.origin);
      if (h?.companion === true && h.instance === this.instance) {
        await fs.writeFile(path.join(this.home, "port"), String(port));
        progress("");
        return this.origin;
      }
      await delay(400);
    }
    this.stop();
    throw new Error("问答引擎启动超时，请打开运行日志。");
  }
  stop() {
    this.stopping = true;
    const child = this.child;
    if (!child) return;
    child.stdin.end();
    const timer = setTimeout(() => child.kill(), 3000);
    timer.unref();
  }
}
module.exports = { Engine, health };
