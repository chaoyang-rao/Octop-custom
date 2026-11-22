export type BoardId = "aftersales" | "workbench" | "profit" | "knowledge" | "team";
export type Binding = {
  agentId: string;
  connectors: string[];
  knowledgeBases: string[];
};
export type Agent = {
  id: string;
  name: string;
  owner_user_id?: number;
  user_id?: number;
  is_running?: boolean;
  is_team?: boolean;
};
export type Resource = { id: string; name: string; usable?: boolean };
export type Attachment = {
  path: string;
  filename: string;
  media_type: string;
  url?: string;
  preview?: string;
};
export type Message = {
  id: string;
  role: "user" | "assistant";
  text: string;
  speaker?: string;
  agentId?: string;
  tools?: string[];
  reasoning?: string;
  images?: string[];
  attachments?: Attachment[];
  pending?: boolean;
  error?: string;
  inputId?: string;
  pendingId?: string;
  previewOnly?: boolean;
  teamWrapup?:boolean;
  delivery?: "pending" | "queued" | "applied" | "failed" | "removed";
};
export const boards: {
  id: BoardId;
  name: string;
}[] = [
  {
    id: "aftersales",
    name: "售后",
  },
  {
    id: "workbench",
    name: "词元",
  },
  {
    id: "profit",
    name: "负利润",
  },
  {
    id: "knowledge",
    name: "知识库",
  },
  {id:"team",name:"团队"},
];
export function asList(
  value: unknown,
  keys = ["items", "agents", "servers", "entries", "knowledge_bases"],
): Record<string, unknown>[] {
  if (Array.isArray(value))
    return value.filter((item) => item && typeof item === "object");
  if (value && typeof value === "object")
    for (const key of keys) {
      const candidate = (value as Record<string, unknown>)[key];
      if (Array.isArray(candidate)) return asList(candidate);
    }
  return [];
}
export function normalizeAgents(value: unknown, userId: number): Agent[] {
  return asList(value)
    .filter((row) => {
      const owner = row.owner_user_id ?? row.user_id;
      return owner === undefined || Number(owner) === userId;
    })
    .map((row) => ({
      id: String(row.agent_id ?? row.id),
      name: String(row.name ?? row.display_name ?? row.agent_id ?? row.id),
      is_running: row.is_running === true,
      is_team: row.is_team === true,
    }));
}
export function settingsKey(origin: string, userId: number) {
  return `octop-companion:v1:${origin}:${userId}`;
}
export function sessionKey(
  agentId: string,
  userId: number,
  board: BoardId,
  conversationId: string,
) {
  // Keep dashboard's four-part key structure, with a distinct DM subtype.
  return `${agentId}:dashboard:${userId}:companion-${board}-${conversationId}`;
}
export function acceptsRoomEvent(
  room: { conversationId: string; threadId?: string },
  event: { contextKey?: string; threadId?: unknown },
) {
  return (
    event.contextKey === room.conversationId &&
    (!room.threadId || !event.threadId || event.threadId === room.threadId)
  );
}
export function connectionCandidates(value: unknown): Resource[] {
  return asList(value)
    .filter(
      (row) =>
        row.usable !== false &&
        row.status !== "disabled" &&
        row.enabled !== false,
    )
    .map((row) => ({
      id: String(row.mcp_server_name ?? row.server_name ?? row.name ?? row.id),
      name: String(
        row.display_name ?? row.name ?? row.mcp_server_name ?? row.id,
      ),
    }))
    .filter((row) => !!row.id && row.id !== "undefined");
}
export function initialBinding(
  board: BoardId,
  agents: Agent[],
  connectors: Resource[],
): Binding {
  if (board === "team") return {agentId:"",connectors:[],knowledgeBases:[]};
  agents=agents.filter(agent=>!agent.is_team);
  const primary =
    agents.find((agent) => agent.name === "小通") ??
    agents.find((agent) => !agent.is_team) ??
    agents[0];
  const pattern =
    board === "aftersales"
      ? /aftersales|售后|质量/i
      : board === "workbench"
      ? /workbench|aiq|词元/i
      : board === "profit"
      ? /negative[-_ ]?profit|负利润|亏损/i
      : /knowledge|知识/i;
  return {
    agentId:
      (
        agents.find((agent) => pattern.test(`${agent.name} ${agent.id}`)) ??
        primary
      )?.id ?? "",
    connectors:
      board === "knowledge"
        ? []
        : connectors
            .filter((item) => pattern.test(`${item.name} ${item.id}`))
            .map((item) => item.id),
    knowledgeBases: [],
  };
}
export function turnPayload(
  binding: Binding,
  key: string,
  text: string,
  attachments: Attachment[],
  threadId?: string,
) {
  if (!binding.agentId) throw new Error("请先为这个板块选择专家。");
  const content: Record<string, unknown>[] = [];
  if (text.trim()) content.push({ type: "text", text: text.trim() });
  for (const item of attachments)
    content.push(
      item.media_type.startsWith("image/")
        ? {
            type: "image_url",
            image_url: { url: item.path },
            workspace_path: item.path,
            filename: item.filename,
            mime_type: item.media_type,
          }
        : {
            type: "file",
            workspace_path: item.path,
            filename: item.filename,
            media_type: item.media_type,
          },
    );
  // Omit permission overrides: the existing expert's Octop policy remains authoritative.
  return {
    type: "user_turn",
    session_key: key,
    ...(threadId ? { thread_id: threadId } : {}),
    messages: [{ role: "user", content }],
    // Inherit the selected expert's MCPs. An empty override would disable them.
    ...(binding.knowledgeBases.length
      ? { knowledge_base_ids: [...binding.knowledgeBases] }
      : {}),
  };
}
export function safeImageSource(source: unknown): string | null {
  if (typeof source !== "string") return null;
  if (/^data:image\/(png|jpeg|webp|gif);base64,[a-z0-9+/=]+$/i.test(source))
    return source;
  if (
    source.startsWith("/api/") &&
    !source.includes("\\") &&
    !/(?:^|\/)\.\.(?:\/|$)/.test(source)
  )
    return source;
  if (/^https:\/\//i.test(source)) return source;
  return null;
}
export function resolveImageSource(
  value: unknown,
  agentId?: string,
  mimeType?: string,
): string | null {
  const direct = safeImageSource(value);
  if (direct) return direct;
  if (typeof value !== "string" || !agentId) return null;
  let path = value.replace(/\\/g, "/");
  const media = path.match(/(?:^|\/)((?:outbound|inbound)\/.*)$/);
  if (media) path = media[1];
  else if (path.startsWith("/workspace/"))
    path = path.slice("/workspace/".length);
  else return null;
  let decoded = path;
  for (let index = 0; index < 3; index++) {
    try {
      decoded = decodeURIComponent(decoded);
    } catch {
      return null;
    }
  }
  if (decoded.split("/").includes("..") || decoded.includes("\0")) return null;
  const params = new URLSearchParams({ source: path });
  if (mimeType?.startsWith("image/")) params.set("mime_type", mimeType);
  return `/api/agents/${encodeURIComponent(agentId)}/media/preview?${params}`;
}
export function contentImages(value: unknown, agentId?: string): string[] {
  const images: string[] = [];
  function walk(item: unknown, depth = 0) {
    if (!item || depth > 10) return;
    if (
      typeof item === "string" &&
      item.length < 6_000_000 &&
      /^\s*[\[{]/.test(item)
    ) {
      try {
        walk(JSON.parse(item), depth + 1);
      } catch {
        /* Tool content may be ordinary prose. */
      }
      return;
    }
    if (Array.isArray(item)) {
      item.forEach((child) => walk(child, depth + 1));
      return;
    }
    if (typeof item !== "object") return;
    const row = item as Record<string, unknown>;
    if (
      row.type === "image_url" ||
      row.type === "image" ||
      row.kind === "image" ||
      String(row.mime_type ?? row.media_type ?? row.mediaType ?? "").startsWith(
        "image/",
      )
    ) {
      const source =
        typeof row.image_url === "object"
          ? (row.image_url as { url?: string })?.url
          : row.image_url ??
            row.preview_url ??
            row.url ??
            row.path ??
            row.localPath;
      const mime = String(
        row.mime_type ?? row.media_type ?? row.mediaType ?? "image/png",
      );
      const inline =
        typeof row.data === "string" && mime.startsWith("image/")
          ? row.data.startsWith("data:")
            ? row.data
            : `data:${mime};base64,${row.data}`
          : undefined;
      const safe = resolveImageSource(source ?? inline, agentId, mime);
      if (safe) images.push(safe);
    }
    for (const key of [
      "content",
      "messages",
      "attachments",
      "data",
      "artifacts",
      "images",
    ])
      if (row[key]) walk(row[key], depth + 1);
  }
  walk(value);
  return [...new Set(images)];
}
export function historyMessages(
  value: unknown,
  defaultAgentId?: string,
): Message[] {
  const rows = asList(value, ["messages"]);
  const messages: Message[] = [];
  rows.forEach((row, index) => {
    const kind = String(row.role ?? row.type);
    const agentId = String(
      row.speaker_agent_id ?? row.agent_id ?? defaultAgentId ?? "",
    );
    const images = contentImages(row, agentId);
    if (kind === "tool") {
      if (images.length) {
        let target = messages.at(-1);
        if (!target || target.role !== "assistant") {
          target = {
            id: `tool-media-${index}`,
            role: "assistant",
            text: "",
            agentId,
          };
          messages.push(target);
        }
        target.images = [...new Set([...(target.images ?? []), ...images])];
      }
      return;
    }
    if (!["user", "human", "assistant", "ai"].includes(kind)) return;
    const content = row.content;
    const text =
      typeof content === "string"
        ? content
        : Array.isArray(content)
        ? content
            .filter((block) => block?.type === "text")
            .map((block) => block.text ?? "")
            .join("\n")
        : "";
    messages.push({
      id: String(row.id ?? `history-${index}`),
      role: ["user", "human"].includes(String(row.role ?? row.type))
        ? "user"
        : "assistant",
      text,
      agentId,
      images,
      attachments: Array.isArray(content)
        ? content
            .filter(
              (block) =>
                ["file", "image_url", "image"].includes(block?.type) &&
                typeof block.workspace_path === "string",
            )
            .map((block) => ({
              path: block.workspace_path,
              filename: block.filename || "附件",
              media_type:
                block.media_type ||
                block.mime_type ||
                block.source?.media_type ||
                (block.type === "file"
                  ? "application/octet-stream"
                  : "image/png"),
            }))
        : [],
      speaker: typeof row.name === "string" ? row.name : undefined,
    });
  });
  return messages;
}
export function consumeFrame(
  messages: Message[],
  frame: Record<string, unknown>,
  agentName: (id: string) => string,
  defaultAgentId?: string,
): Message[] {
  const type = String(frame.type ?? "");
  const result = messages.map((message) => ({ ...message }));
  const speakerId = String(
    frame.speaker_agent_id ?? frame.agent_id ?? frame.agent ?? "",
  );
  const speaker = speakerId ? agentName(speakerId) : defaultAgentId ? agentName(defaultAgentId) : undefined;
  let target = result.at(-1);
  if (speakerId) {
    const existing=[...result].reverse().find(item=>item.role === "assistant" && item.agentId === speakerId && (item.pending || type === "done") && (!!item.teamWrapup === (frame.team_wrapup === true)));
    if (existing) target=existing;
    else if (type === "done") return result;
  }
  if (
    [
      "token",
      "reasoning",
      "tool_call_chunk",
      "tool_result",
      "attachment",
      "error",
      "hitl_required",
    ].includes(type)
  ) {
    if (
      !target ||
      target.role !== "assistant" ||
      (speaker && target.speaker && target.speaker !== speaker) ||
      (speakerId && target.agentId && target.agentId !== speakerId) ||
      (frame.team_wrapup === true && (!target.pending || !target.teamWrapup))
    ) {
      target = {
        id: crypto.randomUUID(),
        role: "assistant",
        text: "",
        speaker,
        pending: true,
        ...(frame.team_wrapup === true ? {teamWrapup:true} : {}),
      };
      result.push(target);
    }
    if (speaker) target.speaker = speaker;
    target.agentId = speakerId || defaultAgentId;
  }
  if (!target) return result;
  if (type === "token" && (frame.node === undefined || frame.node !== "tool")) {
    target.text = frame.team_snapshot
      ? String(frame.content ?? "")
      : target.text + String(frame.content ?? "");
  } else if (type === "reasoning")
    target.reasoning = (target.reasoning ?? "") + String(frame.content ?? "");
  else if (type === "tool_call_chunk" && (frame.display_name || frame.name))
    target.tools = [
      ...new Set([
        ...(target.tools ?? []),
        String(frame.display_name ?? frame.name),
      ]),
    ];
  else if (type === "attachment" || type === "tool_result")
    target.images = [
      ...new Set([
        ...(target.images ?? []),
        ...contentImages(frame, speakerId || defaultAgentId),
      ]),
    ];
  else if (type === "error") {
    target.error = String(frame.message ?? "回答未完成，请重试。");
    target.pending = false;
  } else if (type === "hitl_required") {
    target.pending = false;
  } else if (type === "done") {
    if (!speakerId || frame.team_wrapup || !frame.team_member_continuing)
      target.pending = false;
    if(frame.team_wrapup) for(const message of result) if(message.agentId === speakerId || message.agentId === defaultAgentId) message.pending=false;
  }
  return result;
}
