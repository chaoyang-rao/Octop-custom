"use strict";
const http = require("node:http");
const https = require("node:https");
const { randomUUID } = require("node:crypto");
const { StringDecoder } = require("node:string_decoder");
const WebSocket = require("ws");
const policy = require("./security.cjs");

class BackendClient {
  constructor(base, event = () => {}) {
    this.origin = policy.origin(base);
    this.token = null;
    this.revision = 0;
    this.event = event;
    this.sockets = new Map();
    this.approvals = new Map();
  }
  setOrigin(base) {
    if (this.origin !== policy.origin(base)) {
      this.logout();
      this.origin = policy.origin(base);
    }
  }
  logout() {
    this.revision++;
    this.token = null;
    this.closeAll();
  }
  expire(token, revision) {
    if (this.token === token && this.revision === revision) {
      this.logout();
      this.event({ type: "authExpired" });
      return true;
    }
    return false;
  }
  async request(
    relative,
    {
      method = "GET",
      body,
      contentType,
      authenticated = true,
      token = this.token,
      stream = false,
      signal,
    } = {},
  ) {
    const url = policy.apiPath(relative, this.origin),
      revision = this.revision;
    if (authenticated && !token) throw new Error("请先使用企业飞书登录桌宠。");
    const bytes =
      body === undefined
        ? undefined
        : Buffer.isBuffer(body)
        ? body
        : Buffer.from(JSON.stringify(body));
    return await new Promise((resolve, reject) => {
      const headers = { "Accept-Language": "zh" };
      if (authenticated) headers.Authorization = "Bearer " + token;
      if (bytes) {
        headers["Content-Type"] = contentType || "application/json";
        headers["Content-Length"] = bytes.length;
      }
      // Node's direct loopback transport deliberately ignores machine proxy settings.
      const req = (url.protocol === "https:" ? https : http).request(
        url,
        { method, headers, agent: false, signal },
        (response) => {
          const status = response.statusCode || 0;
          if (status === 401 && authenticated) this.expire(token, revision);
          if (
            status >= 200 &&
            status < 300 &&
            this.token === token &&
            this.revision === revision &&
            response.headers["x-octop-access-token"]
          )
            this.token = String(response.headers["x-octop-access-token"]);
          if (status >= 300 && status < 400) {
            response.resume();
            reject(new Error("本机请求发生了未经允许的重定向。"));
            return;
          }
          if (stream) {
            resolve({ status, headers: response.headers, response });
            return;
          }
          const chunks = [];
          let size = 0;
          response.on("data", (chunk) => {
            size += chunk.length;
            if (size > 40 * 1024 * 1024) {
              response.destroy(new Error("返回内容过大。"));
              return;
            }
            chunks.push(chunk);
          });
          response.on("error", reject);
          response.on("end", () =>
            resolve({
              status,
              headers: response.headers,
              bytes: Buffer.concat(chunks),
            }),
          );
        },
      );
      req.setTimeout(stream ? 3_600_000 : 55_000, () =>
        req.destroy(new Error("连接超时，请重试或查看运行日志。")),
      );
      req.on("error", reject);
      if (bytes) req.write(bytes);
      req.end();
    });
  }
  async json(relative, options) {
    const r = await this.request(relative, options);
    let data = {};
    if (r.bytes.length) {
      try {
        data = JSON.parse(r.bytes.toString("utf8"));
      } catch {
        throw new Error("问答引擎返回了无法识别的数据。");
      }
    }
    return { status: r.status, data };
  }
  async data(relative, options) {
    const r = await this.json(relative, options);
    if (r.status < 200 || r.status >= 300)
      throw new Error(
        r.data?.error?.message || r.data?.detail || `请求未完成（${r.status}）`,
      );
    return r.data;
  }
  async user(token = this.token) {
    const r = await this.json("/api/auth/me", { token });
    if (r.status !== 200 || r.data?.id === undefined)
      throw new Error("登录已过期，请重新登录。");
    return Object.fromEntries(
      ["id", "username", "display_name", "role", "locale"]
        .filter((key) => key in r.data)
        .map((key) => [key, r.data[key]]),
    );
  }
  async acceptToken(token) {
    if (typeof token !== "string" || !token || token.length > 32000)
      throw new Error("登录信息无效。");
    const revision = this.revision,
      base = this.origin,
      user = await this.user(token);
    if (token === this.token) return user;
    if (revision !== this.revision || base !== this.origin)
      throw new Error("登录状态已经变化。");
    this.closeAll();
    this.revision++;
    this.token = token;
    return user;
  }
  async companionIDs() {
    const rows = await this.data("/api/companion/agents");
    if (!Array.isArray(rows)) throw new Error("专家授权暂不可用，请刷新。");
    return new Set(rows.map((r) => r.agent_id));
  }
  async expertMCPs(agent) {
    agent = policy.segment(agent);
    if (!(await this.companionIDs()).has(agent))
      throw new Error("这个专家当前未向桌宠开放，请刷新或核对授权。");
    const row = await this.data(`/api/agents/${agent}`);
    if (
      row.kind === "team" ||
      !Array.isArray(row.mcp_servers) ||
      row.mcp_servers.some((v) => typeof v !== "string")
    )
      throw new Error("专家的MCP配置暂不可用，请刷新。");
    return row.mcp_servers;
  }
  async validateTeam(team) {
    team = policy.segment(team);
    const row = await this.data(`/api/teams/${team}`),
      ids = await this.companionIDs();
    const members = row.member_ids;
    if (
      row.primary_agent_name !== "小通" ||
      !Array.isArray(members) ||
      new Set(members).size < 2 ||
      !members.includes(row.primary_agent_id) ||
      !ids.has(team) ||
      members.some((id) => !ids.has(id))
    )
      throw new Error("团队须由已开放的小通主持，所有成员也须当前可用。");
    const host = await this.data(
      `/api/agents/${policy.segment(row.primary_agent_id)}`,
    );
    if (host.name !== "小通" || host.is_team_primary !== true)
      throw new Error("小通主持配置已变化，请刷新核对。");
  }
  async saveTeam(args) {
    const host = policy.segment(args.hostId),
      ids = await this.companionIDs(),
      primary = await this.data(`/api/agents/${host}`);
    if (
      !ids.has(host) ||
      primary.name !== "小通" ||
      primary.is_team_primary !== true
    )
      throw new Error("请先恢复本人已开放的小通主专家。");
    const members = [
      ...new Set((args.memberIds || []).map((id) => policy.segment(id))),
    ].filter((id) => id !== host);
    if (
      typeof args.name !== "string" ||
      !args.name.trim() ||
      !members.length ||
      members.some((id) => !ids.has(id))
    )
      throw new Error("请填写团队名称并选择至少一位可用专家。");
    const target = args.teamId
      ? `/api/teams/${policy.segment(args.teamId)}`
      : "/api/teams";
    if (args.teamId) {
      const old = await this.data(target);
      if (old.primary_agent_id !== host || old.primary_agent_name !== "小通")
        throw new Error("这个团队的主持人不是当前小通。");
    }
    return await this.data(target, {
      method: args.teamId ? "PATCH" : "POST",
      body: { name: args.name.trim(), member_ids: members },
    });
  }
  close(board) {
    this.approvals.get(board)?.controller.abort();
    this.approvals.delete(board);
    const previous = this.sockets.get(board);
    this.sockets.delete(board);
    previous?.socket.close(1000);
  }
  closeAll() {
    for (const board of new Set([
      ...this.sockets.keys(),
      ...this.approvals.keys(),
    ]))
      this.close(board);
  }
  async socket(command) {
    const old = this.sockets.get(command.board);
    if (
      old?.agent === command.agent &&
      old.context === command.context &&
      old.socket.readyState === WebSocket.OPEN
    )
      return old.socket;
    this.close(command.board);
    if (!this.token) throw new Error("请先登录。");
    const url = policy.apiPath(
      `/api/agents/${command.agent}/chat/ws`,
      this.origin,
    );
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    const token = this.token,
      revision = this.revision;
    const socket = new WebSocket(url, {
      headers: { Authorization: "Bearer " + token },
      followRedirects: false,
      handshakeTimeout: 15000,
      maxPayload: 16 * 1024 * 1024,
      perMessageDeflate: false,
    });
    const entry = { agent: command.agent, context: command.context, socket };
    this.sockets.set(command.board, entry);
    socket.on("message", (data) => {
      if (
        this.sockets.get(command.board) !== entry ||
        revision !== this.revision
      )
        return;
      try {
        this.event({
          type: "chat",
          board: command.board,
          contextKey: command.context,
          data: JSON.parse(data.toString()),
        });
      } catch {
        socket.close(1007);
      }
    });
    socket.on("close", (code) => {
      if (
        this.sockets.get(command.board) !== entry ||
        revision !== this.revision
      )
        return;
      this.sockets.delete(command.board);
      if (code === 4001 && this.expire(token, revision)) return;
      this.event({
        type: "chatError",
        board: command.board,
        contextKey: command.context,
        error: "与专家的连接已断开，已有回答已保存。",
      });
    });
    socket.on("error", () => {});
    await new Promise((resolve, reject) => {
      socket.once("open", resolve);
      socket.once("error", reject);
    });
    if (
      revision !== this.revision ||
      this.sockets.get(command.board) !== entry
    ) {
      socket.close();
      throw new Error("会话已经变化。");
    }
    return socket;
  }
  async send(args) {
    const command = policy.chatCommand(args),
      revision = this.revision;
    if (command.frame.type === "user_turn")
      command.frame.mcp_servers =
        command.board === "team"
          ? (await this.validateTeam(command.agent), [])
          : await this.expertMCPs(command.agent);
    if (revision !== this.revision) throw new Error("登录状态已经变化。");
    if (command.frame.type === "cancel") {
      this.approvals.get(command.board)?.controller.abort();
      this.approvals.delete(command.board);
    }
    const socket = await this.socket(command);
    await new Promise((resolve, reject) =>
      socket.send(JSON.stringify(command.frame), (err) =>
        err ? reject(err) : resolve(),
      ),
    );
    return true;
  }
  async resume(args) {
    const command = policy.chatCommand({
      ...args,
      frame: { type: "subscribe", thread_id: args.threadId },
    });
    policy.segment(args.pendingId);
    const choices = policy.decisions(args.decisions);
    if (command.board === "team" && choices.some((d) => d.type !== "reject"))
      await this.validateTeam(command.agent);
    const prior = this.sockets.get(command.board);
    const hadSocket =
      prior?.agent === command.agent &&
      prior?.context === command.context &&
      prior?.socket.readyState === WebSocket.OPEN;
    const socket = await this.socket(command);
    if (!hadSocket) socket.send(JSON.stringify(command.frame));
    this.approvals.get(command.board)?.controller.abort();
    const controller = new AbortController(),
      revision = this.revision,
      id = randomUUID();
    this.approvals.set(command.board, { id, controller });
    try {
      const r = await this.request(
        `/api/agents/${command.agent}/chat/hitl/resume`,
        {
          method: "POST",
          body: {
            thread_id: args.threadId,
            pending_id: args.pendingId,
            decisions: choices,
          },
          stream: true,
          signal: controller.signal,
        },
      );
      if (
        r.status !== 200 ||
        !String(r.headers["content-type"]).startsWith("text/event-stream")
      ) {
        r.response.resume();
        throw new Error(
          `确认未提交（HTTP ${r.status}），请核对登录和任务状态。`,
        );
      }
      if (
        this.approvals.get(command.board)?.id !== id ||
        revision !== this.revision
      ) {
        r.response.destroy();
        throw new Error("会话已经变化。");
      }
      void this.consumeApproval(command, r.response, controller, id, revision);
      return true;
    } catch (e) {
      if (this.approvals.get(command.board)?.id === id)
        this.approvals.delete(command.board);
      controller.abort();
      const current = this.sockets.get(command.board);
      if (
        revision === this.revision &&
        current?.socket === socket &&
        current.context === command.context &&
        socket.readyState === WebSocket.OPEN
      )
        socket.send(
          JSON.stringify({ type: "cancel", thread_id: args.threadId }),
        );
      throw e;
    }
  }
  async consumeApproval(command, response, controller, id, revision) {
    const decoder = new policy.SSEDecoder(),
      utf8 = new StringDecoder("utf8");
    let terminal = false;
    try {
      for await (const chunk of response) {
        if (
          revision !== this.revision ||
          this.approvals.get(command.board)?.id !== id
        )
          break;
        for (const frame of decoder.feed(utf8.write(chunk))) {
          frame.thread_id = command.frame.thread_id;
          if (["done", "error", "hitl_required"].includes(frame.type))
            terminal = true;
          this.event({
            type: "chat",
            board: command.board,
            contextKey: command.context,
            data: frame,
          });
        }
      }
      if (!terminal && !controller.signal.aborted)
        throw new Error("确认后的连接已结束，请刷新核对任务状态。");
    } catch (e) {
      if (
        !controller.signal.aborted &&
        revision === this.revision &&
        this.approvals.get(command.board)?.id === id
      )
        this.event({
          type: "resumeError",
          board: command.board,
          contextKey: command.context,
          error: e.message,
        });
    } finally {
      if (this.approvals.get(command.board)?.id === id)
        this.approvals.delete(command.board);
      controller.abort();
    }
  }
  ping() {
    for (const { socket } of this.sockets.values())
      if (socket.readyState === WebSocket.OPEN) socket.ping();
  }
  async upload(args) {
    const id = policy.segment(args.agentId),
      mime = args.mimeType,
      bytes = Buffer.from(args.base64 || "", "base64");
    if (
      !policy.MIME_TYPES.has(mime) ||
      bytes.length > 12 * 1024 * 1024 ||
      String(args.base64).length > 17 * 1024 * 1024
    )
      throw new Error("请选择不超过12MB的图片、Excel、CSV或PDF。");
    const filename = String(args.filename || "attachment")
        .split(/[\\/]/)
        .pop()
        .replace(/["\r\n]/g, ""),
      boundary = "Dora-" + randomUUID();
    const body = Buffer.concat([
      Buffer.from(
        `--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="${filename}"\r\nContent-Type: ${mime}\r\n\r\n`,
      ),
      bytes,
      Buffer.from(`\r\n--${boundary}--\r\n`),
    ]);
    return await this.data(`/api/agents/${id}/upload`, {
      method: "POST",
      body,
      contentType: `multipart/form-data; boundary=${boundary}`,
    });
  }
}
module.exports = { BackendClient };
