import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  ArrowUp,
  AudioLines,
  BookOpen,
  Check,
  ChevronDown,
  Copy,
  ImagePlus,
  LoaderCircle,
  LogIn,
  MessageCircle,
  Mic,
  Plus,
  Settings2,
  ShieldCheck,
  Square,
  Volume2,
  VolumeX,
  Wrench,
  X,
} from "lucide-react";
import { api, isNative, native, type NativeEvent } from "./bridge";
import {
  acceptsRoomEvent,
  asList,
  boards,
  connectionCandidates,
  consumeFrame,
  historyMessages,
  initialBinding,
  normalizeAgents,
  resolveImageSource,
  safeImageSource,
  sessionKey,
  settingsKey,
  turnPayload,
  type Agent,
  type Attachment,
  type Binding,
  type BoardId,
  type Message,
  type Resource,
} from "./core";
import "./styles.css";

type User = { id: number; username: string; display_name?: string };
type Status = {
  authenticated: boolean;
  origin: string;
  user?: User;
  backendRunning?: boolean;
  standalone?: boolean;
  storageScope?: string;
};
type Room = {
  binding: Binding;
  conversationId: string;
  threadId?: string;
  messages: Message[];
  draft: string;
  files: Attachment[];
  busy: boolean;
  error?: string;
};
type Rooms = Record<BoardId, Room>;
const freshRoom = (binding: Binding): Room => ({
  binding,
  conversationId: crypto.randomUUID(),
  messages: [],
  draft: "",
  files: [],
  busy: false,
});
const emptyRooms = () =>
  Object.fromEntries(
    boards.map(({ id }) => [
      id,
      freshRoom({ agentId: "", connectors: [], knowledgeBases: [] }),
    ]),
  ) as Rooms;
const errorText = (error: unknown) =>
  error instanceof Error ? error.message : "操作未完成，请重试。";
const plainSpeech = (text: string) =>
  text
    .replace(/```[\s\S]*?```/g, "，代码请查看对话框。")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, "，图片已显示在对话中。")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/[#*_`>|]/g, "")
    .trim();

function InlineImage({
  source,
  title = "回答图片",
}: {
  source: string;
  title?: string;
}) {
  const [url, setUrl] = useState<string>();
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    const safe = safeImageSource(source);
    if (!safe) return;
    if (safe.startsWith("/api/")) {
      native<{ url: string }>("image", { path: safe })
        .then((result) => {
          if (live) setUrl(result.url);
        })
        .catch((e) => {
          if (live) setError(errorText(e));
        });
    } else setUrl(safe);
    return () => {
      live = false;
    };
  }, [source]);
  return (
    <span className="answer-image" role="group" aria-label={title}>
      {url ? (
        <img
          src={url}
          alt={title}
          loading="lazy"
          onError={() => setError("图片暂时无法显示，可在 Octop 中查看。")}
        />
      ) : (
        <span>{error || "正在读取图片…"}</span>
      )}
      {url && (
        <button
          className="text-button"
          onClick={() =>
            void native("saveImage", { source, name: title }).catch((e) =>
              setError(errorText(e)),
            )
          }
        >
          保存图片
        </button>
      )}
      {error && <small role="alert">{error}</small>}
    </span>
  );
}

function MessageCard({
  message,
  agentId,
}: {
  message: Message;
  agentId: string;
}) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await native("copy", { text: message.text });
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      /* The normal text selection remains available. */
    }
  }
  return (
    <article className={`message ${message.role}`}>
      {message.role === "assistant" && (
        <div className="speaker">
          <span className="speaker-dot" />
          {message.speaker || "专家"}
        </div>
      )}
      <div className="message-body">
        {message.attachments?.map(
          (item) =>
            item.preview && (
              <img
                key={item.path}
                className="input-image"
                src={item.preview}
                alt={item.filename}
              />
            ),
        )}
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            a: ({ href, children }) => (
              <a
                href={href}
                onClick={(event) => {
                  event.preventDefault();
                  if (href) void native("openLink", { url: href });
                }}
              >
                {children}
              </a>
            ),
            img: ({ src, alt }) =>
              src && resolveImageSource(src, message.agentId || agentId) ? (
                <InlineImage
                  source={resolveImageSource(src, message.agentId || agentId)!}
                  title={alt}
                />
              ) : (
                <span>图片链接不可用</span>
              ),
          }}
        >
          {message.text}
        </ReactMarkdown>
        {message.images?.map((url) => (
          <InlineImage key={url} source={url} />
        ))}
        {message.pending && !message.text && (
          <div className="thinking" role="status">
            <span />
            <span />
            <span />
            <span className="sr-only">正在回答</span>
          </div>
        )}
        {message.error && (
          <div className="message-error" role="alert">
            {message.error}
          </div>
        )}
      </div>
      {((message.tools?.length ?? 0) > 0 || message.reasoning) && (
        <details className="process">
          <summary>
            查看处理过程
            {message.tools?.length ? ` · ${message.tools.length} 项工具` : ""}
            <ChevronDown size={13} />
          </summary>
          {message.tools?.map((tool) => (
            <div key={tool} className="tool-item">
              <Wrench size={12} />
              {tool}
            </div>
          ))}
          {message.reasoning && <pre>{message.reasoning}</pre>}
        </details>
      )}
      {message.role === "assistant" && message.text && !message.pending && (
        <div className="message-actions">
          <button
            title="复制回答"
            aria-label="复制回答"
            onClick={() => void copy()}
          >
            {copied ? <Check size={14} /> : <Copy size={14} />}
          </button>
          <button
            title="朗读回答"
            aria-label="朗读回答"
            onClick={() =>
              void native("speak", { text: plainSpeech(message.text) })
            }
          >
            <Volume2 size={14} />
          </button>
        </div>
      )}
    </article>
  );
}

function App() {
  const [status, setStatus] = useState<Status>({
    authenticated: false,
    origin: "",
    standalone: true,
  });
  const [rooms, setRooms] = useState<Rooms>(emptyRooms);
  const [active, setActive] = useState<BoardId>("aftersales");
  const [agents, setAgents] = useState<Agent[]>([]);
  const [connectors, setConnectors] = useState<Resource[]>([]);
  const [knowledge, setKnowledge] = useState<Resource[]>([]);
  const [showSettings, setShowSettings] = useState(false);
  const [originDraft, setOriginDraft] = useState(status.origin);
  const [loading, setLoading] = useState(false);
  const [voice, setVoice] = useState(true);
  const [speaking, setSpeaking] = useState(false);
  const [listening, setListening] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [notice, setNotice] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const roomsRef = useRef(rooms);
  const activeRef = useRef(active);
  const voiceRef = useRef(voice);
  const agentsRef = useRef(agents);
  const userRef = useRef<User>();
  const voiceDraft = useRef<{
    board: BoardId;
    text: string;
    lastApplied: string;
    owner: string | null;
    conversationId: string;
  }>({
    board: active,
    text: "",
    lastApplied: "",
    owner: null,
    conversationId: "",
  });
  const refreshRevision = useRef(0);
  const loadedOwner = useRef<string | null>(null);
  const ownerKey =
    status.authenticated && status.user?.id !== undefined
      ? settingsKey(status.storageScope ?? status.origin, status.user.id)
      : null;
  const ownerRef = useRef(ownerKey);
  ownerRef.current = ownerKey;
  activeRef.current = active;
  voiceRef.current = voice;
  agentsRef.current = agents;
  userRef.current = status.user;
  const room = rooms[active];
  const board = boards.find((value) => value.id === active)!;
  const chosenAgent = agents.find((agent) => agent.id === room.binding.agentId);
  const selectedResources =
    active === "knowledge"
      ? room.binding.knowledgeBases
      : room.binding.connectors;
  const visibleResources = active === "knowledge" ? knowledge : connectors;
  const resourceChoices = [
    ...visibleResources,
    ...selectedResources
      .filter((id) => !visibleResources.some((item) => item.id === id))
      .map((id) => ({ id, name: `${id}（当前不可用）` })),
  ];
  const identity = status.user?.display_name || status.user?.username;

  function updateRoom(
    id: BoardId,
    change: Partial<Room> | ((room: Room) => Room),
  ) {
    const previous = roomsRef.current;
    const next = {
      ...previous,
      [id]:
        typeof change === "function"
          ? change(previous[id])
          : { ...previous[id], ...change },
    };
    roomsRef.current = next;
    setRooms(next);
  }
  function replaceRooms(next: Rooms) {
    roomsRef.current = next;
    setRooms(next);
  }

  async function refresh() {
    const revision = ++refreshRevision.current;
    setLoading(true);
    setNotice("");
    try {
      const next = await native<Status>("status");
      if (revision !== refreshRevision.current) return;
      const nextOwner =
        next.authenticated && next.user?.id !== undefined
          ? settingsKey(next.storageScope ?? next.origin, next.user.id)
          : null;
      const previouslyLoaded =
        loadedOwner.current === nextOwner && nextOwner !== null;
      if (!previouslyLoaded) {
        replaceRooms(emptyRooms());
        setAgents([]);
        setConnectors([]);
        setKnowledge([]);
        voiceDraft.current.owner = null;
      }
      setStatus(next);
      setOriginDraft(next.origin);
      if (next.backendRunning === false)
        setNotice("问答引擎暂未就绪，请重试或在桌宠菜单查看运行日志。");
      if (!next.authenticated || !next.user) {
        loadedOwner.current = null;
        replaceRooms(emptyRooms());
        setAgents([]);
        return;
      }
      const [agentResult, instanceResult, knowledgeResult] =
        await Promise.allSettled([
          api("/api/agents"),
          api("/api/connector-instances"),
          api("/api/knowledge-bases"),
        ]);
      if (revision !== refreshRevision.current) return;
      if (agentResult.status === "rejected") throw agentResult.reason;
      const owned = normalizeAgents(agentResult.value, next.user.id);
      const connections =
        instanceResult.status === "fulfilled"
          ? connectionCandidates(instanceResult.value)
          : [];
      const bases =
        knowledgeResult.status === "fulfilled"
          ? asList(knowledgeResult.value).map((row) => ({
              id: String(row.knowledge_base_id ?? row.id),
              name: String(row.name ?? row.title ?? row.id),
            }))
          : [];
      setAgents(owned);
      if (next.standalone && !owned.length)
        setNotice(
          "暂无已开放的专家。请联系企业超级管理员在“桌宠开放专家”中配置，并确认本人有对应权限。",
        );
      setConnectors(connections);
      setKnowledge(bases);
      if (previouslyLoaded) return;
      let saved: { rooms?: Record<BoardId, Partial<Room>>; voice?: boolean } =
        {};
      try {
        saved = JSON.parse(
          localStorage.getItem(
            settingsKey(next.storageScope ?? next.origin, next.user.id),
          ) || "{}",
        );
      } catch {
        /* Invalid local view preferences do not alter server data. */
      }
      const restored = Object.fromEntries(
        boards.map(({ id }) => {
          const old = saved.rooms?.[id];
          let binding = old?.binding || initialBinding(id, owned, connections);
          if (
            !binding ||
            typeof binding.agentId !== "string" ||
            !Array.isArray(binding.connectors) ||
            !Array.isArray(binding.knowledgeBases)
          )
            binding = initialBinding(id, owned, connections);
          return [
            id,
            {
              ...freshRoom(binding),
              ...(old
                ? {
                    conversationId: old.conversationId || crypto.randomUUID(),
                    threadId: old.threadId,
                    draft: old.draft || "",
                  }
                : {}),
            },
          ];
        }),
      ) as Rooms;
      loadedOwner.current = nextOwner;
      replaceRooms(restored);
      setVoice(saved.voice ?? true);
      if (knowledgeResult.status === "rejected")
        setNotice("知识库列表暂时不可用，请检查该账号的知识库权限。");
      await Promise.all(
        boards.map(async ({ id }) => {
          const item = restored[id];
          if (!item.threadId || !item.binding.agentId) return;
          try {
            const history = await api<{
              messages: unknown[];
              turn_active?: boolean;
            }>(
              `/api/agents/${encodeURIComponent(
                item.binding.agentId,
              )}/threads/${encodeURIComponent(
                item.threadId,
              )}/history?limit=100`,
            );
            if (
              revision !== refreshRevision.current ||
              roomsRef.current[id].threadId !== item.threadId ||
              roomsRef.current[id].binding.agentId !== item.binding.agentId
            )
              return;
            updateRoom(id, {
              messages: historyMessages(history, item.binding.agentId),
              busy: !!history.turn_active,
            });
            if (history.turn_active)
              await native("chatSend", {
                board: id,
                contextKey: item.conversationId,
                agentId: item.binding.agentId,
                frame: { type: "subscribe", thread_id: item.threadId },
              });
          } catch (error) {
            updateRoom(id, { error: errorText(error) });
          }
        }),
      );
    } catch (error) {
      if (revision === refreshRevision.current) setNotice(errorText(error));
    } finally {
      if (revision === refreshRevision.current) setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);
  useEffect(() => {
    if (status.authenticated || status.backendRunning !== false || loading)
      return;
    const timer = window.setTimeout(() => void refresh(), 4000);
    return () => clearTimeout(timer);
  }, [status.authenticated, status.backendRunning, loading]);
  const persistence = JSON.stringify({
    voice,
    rooms: Object.fromEntries(
      boards.map(({ id }) => {
        const item = rooms[id];
        return [
          id,
          {
            binding: item.binding,
            conversationId: item.conversationId,
            threadId: item.threadId,
            draft: item.draft,
          },
        ];
      }),
    ),
  });
  useEffect(() => {
    if (ownerKey && !loading) localStorage.setItem(ownerKey, persistence);
  }, [ownerKey, persistence, loading]);

  useEffect(() => {
    if (!status.authenticated || !status.user || !ownerKey) return;
    let live = true,
      running = false;
    const userId = status.user.id,
      owner = ownerKey;
    const refreshDirectory = async () => {
      if (running) return;
      running = true;
      try {
        const [agentResult, connectionResult, knowledgeResult] =
          await Promise.allSettled([
            api("/api/agents"),
            api("/api/connector-instances"),
            api("/api/knowledge-bases"),
          ]);
        if (!live || ownerRef.current !== owner) return;
        if (agentResult.status === "fulfilled")
          setAgents(normalizeAgents(agentResult.value, userId));
        if (connectionResult.status === "fulfilled")
          setConnectors(connectionCandidates(connectionResult.value));
        if (knowledgeResult.status === "fulfilled")
          setKnowledge(
            asList(knowledgeResult.value).map((row) => ({
              id: String(row.knowledge_base_id ?? row.id),
              name: String(row.name ?? row.title ?? row.id),
            })),
          );
        // Failed or changed directories never erase a member's saved binding/draft.
      } finally {
        running = false;
      }
    };
    const timer = window.setInterval(() => void refreshDirectory(), 30_000);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, [status.authenticated, status.user?.id, ownerKey]);

  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent<NativeEvent>).detail;
      if (detail.type === "authChanged") {
        void refresh();
        return;
      }
      if (detail.type === "authExpired") {
        ++refreshRevision.current;
        loadedOwner.current = null;
        voiceDraft.current.owner = null;
        setListening(false);
        setSpeaking(false);
        setLoading(false);
        setStatus((value) => ({
          ...value,
          authenticated: false,
          user: undefined,
        }));
        replaceRooms(emptyRooms());
        setNotice("登录已过期，请重新连接原来的 Octop 账号。");
        return;
      }
      if (detail.type === "voice") {
        if (detail.text !== undefined) {
          const base = voiceDraft.current;
          const current = roomsRef.current[base.board];
          if (
            base.owner === ownerRef.current &&
            base.conversationId === current.conversationId &&
            current.draft === base.lastApplied
          ) {
            const text = [base.text, detail.text].filter(Boolean).join(" ");
            base.lastApplied = text;
            updateRoom(base.board, { draft: text });
          }
        }
        if (detail.error) {
          setNotice(detail.error);
          setListening(false);
        }
        if (detail.data === "started") setListening(true);
        if (detail.data === "stopped") setListening(false);
        return;
      }
      if (detail.type === "speech") {
        setSpeaking(detail.data === "started");
        if (
          detail.data !== "started" &&
          Object.values(roomsRef.current).some((item) => item.busy)
        )
          void native("petState", { state: "working" });
        return;
      }
      if (detail.type === "focusVoice") {
        inputRef.current?.focus();
        return;
      }
      if (detail.type === "chatError" && detail.board) {
        if (acceptsRoomEvent(roomsRef.current[detail.board as BoardId], detail))
          updateRoom(detail.board as BoardId, {
            busy: false,
            error: detail.error || "与专家的连接已断开，请重试。",
          });
        return;
      }
      if (
        detail.type !== "chat" ||
        !detail.board ||
        !detail.data ||
        typeof detail.data !== "object"
      )
        return;
      const id = detail.board as BoardId;
      const frame = detail.data as Record<string, unknown>;
      const current = roomsRef.current[id];
      if (
        !acceptsRoomEvent(current, {
          contextKey: detail.contextKey,
          threadId: frame.thread_id,
        })
      )
        return;
      if (
        ["steer.rejected", "steer.expired", "steer.discarded"].includes(
          String(frame.type),
        )
      ) {
        const last = current.messages
          .filter((message) => message.role === "user")
          .at(-1);
        updateRoom(id, {
          busy: false,
          error:
            "这条消息尚未执行。请先在 Octop 中确认上一项任务状态，再继续发送。",
          draft: current.draft || last?.text || "",
          files: current.files.length ? current.files : last?.attachments || [],
        });
        return;
      }
      if (frame.type === "turn_status" && typeof frame.active === "boolean") {
        updateRoom(id, (value) => ({
          ...value,
          busy: frame.active as boolean,
          messages: frame.active
            ? value.messages
            : value.messages.map((message) => ({ ...message, pending: false })),
        }));
        return;
      }
      const speakerId = String(
        frame.speaker_agent_id ?? frame.agent_id ?? frame.agent ?? "",
      );
      const finished =
        frame.type === "done" &&
        !frame.team_member_continuing &&
        (!speakerId ||
          speakerId === current.binding.agentId ||
          frame.team_wrapup === true);
      if (finished && voiceRef.current && activeRef.current === id) {
        const last = current.messages
          .filter((item) => item.role === "assistant" && item.text)
          .at(-1);
        if (last)
          void native("speak", { text: plainSpeech(last.text) }).catch(
            (error) => setNotice(errorText(error)),
          );
      }
      updateRoom(id, (value) => ({
        ...value,
        ...(typeof frame.thread_id === "string"
          ? { threadId: frame.thread_id }
          : {}),
        busy:
          frame.type === "error" || frame.type === "hitl_required" || finished
            ? false
            : value.busy,
        messages: consumeFrame(
          value.messages,
          frame,
          (agentId) =>
            agentsRef.current.find((item) => item.id === agentId)?.name ||
            agentId,
          value.binding.agentId,
        ),
      }));
      if (finished || frame.type === "error")
        void native("petState", {
          state: Object.entries(roomsRef.current).some(
            ([key, value]) => key !== id && value.busy,
          )
            ? "working"
            : frame.type === "error"
              ? "error"
              : "success",
        });
    };
    window.addEventListener("companion", handler);
    return () => window.removeEventListener("companion", handler);
  }, []);

  useEffect(() => {
    const element = scrollRef.current;
    if (
      element &&
      element.scrollHeight - element.scrollTop - element.clientHeight < 180
    )
      element.scrollTop = element.scrollHeight;
  }, [room.messages]);

  async function send() {
    const id = active;
    const current = roomsRef.current[id];
    const user = userRef.current;
    const owner = ownerRef.current;
    if (
      !user ||
      !status.authenticated ||
      current.busy ||
      uploading ||
      (!current.draft.trim() && !current.files.length)
    )
      return;
    if (
      !current.binding.agentId ||
      (id !== "knowledge" && !current.binding.connectors.length)
    ) {
      setShowSettings(true);
      updateRoom(id, {
        error: !current.binding.agentId
          ? "请先选择管理员已开放的专家。"
          : "先选择专家和本人已授权的连接器，再查询业务数据。",
      });
      return;
    }
    if (
      !agents.some((item) => item.id === current.binding.agentId) ||
      current.binding.connectors.some(
        (name) => !connectors.some((item) => item.id === name),
      ) ||
      current.binding.knowledgeBases.some(
        (name) => !knowledge.some((item) => item.id === name),
      )
    ) {
      setShowSettings(true);
      updateRoom(id, {
        error:
          "原先选择的专家或资源当前不可用，已保留你的选择。请先核对个人授权与资源分配。",
      });
      return;
    }
    const message: Message = {
      id: crypto.randomUUID(),
      role: "user",
      text: current.draft,
      attachments: current.files,
    };
    updateRoom(id, (value) => ({
      ...value,
      messages: [...value.messages, message],
      draft: "",
      files: [],
      busy: true,
      error: undefined,
    }));
    void native("stopSpeaking");
    void native("petState", { state: "working" });
    try {
      await native("chatSend", {
        board: id,
        contextKey: current.conversationId,
        agentId: current.binding.agentId,
        frame: turnPayload(
          current.binding,
          sessionKey(
            current.binding.agentId,
            user.id,
            id,
            current.conversationId,
          ),
          current.draft,
          current.files,
          current.threadId,
        ),
      });
    } catch (error) {
      if (
        ownerRef.current === owner &&
        roomsRef.current[id].conversationId === current.conversationId
      )
        updateRoom(id, (value) => ({
          ...value,
          busy: false,
          error: errorText(error),
          draft: current.draft,
          files: current.files,
        }));
    }
  }

  async function addFiles(files: File[]) {
    const id = active;
    const current = roomsRef.current[id];
    const owner = ownerRef.current;
    if (!status.authenticated || !current.binding.agentId) {
      setNotice("请先登录并选择当前板块的专家。");
      return;
    }
    if (uploading || current.busy) return;
    setUploading(true);
    setNotice("");
    try {
      for (const file of files.slice(0, 4 - current.files.length)) {
        if (
          !/^image\/(png|jpeg|webp|gif)$/.test(file.type) ||
          file.size > 12 * 1024 * 1024
        )
          throw new Error("请选择不超过 12 MB 的 PNG、JPG、WebP 或 GIF 图片。");
        const base64 = await new Promise<string>((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(String(reader.result).split(",")[1]);
          reader.onerror = reject;
          reader.readAsDataURL(file);
        });
        const uploaded = await native<Attachment>("upload", {
          agentId: current.binding.agentId,
          filename: file.name,
          mimeType: file.type,
          base64,
        });
        if (
          ownerRef.current !== owner ||
          roomsRef.current[id].conversationId !== current.conversationId
        )
          return;
        updateRoom(id, (value) => ({
          ...value,
          files: [
            ...value.files,
            { ...uploaded, preview: `data:${file.type};base64,${base64}` },
          ],
        }));
      }
    } catch (error) {
      setNotice(errorText(error));
    } finally {
      setUploading(false);
    }
  }

  async function toggleMic() {
    if (listening) {
      await native("stopListening");
      setListening(false);
      return;
    }
    voiceDraft.current = {
      board: active,
      text: room.draft,
      lastApplied: room.draft,
      owner: ownerRef.current,
      conversationId: room.conversationId,
    };
    setListening(true);
    setNotice("");
    try {
      await native("startListening");
    } catch (error) {
      setListening(false);
      setNotice(errorText(error));
    }
  }

  function changeBinding(binding: Binding) {
    if (room.busy) return;
    if (JSON.stringify(room.binding) === JSON.stringify(binding)) return;
    if (listening) {
      void native("stopListening");
      setListening(false);
    }
    updateRoom(active, {
      binding,
      conversationId: crypto.randomUUID(),
      threadId: undefined,
      messages: [],
      files: [],
      error: undefined,
    });
    void native("chatClose", { board: active }).catch(() => {});
  }

  return (
    <main
      className="shell"
      onDragOver={(event) => {
        event.preventDefault();
      }}
      onDrop={(event) => {
        event.preventDefault();
        void addFiles([...event.dataTransfer.files]);
      }}
    >
      <header className="topbar">
        <div className="app-mark">
          <MessageCircle size={18} />
          <div>
            <strong>哆啦</strong>
            <span>
              {identity ? `${identity} · 本机运行` : "让问题随时有个入口"}
            </span>
          </div>
        </div>
        <div className="top-actions">
          <button
            aria-label={voice ? "关闭自动朗读" : "开启自动朗读"}
            title={voice ? "自动朗读已开启" : "开启自动朗读"}
            className={voice ? "selected" : ""}
            onClick={() => {
              setVoice(!voice);
              if (voice) void native("stopSpeaking");
            }}
          >
            {voice ? <Volume2 size={17} /> : <VolumeX size={17} />}
          </button>
          <button
            aria-label="设置板块"
            title="板块设置"
            className={showSettings ? "selected" : ""}
            onClick={() => setShowSettings(!showSettings)}
          >
            <Settings2 size={17} />
          </button>
        </div>
      </header>
      <nav className="boards" aria-label="选择问答板块">
        {boards.map((item) => (
          <button
            key={item.id}
            aria-pressed={item.id === active}
            className={`board ${item.id} ${item.id === active ? "active" : ""}`}
            onClick={() => {
              if (listening) {
                void native("stopListening");
                setListening(false);
              }
              setActive(item.id);
              setNotice("");
            }}
          >
            <span className="board-icon">
              {item.id === "aftersales" ? (
                <Wrench size={17} />
              ) : item.id === "workbench" ? (
                <AudioLines size={17} />
              ) : (
                <BookOpen size={17} />
              )}
            </span>
            {item.name}
            {rooms[item.id].busy && <LoaderCircle size={12} className="spin" />}
          </button>
        ))}
      </nav>
      {!status.authenticated ? (
        <section className="login-state">
          <div className="welcome-orbit">
            <ShieldCheck size={30} />
          </div>
          <h1>登录桌宠</h1>
          <p>使用企业飞书账号，获取管理员开放的专家，再完成本人的 MCP 授权。</p>
          <button
            className="primary"
            disabled={!isNative() || loading}
            onClick={() =>
              void native("login").catch((e) => setNotice(errorText(e)))
            }
          >
            <LogIn size={16} />
            使用企业飞书登录
          </button>
          <button
            className="text-button"
            disabled={!isNative()}
            onClick={() => void native("startOctop")}
          >
            连接设置
          </button>
          {!isNative() && (
            <small>浏览器预览 · 实际登录与问答请使用 Mac 桌宠应用</small>
          )}
          <small>内置问答引擎 · 无需另装 Octop</small>
        </section>
      ) : (
        <>
          {showSettings && (
            <section className="settings-panel" aria-label="当前板块设置">
              <div className="section-title">
                <strong>{board.name}板块设置</strong>
                <button
                  aria-label="关闭设置"
                  onClick={() => setShowSettings(false)}
                >
                  <X size={15} />
                </button>
              </div>
              <label>
                回答专家
                <select
                  disabled={room.busy}
                  value={room.binding.agentId}
                  onChange={(event) =>
                    void changeBinding({
                      ...room.binding,
                      agentId: event.target.value,
                    })
                  }
                >
                  <option value="">请选择专家</option>
                  {room.binding.agentId && !chosenAgent && (
                    <option value={room.binding.agentId}>
                      原专家（当前不可用）
                    </option>
                  )}
                  {agents.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name}
                    </option>
                  ))}
                </select>
              </label>
              <fieldset disabled={room.busy}>
                <legend>
                  {active === "knowledge" ? "检索知识库" : "使用的连接器"}
                </legend>
                <div className="resource-options">
                  {resourceChoices.map((item) => {
                    const selected =
                      active === "knowledge"
                        ? room.binding.knowledgeBases
                        : room.binding.connectors;
                    return (
                      <label key={item.id}>
                        <input
                          type="checkbox"
                          checked={selected.includes(item.id)}
                          onChange={(event) => {
                            const values = event.target.checked
                              ? [...selected, item.id]
                              : selected.filter((id) => id !== item.id);
                            void changeBinding({
                              ...room.binding,
                              [active === "knowledge"
                                ? "knowledgeBases"
                                : "connectors"]: values,
                            });
                          }}
                        />
                        {item.name}
                      </label>
                    );
                  })}
                  {!(active === "knowledge" ? knowledge : connectors)
                    .length && (
                    <small>
                      暂无可用资源，请在资源设置中完成个人授权或添加知识库。
                    </small>
                  )}
                </div>
              </fieldset>
              <div className="settings-footer">
                <button
                  className="text-button"
                  onClick={() =>
                    void native("openOctop", {
                      path:
                        active === "knowledge"
                          ? "/knowledge-bases"
                          : "/connectors",
                    })
                  }
                >
                  管理资源与授权
                </button>
                <button
                  className="text-button"
                  disabled={
                    loading || Object.values(rooms).some((value) => value.busy)
                  }
                  onClick={() => void refresh()}
                >
                  {loading ? "刷新中…" : "刷新资源"}
                </button>
              </div>
              <small>
                更换专家或资源会开始新对话，原会话保留。专家由企业管理员开放。
              </small>
              <div className="settings-footer">
                <button
                  className="text-button"
                  disabled={Object.values(rooms).some((item) => item.busy)}
                  onClick={() =>
                    void native("logout").catch((error) =>
                      setNotice(errorText(error)),
                    )
                  }
                >
                  退出桌宠账号
                </button>
              </div>
            </section>
          )}
          <div className="conversation-meta">
            <span>
              <span className={`status-dot ${room.busy ? "busy" : ""}`} />
              {chosenAgent?.name || "请选择专家"}
              {room.busy
                ? " · 正在处理"
                : active === "knowledge" && !room.binding.knowledgeBases.length
                  ? " · 未绑定知识库，可用本轮文字或图片提问"
                  : ` · ${board.hint}`}
            </span>
            <button
              title="新对话"
              aria-label="新对话"
              disabled={room.busy || uploading}
              onClick={() => {
                void native("chatClose", { board: active });
                updateRoom(active, {
                  ...freshRoom(room.binding),
                  draft: room.draft,
                });
              }}
            >
              <Plus size={16} />
            </button>
          </div>
          <div
            className="messages"
            ref={scrollRef}
            role="log"
            aria-label={`${board.name}对话`}
            aria-live="polite"
          >
            {!room.messages.length && (
              <div className="empty-state">
                <span className={`empty-icon ${active}`}>
                  {active === "aftersales" ? (
                    <Wrench size={24} />
                  ) : active === "workbench" ? (
                    <AudioLines size={24} />
                  ) : (
                    <BookOpen size={24} />
                  )}
                </span>
                <h1>{board.name}，从这里问起</h1>
                <p>
                  {active === "knowledge" && !room.binding.knowledgeBases.length
                    ? "知识库可后续接入。现在可以先提供文字或图片提问。"
                    : `${board.hint}。文字、语音或图片都可以。`}
                </p>
                <div className="suggestions">
                  {board.examples.map((text) => (
                    <button
                      key={text}
                      onClick={() => {
                        updateRoom(active, { draft: text });
                        inputRef.current?.focus();
                      }}
                    >
                      {text}
                      <ArrowUp size={13} />
                    </button>
                  ))}
                </div>
                <button
                  className="text-button"
                  onClick={() => setShowSettings(true)}
                >
                  选择专家与{active === "knowledge" ? "知识库" : "连接器"}
                </button>
              </div>
            )}
            {room.messages.map((message) => (
              <MessageCard
                key={message.id}
                message={message}
                agentId={room.binding.agentId}
              />
            ))}
          </div>
        </>
      )}
      {(notice || room.error) && (
        <div role="alert" className="notice">
          {notice || room.error}
          <button
            aria-label="关闭提示"
            onClick={() => {
              setNotice("");
              updateRoom(active, { error: undefined });
            }}
          >
            <X size={14} />
          </button>
        </div>
      )}
      <section className="composer" aria-label="消息输入">
        <div className="attachment-strip">
          {room.files.map((item, index) => (
            <div key={`${item.path}-${index}`}>
              <img src={item.preview} alt={item.filename} />
              <button
                aria-label={`移除 ${item.filename}`}
                onClick={() =>
                  updateRoom(active, {
                    files: room.files.filter((_, i) => i !== index),
                  })
                }
              >
                <X size={12} />
              </button>
            </div>
          ))}
        </div>
        <textarea
          ref={inputRef}
          aria-label="输入问题"
          placeholder={
            status.authenticated
              ? `向${board.name}专家提问，或粘贴一张图片…`
              : "登录后开始提问"
          }
          value={room.draft}
          disabled={!status.authenticated || loading}
          rows={2}
          onChange={(event) =>
            updateRoom(active, { draft: event.target.value })
          }
          onPaste={(event) => {
            const files = [...event.clipboardData.files];
            if (files.length) {
              event.preventDefault();
              void addFiles(files);
            }
          }}
          onKeyDown={(event) => {
            if (
              event.key === "Enter" &&
              !event.shiftKey &&
              !event.nativeEvent.isComposing
            ) {
              event.preventDefault();
              void send();
            }
          }}
        />
        <div className="composer-bottom">
          <div className="input-tools">
            <button
              aria-label="添加图片"
              title="添加图片，也可拖入或粘贴"
              disabled={
                !status.authenticated ||
                room.busy ||
                uploading ||
                room.files.length >= 4
              }
              onClick={() => fileRef.current?.click()}
            >
              {uploading ? (
                <LoaderCircle size={18} className="spin" />
              ) : (
                <ImagePlus size={18} />
              )}
            </button>
            <button
              aria-label={listening ? "结束语音输入" : "开始语音输入"}
              title={listening ? "结束录音，文字保留在输入框" : "语音输入"}
              aria-pressed={listening}
              className={listening ? "recording" : ""}
              disabled={!status.authenticated || room.busy}
              onClick={() =>
                void toggleMic().catch((e) => setNotice(errorText(e)))
              }
            >
              {listening ? <Square size={16} /> : <Mic size={18} />}
            </button>
            {speaking && (
              <button
                aria-label="停止朗读"
                title="停止朗读"
                onClick={() => void native("stopSpeaking")}
              >
                <VolumeX size={18} />
              </button>
            )}
            <span>
              {listening
                ? "正在聆听 · 再次点击结束"
                : uploading
                  ? "正在上传图片…"
                  : "Enter 发送"}
            </span>
          </div>
          {room.busy ? (
            <button
              className="send stop"
              aria-label="停止回答"
              onClick={() => {
                if (room.threadId)
                  void native("chatSend", {
                    board: active,
                    agentId: room.binding.agentId,
                    frame: { type: "cancel", thread_id: room.threadId },
                  });
              }}
            >
              <Square size={15} />
            </button>
          ) : (
            <button
              className="send"
              aria-label="发送消息"
              disabled={
                !status.authenticated ||
                uploading ||
                listening ||
                (!room.draft.trim() && !room.files.length)
              }
              onClick={() => void send()}
            >
              <ArrowUp size={18} />
            </button>
          )}
        </div>
        <input
          ref={fileRef}
          type="file"
          accept="image/png,image/jpeg,image/webp,image/gif"
          multiple
          hidden
          onChange={(event) => {
            void addFiles([...(event.target.files || [])]);
            event.target.value = "";
          }}
        />
      </section>
      <footer className="footnote">
        <span>会话保存在本机 · 本人授权</span>
        <button
          className="text-button"
          onClick={() =>
            void native("openOctop", {
              path: room.binding.agentId
                ? `/chat/${encodeURIComponent(room.binding.agentId)}${
                    room.threadId ? `/${encodeURIComponent(room.threadId)}` : ""
                  }`
                : "/",
            })
          }
        >
          资源与模型设置
        </button>
      </footer>
      {showSettings && !status.authenticated && !status.standalone && (
        <section className="backend-settings">
          <label>
            本机 Octop 地址
            <input
              value={originDraft}
              onChange={(event) => setOriginDraft(event.target.value)}
            />
          </label>
          <button
            className="primary"
            onClick={() =>
              void native("setOrigin", { origin: originDraft })
                .then(() => refresh())
                .catch((error) => setNotice(errorText(error)))
            }
          >
            保存并连接
          </button>
        </section>
      )}
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
