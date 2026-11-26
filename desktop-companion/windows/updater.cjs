"use strict";
const fs = require("node:fs/promises");
const path = require("node:path");
const { spawn, execFile } = require("node:child_process");
const { promisify } = require("node:util");
const run = promisify(execFile);
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const validId = (value) =>
  typeof value === "string" && /^[a-f0-9]{32}$/.test(value);
const terminal = new Set(["accepted", "rolled_back", "cancelled", "failed"]);
class CompanionUpdater {
  constructor(resources, home, appRoot, execute = run) {
    this.resources = resources;
    this.home = path.join(home, "Data");
    this.appRoot = path.resolve(appRoot);
    this.helper = path.join(resources, "client-updater.exe");
    this.execute = execute;
    this.installing = false;
  }
  directory(id) {
    if (!validId(id)) throw new Error("更新作业编号无效。");
    return path.join(this.home, "client-updates", "jobs", id);
  }
  async read(id) {
    const directory = this.directory(id);
    for (const item of [
      path.dirname(path.dirname(directory)),
      path.dirname(directory),
      directory,
    ]) {
      if ((await fs.lstat(item)).isSymbolicLink())
        throw new Error("更新目录无效。");
    }
    const file = path.join(directory, "job.json"),
      info = await fs.lstat(file);
    if (!info.isFile() || info.size > 1_000_000)
      throw new Error("更新记录无效。");
    const job = JSON.parse(await fs.readFile(file, "utf8"));
    if (
      job.id !== id ||
      job.product !== "octop-companion" ||
      path.resolve(job.app_root) !== this.appRoot ||
      path.resolve(job.data_root) !== path.resolve(this.home)
    )
      throw new Error("更新不属于当前桌宠。");
    return job;
  }
  async write(job) {
    const file = path.join(this.directory(job.id), "job.json");
    await fs.writeFile(file + ".native-writing", JSON.stringify(job), {
      mode: 0o600,
    });
    await fs.rename(file + ".native-writing", file);
  }
  async validate(id, mode) {
    try {
      await this.execute(
        this.helper,
        [
          "--home",
          this.home,
          "--job",
          id,
          "--product",
          "octop-companion",
          mode,
        ],
        { windowsHide: true, timeout: 15000 },
      );
    } catch {
      throw new Error("桌宠更新校验未通过，请重新检查更新。");
    }
  }
  async start(id, backendPID) {
    if (this.installing) throw new Error("桌宠正在更新。");
    const job = await this.read(id);
    await this.validate(id, "--validate");
    job.old_pid = process.pid;
    job.old_backend_pid = backendPID;
    await this.write(job);
    const helper = path.join(this.directory(id), "Dora-updater.exe");
    await fs.copyFile(this.helper, helper);
    const child = spawn(
      helper,
      ["--home", this.home, "--job", id, "--product", "octop-companion"],
      { windowsHide: true, detached: true, stdio: "ignore" },
    );
    await new Promise((resolve, reject) => {
      child.once("spawn", resolve);
      child.once("error", reject);
    });
    child.unref();
    try {
      await fs.writeFile(
        path.join(this.home, "client-updates", "active.json"),
        JSON.stringify({ job_id: id, helper_pid: child.pid }),
        { mode: 0o600 },
      );
    } catch (error) {
      child.kill();
      throw error;
    }
    this.installing = true;
  }
  async monitor(id, progress) {
    for (;;) {
      const job = await this.read(id);
      progress(job.phase);
      if (job.phase === "ready_to_swap" || terminal.has(job.phase))
        return job.phase;
      await wait(250);
    }
  }
  async initialize(engine, args) {
    const index = args.indexOf("--managed-client-update"),
      id = index >= 0 ? args[index + 1] : null;
    if (index >= 0) {
      const job = await this.read(id);
      if (["accepted", "rolled_back", "cancelled"].includes(job.phase))
        return true;
      await this.validate(id, "--candidate");
      job.candidate_pid = process.pid;
      await this.write(job);
      engine.pendingUpdateId = id;
      engine.onSpawn = async (pid) => {
        job.backend_pid = pid;
        await this.write(job);
      };
      const origin = await engine.start();
      job.backend_pid = engine.child.pid;
      job.candidate_base = origin;
      job.phase = "candidate_ready";
      await this.write(job);
      for (let attempt = 0; attempt < 960; attempt++) {
        const current = await this.read(id);
        if (current.phase === "accepted") {
          engine.pendingUpdateId = null;
          engine.onSpawn = null;
          return true;
        }
        if (["failed", "rolling_back", "rolled_back"].includes(current.phase))
          throw new Error("桌宠更新未通过启动验证。");
        await wait(250);
      }
      throw new Error("桌宠更新验证超时。");
    }
    let active;
    try {
      active = JSON.parse(
        await fs.readFile(
          path.join(this.home, "client-updates", "active.json"),
          "utf8",
        ),
      );
    } catch (error) {
      if (error.code === "ENOENT") return true;
      throw error;
    }
    const job = await this.read(active.job_id);
    if (
      terminal.has(job.phase) &&
      job.error_code !== "CLIENT_UPDATE_RECOVERY_REQUIRED"
    )
      return true;
    if (Number.isInteger(active.helper_pid) && active.helper_pid > 0) {
      try {
        process.kill(active.helper_pid, 0);
        return false;
      } catch {}
    }
    if (!job.backup_ready) return true;
    const child = spawn(
      this.helper,
      [
        "--home",
        this.home,
        "--job",
        job.id,
        "--product",
        "octop-companion",
        "--recover",
        "--wait-pid",
        String(process.pid),
      ],
      { windowsHide: true, detached: true, stdio: "ignore" },
    );
    child.on("error", () => {});
    child.unref();
    return false;
  }
}
module.exports = { CompanionUpdater, validId };
