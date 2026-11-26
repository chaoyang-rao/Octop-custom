"use strict";
const { EventEmitter } = require("node:events");
const { spawn } = require("node:child_process");
const MAX_SIDE = 1024,
  MAX_PACKET = MAX_SIDE * MAX_SIDE * 4 + 9;
const MOTIONS = new Set([
  "petInteraction",
  "footEasterEgg",
  "tailEasterEgg",
  "keyboardMarquee",
  "enableAnger",
  "enableDragAnimation",
]);
class FrameDecoder {
  constructor(frame, event) {
    this.frame = frame;
    this.event = event;
    this.header = Buffer.alloc(4);
    this.headerOffset = 0;
    this.body = null;
    this.bodyOffset = 0;
  }
  push(chunk) {
    let offset = 0;
    while (offset < chunk.length) {
      if (!this.body) {
        const count = Math.min(4 - this.headerOffset, chunk.length - offset);
        chunk.copy(this.header, this.headerOffset, offset, offset + count);
        offset += count;
        this.headerOffset += count;
        if (this.headerOffset < 4) continue;
        const size = this.header.readUInt32LE(0);
        if (size < 2 || size > MAX_PACKET)
          throw new Error("小猫渲染数据长度无效。");
        this.body = Buffer.allocUnsafe(size);
        this.bodyOffset = 0;
        this.headerOffset = 0;
      }
      const count = Math.min(
        this.body.length - this.bodyOffset,
        chunk.length - offset,
      );
      chunk.copy(this.body, this.bodyOffset, offset, offset + count);
      offset += count;
      this.bodyOffset += count;
      if (this.bodyOffset !== this.body.length) continue;
      const packet = this.body;
      this.body = null;
      if (packet[0] === 1) {
        if (packet.length < 9) throw new Error("小猫图像数据无效。");
        const width = packet.readUInt32LE(1),
          height = packet.readUInt32LE(5);
        if (
          !width ||
          !height ||
          width > MAX_SIDE ||
          height > MAX_SIDE ||
          packet.length !== 9 + width * height * 4
        )
          throw new Error("小猫图像尺寸无效。");
        this.frame({ width, height, rgba: packet.subarray(9) });
      } else if (packet[0] === 2) {
        if (packet.length > 65536) throw new Error("小猫状态数据过大。");
        const value = JSON.parse(packet.subarray(1).toString("utf8"));
        if (["ready", "stats"].includes(value.type)) this.event(value);
      } else throw new Error("小猫渲染协议无效。");
    }
  }
}
class NativePet extends EventEmitter {
  constructor(binary, launch = spawn) {
    super();
    this.binary = binary;
    this.launch = launch;
    this.child = null;
    this.ready = null;
    this.statistics = {};
    this.lastFrame = "";
  }
  start() {
    if (this.child) return this.starting;
    const child = this.launch(this.binary, [], {
      windowsHide: true,
      stdio: ["pipe", "pipe", "pipe"],
    });
    this.child = child;
    this.starting = new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.cancelStart = null;
        this.stop();
        reject(new Error("小黑猫渲染器启动超时。"));
      }, 10000);
      this.cancelStart = () => {
        clearTimeout(timer);
        reject(new Error("小黑猫渲染已取消。"));
      };
      const decoder = new FrameDecoder(
        (frame) => {
          if (this.child === child) this.emit("frame", frame);
        },
        (value) => {
          if (this.child !== child) return;
          if (value.type === "ready") {
            this.ready = value;
            clearTimeout(timer);
            this.cancelStart = null;
            resolve(value);
          }
          if (value.type === "stats") this.statistics = value;
        },
      );
      child.stdout.on("data", (bytes) => {
        if (this.child !== child) return;
        try {
          decoder.push(bytes);
        } catch (e) {
          this.stop();
          clearTimeout(timer);
          reject(e);
          this.emit("failure", e);
        }
      });
      child.stderr.on("data", () => {});
      child.stdin.on("error", () => {});
      child.once("error", () => {
        clearTimeout(timer);
        if (this.child === child) this.child = null;
        reject(new Error("小黑猫渲染器无法启动。"));
      });
      child.once("exit", () => {
        clearTimeout(timer);
        if (this.child !== child) return;
        this.child = null;
        this.ready = null;
        const e = new Error("小黑猫渲染器已停止。");
        reject(e);
        this.emit("failure", e);
      });
    });
    return this.starting;
  }
  command(line) {
    if (this.child?.stdin.writable) this.child.stdin.write(line + "\n");
  }
  place(rect, scale = 1) {
    if (
      ![rect.x, rect.y, rect.width, rect.height, scale].every(Number.isFinite)
    )
      throw new Error("小猫位置无效。");
    const side = (n) => Math.max(32, Math.min(MAX_SIDE, Math.round(n)));
    const command = `frame ${Math.round(rect.x)} ${Math.round(
      rect.y,
    )} ${Math.round(rect.width)} ${Math.round(rect.height)} ${side(
      rect.width,
    )} ${side(rect.height)} ${scale}`;
    if (command !== this.lastFrame) {
      this.lastFrame = command;
      this.command(command);
    }
  }
  pause(value) {
    this.command(`pause ${value ? 1 : 0}`);
  }
  drag(value, dx = 0, dy = 0) {
    if ([dx, dy].every(Number.isFinite))
      this.command(`drag ${value ? 1 : 0} ${dx} ${dy}`);
  }
  hover(x, y) {
    if ([x, y].every(Number.isFinite)) this.command(`hover ${x} ${y}`);
  }
  motion(name, enabled) {
    if (!MOTIONS.has(name)) throw new Error("小猫动作设置无效。");
    this.command(`motion ${name} ${enabled ? 1 : 0}`);
  }
  state(value) {
    if (
      ![
        "idle",
        "working",
        "thinking",
        "listening",
        "speaking",
        "success",
        "error",
        "sleep",
        "walking",
      ].includes(value)
    )
      throw new Error("小猫状态无效。");
    this.command(`state ${value}`);
  }
  stop() {
    const child = this.child;
    this.child = null;
    this.ready = null;
    this.lastFrame = "";
    this.cancelStart?.();
    this.cancelStart = null;
    if (!child) return;
    if (child.stdin.writable) child.stdin.end("quit\n");
    const timer = setTimeout(() => child.kill(), 1000);
    timer.unref();
    child.once("exit", () => clearTimeout(timer));
  }
}
module.exports = {
  FrameDecoder,
  NativePet,
  MOTIONS,
  createNativePet: (binary) => new NativePet(binary),
};
