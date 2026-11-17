import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  ArrowUp,
  Check,
  ChevronDown,
  ChevronLeft,
  Copy,
  ImagePlus,
  LoaderCircle,
  LogIn,
  MessageCircle,
  Mic,
  MoreHorizontal,
  Plus,
  Settings,
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
import ApprovalCard from "./ApprovalCard";
import TeamSettings from "./TeamSettings";
import {
  teamRecords,
  markTeams,
  teamProblem,
  liveTeamSpeakers,
  type TeamRecord,
} from "./teams";
import {
  attachmentMime,
  canFlushQueue,
  chatCommand,
  pendingApproval,
  safeQueuedInputs,
  type Approval,
  type QueuedInput,
} from "./controls";

type User = { id: number; username: string; display_name?: string };
type Status = {
  authenticated: boolean;
  origin: string;
  user?: User;
  backendRunning?: boolean;
  standalone?: boolean;
  storageScope?: string;
  companionAllowed?: boolean;
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
  queue: QueuedInput[];
  approvals: Approval[];
  queuePaused?: boolean;
  activeTurnId?: string;
  awaitingApproval?: boolean;
  stopping?: boolean;
  cancelSent?: boolean;
  controlStatus?: string;
  resumingId?: string;
  resumeRejected?: boolean;
  approvalStreamActive?: boolean;
  completedTurnId?: string;
  awaitingStatus?: boolean;
  cancelVersion?: number;
  teamSpeakers: string[];
};
type Rooms = Record<BoardId, Room>;
const freshRoom = (binding: Binding): Room => ({
  binding,
  conversationId: crypto.randomUUID(),
  messages: [],
  draft: "",
  files: [],
  busy: false,
  queue: [],
  approvals: [],
  teamSpeakers: [],
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
  onResend,
  onEdit,
  onWithdraw,
  disabled,
}: {
  message: Message;
  agentId: string;
  onResend: () => void;
  onEdit: () => void;
  onWithdraw: () => void;
  disabled: boolean;
}) {
  const [copied, setCopied] = useState(false);
  if (
    !message.pending &&
    !message.text.trim() &&
    !message.error &&
    !message.images?.length &&
    !message.attachments?.length &&
    !message.tools?.length &&
    !message.reasoning?.trim()
  )
    return null;
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
        {message.attachments?.map((item) =>
          item.preview ? (
            <img
              key={item.path}
              className="input-image"
              src={item.preview}
              alt={item.filename}
            />
          ) : !item.media_type.startsWith("image/") ? (
            <span className="file-chip" key={item.path}>
              {item.filename}
            </span>
          ) : null,
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
        {message.images?.map((url) => <InlineImage key={url} source={url} />)}
        {message.pending && !message.text && (
          <div className="thinking" role="status" aria-label="正在回答">
            <span aria-hidden="true" />
            <span aria-hidden="true" />
            <span aria-hidden="true" />
          </div>
        )}
        {message.error && (
          <div className="message-error" role="alert">
            {message.error}
          </div>
        )}
      </div>
      {message.delivery && (
        <div className="delivery-state" role="status">
          {
            {
              pending: "正在补充…",
              queued: "等待本轮接收",
              applied: "已补充到本轮",
              failed: "未执行，内容已保留",
              removed: "已撤回",
            }[message.delivery]
          }
          {message.delivery === "queued" && message.pendingId && (
            <button onClick={onWithdraw}>撤回</button>
          )}
        </div>
      )}
      {!message.pending && !message.previewOnly && (
        <details className="message-menu">
          <summary aria-label="消息操作">
            <MoreHorizontal size={15} />
          </summary>
          <div>
            <button disabled={disabled} onClick={onResend}>
              {message.role === "assistant"
                ? message.error
                  ? "重试"
                  : "重新回答"
                : "再次发送"}
            </button>
            <button disabled={disabled} onClick={onEdit}>
              编辑后再发
            </button>
          </div>
        </details>
      )}
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
  const [teams, setTeams] = useState<TeamRecord[]>([]);
  const [teamsError, setTeamsError] = useState("");
  const teamsRef = useRef(teams);
  teamsRef.current = teams;
  const teamRoomsRef = useRef<Record<string, Room>>({});
  const [showSettings, setShowSettings] = useState(false);
  const [edgeHiding, setEdgeHiding] = useState(true);
  const settingsRef = useRef<HTMLElement>(null);
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
  const selectedTeam = teams.find((t) => t.agent_id === room.binding.agentId);
  const experts = agents.filter((a) => !a.is_team);
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
  function speakerName(id: string, teamId?: string) {
    const team = teamsRef.current.find((t) => t.agent_id === teamId);
    if (team && [team.agent_id, team.primary_agent_id].includes(id))
      return `${
        team.primary_agent_name ||
        agentsRef.current.find((a) => a.id === team.primary_agent_id)?.name ||
        id
      } · 主持人`;
    return (
      agentsRef.current.find((a) => a.id === id)?.name ||
      teamsRef.current.flatMap((t) => t.members).find((m) => m.agent_id === id)
        ?.name ||
      id
    );
  }
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
  function storedRoom(value: Room) {
    return {
      binding: value.binding,
      conversationId: value.conversationId,
      threadId: value.threadId,
      draft: value.draft,
      queue: value.queue.map((q) => ({
        ...q,
        files: q.files.map(({ preview, ...file }) => file),
      })),
    };
  }
  function restoredRoom(
    old: Partial<Room> | undefined,
    binding: Binding,
  ): Room {
    return {
      ...freshRoom(binding),
      ...(old
        ? {
            conversationId: old.conversationId || crypto.randomUUID(),
            threadId: old.threadId,
            draft: old.draft || "",
            queue: safeQueuedInputs(old.queue),
            queuePaused: true,
          }
        : {}),
    };
  }
  function chooseTeam(teamId: string) {
    const old = roomsRef.current.team;
    if (
      old.busy ||
      old.activeTurnId ||
      old.teamSpeakers.length ||
      old.queue.length ||
      old.approvals.some((a) => ["pending", "submitting"].includes(a.status))
    ) {
      setNotice("请先处理当前团队任务、待发消息或确认，再切换团队。");
      return;
    }
    if (old.binding.agentId === teamId) return;
    if (old.binding.agentId) teamRoomsRef.current[old.binding.agentId] = old;
    const next =
      teamRoomsRef.current[teamId] ||
      freshRoom({ agentId: teamId, connectors: [], knowledgeBases: [] });
    updateRoom("team", next);
    void native("chatClose", { board: "team" });
    if (next.threadId)
      void loadRoomHistory("team").catch((error) =>
        updateRoom("team", { error: errorText(error), queuePaused: true }),
      );
  }
  async function saveTeam(
    name: string,
    memberIds: string[],
    teamId?: string,
  ): Promise<TeamRecord> {
    const owner = ownerRef.current,
      user = userRef.current,
      host = agentsRef.current.find((a) => a.name === "小通" && !a.is_team);
    if (
      !user ||
      !host ||
      memberIds.some(
        (id) => !agentsRef.current.some((a) => a.id === id && !a.is_team),
      )
    )
      throw new Error("请选择本人当前可用的专家，由小通主持。");
    const record = await native<TeamRecord>("saveTeam", {
      name,
      memberIds,
      hostId: host.id,
      ...(teamId ? { teamId } : {}),
    });
    if (ownerRef.current !== owner)
      throw new Error("账号已切换，团队已保存到原账号，请重新核对。");
    setTeams((old) => [
      ...old.filter((t) => t.agent_id !== record.agent_id),
      record,
    ]);
    teamsRef.current = [
      ...teamsRef.current.filter((t) => t.agent_id !== record.agent_id),
      record,
    ];
    try {
      const result = await api("/api/agents");
      if (ownerRef.current !== owner) return record;
      setAgents(markTeams(normalizeAgents(result, user.id), teamsRef.current));
      setTeamsError("");
    } catch {
      setTeamsError("团队已保存，请刷新后核对桌宠授权。");
    }
    if (ownerRef.current === owner) {
      if (
        record.primary_agent_id === host.id &&
        record.primary_agent_name === "小通"
      )
        chooseTeam(record.agent_id);
      else setTeamsError("团队已保存，但主持配置不是小通，请先核对主专家。");
    }
    return record;
  }
  async function loadRoomHistory(id: BoardId) {
    const item = roomsRef.current[id],
      revision = refreshRevision.current,
      owner = loadedOwner.current;
    if (!item.threadId || !item.binding.agentId) return;
    const history = await api<{
      messages: unknown[];
      turn_active?: boolean;
      awaiting_user?: boolean;
      hitl_pending?: unknown;
    }>(
      `/api/agents/${encodeURIComponent(
        item.binding.agentId,
      )}/threads/${encodeURIComponent(item.threadId)}/history?limit=100`,
    );
    if (
      revision !== refreshRevision.current ||
      loadedOwner.current !== owner ||
      roomsRef.current[id].conversationId !== item.conversationId
    )
      return;
    const raw = Array.isArray(history.hitl_pending)
      ? history.hitl_pending
      : [history.hitl_pending];
    const approvals = raw
      .map((value) => pendingApproval(value, item.binding.agentId))
      .filter((a): a is Approval => !!a);
    updateRoom(id, {
      messages: historyMessages(history, item.binding.agentId).map(
        (message) => ({
          ...message,
          speaker:
            message.role === "assistant"
              ? speakerName(
                  message.agentId || item.binding.agentId,
                  id === "team" ? item.binding.agentId : undefined,
                )
              : message.speaker,
        }),
      ),
      teamSpeakers: [],
      approvals,
      busy: !!history.turn_active && !approvals.length,
      awaitingApproval: history.awaiting_user === true && !approvals.length,
      stopping: false,
      cancelSent: false,
      activeTurnId: undefined,
    });
    if (history.turn_active || approvals.length || id === "team") {
      updateRoom(id, { awaitingStatus: true });
      await native(
        "chatSend",
        chatCommand(id, item, { type: "subscribe", thread_id: item.threadId }),
      );
    }
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
        teamRoomsRef.current = {};
        setTeams([]);
        setTeamsError("");
        replaceRooms(emptyRooms());
        setAgents([]);
        setConnectors([]);
        setKnowledge([]);
        voiceDraft.current.owner = null;
      }
      setStatus(next);
      if (next.backendRunning === false)
        setNotice("问答引擎暂未就绪，请重试或在桌宠菜单查看运行日志。");
      if (!next.authenticated || !next.user) {
        loadedOwner.current = null;
        replaceRooms(emptyRooms());
        setAgents([]);
        return;
      }
      const [agentResult, instanceResult, knowledgeResult, teamResult] =
        await Promise.allSettled([
          api("/api/agents"),
          api("/api/connector-instances"),
          api("/api/knowledge-bases"),
          api("/api/teams"),
        ]);
      if (revision !== refreshRevision.current) return;
      if (agentResult.status === "rejected") throw agentResult.reason;
      const foundTeams =
        teamResult.status === "fulfilled"
          ? teamRecords(teamResult.value)
          : teamsRef.current;
      setTeams(foundTeams);
      teamsRef.current = foundTeams;
      setTeamsError(
        teamResult.status === "rejected" ? "团队列表暂不可用，请刷新。" : "",
      );
      const owned = markTeams(
        normalizeAgents(agentResult.value, next.user.id),
        foundTeams,
      );
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
      if (previouslyLoaded) {
        await Promise.all(
          boards.map(async ({ id }) => {
            try {
              await loadRoomHistory(id);
            } catch (error) {
              updateRoom(id, { error: errorText(error), queuePaused: true });
            }
          }),
        );
        return;
      }
      let saved: {
        rooms?: Record<BoardId, Partial<Room>>;
        voice?: boolean;
        active?: BoardId;
        teamSessions?: Record<string, Partial<Room>>;
      } = {};
      try {
        saved = JSON.parse(
          localStorage.getItem(
            settingsKey(next.storageScope ?? next.origin, next.user.id),
          ) || "{}",
        );
      } catch {
        /* Invalid local view preferences do not alter server data. */
      }
      teamRoomsRef.current = Object.fromEntries(
        Object.entries(saved.teamSessions || {}).map(([id, old]) => [
          id,
          restoredRoom(old, {
            agentId: id,
            connectors: [],
            knowledgeBases: [],
          }),
        ]),
      );
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
          return [id, restoredRoom(old, binding)];
        }),
      ) as Rooms;
      loadedOwner.current = nextOwner;
      replaceRooms(restored);
      setVoice(saved.voice ?? true);
      if (boards.some((item) => item.id === saved.active))
        setActive(saved.active!);
      if (knowledgeResult.status === "rejected")
        setNotice("知识库列表暂时不可用，请检查该账号的知识库权限。");
      await Promise.all(
        boards.map(async ({ id }) => {
          const item = restored[id];
          if (!item.threadId || !item.binding.agentId) return;
          try {
            await loadRoomHistory(id);
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
    active,
    teamSessions: Object.fromEntries(
      Object.entries({
        ...teamRoomsRef.current,
        ...(rooms.team.binding.agentId
          ? { [rooms.team.binding.agentId]: rooms.team }
          : {}),
      }).map(([id, value]) => [id, storedRoom(value)]),
    ),
    rooms: Object.fromEntries(
      boards.map(({ id }) => {
        const item = rooms[id];
        return [id, storedRoom(item)];
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
        const [
          agentResult,
          connectionResult,
          knowledgeResult,
          accessResult,
          teamResult,
        ] = await Promise.allSettled([
          api("/api/agents"),
          api("/api/connector-instances"),
          api("/api/knowledge-bases"),
          api<{ allowed: boolean }>("/api/companion/access"),
          api("/api/teams"),
        ]);
        if (!live || ownerRef.current !== owner) return;
        setStatus((value) => ({
          ...value,
          companionAllowed:
            accessResult.status === "fulfilled" &&
            accessResult.value.allowed === true,
        }));
        const latestTeams =
          teamResult.status === "fulfilled"
            ? teamRecords(teamResult.value)
            : teamsRef.current;
        if (teamResult.status === "fulfilled") {
          setTeams(latestTeams);
          teamsRef.current = latestTeams;
          setTeamsError("");
        }
        if (agentResult.status === "fulfilled")
          setAgents(
            markTeams(normalizeAgents(agentResult.value, userId), latestTeams),
          );
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
        teamRoomsRef.current = {};
        teamsRef.current = [];
        setTeams([]);
        void refresh();
        return;
      }
      if (detail.type === "authExpired") {
        teamRoomsRef.current = {};
        teamsRef.current = [];
        setTeams([]);
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
          Object.values(roomsRef.current).some(
            (item) => item.busy || item.teamSpeakers.length,
          )
        )
          void native("petState", { state: "working" });
        return;
      }
      if (detail.type === "focusVoice") {
        inputRef.current?.focus();
        return;
      }
      if (["chatError", "resumeError"].includes(detail.type) && detail.board) {
        if (acceptsRoomEvent(roomsRef.current[detail.board as BoardId], detail))
          updateRoom(detail.board as BoardId, (value) => ({
            ...value,
            busy: detail.type === "chatError" && !!value.approvalStreamActive,
            approvalStreamActive:
              detail.type === "chatError" && value.approvalStreamActive,
            activeTurnId: undefined,
            stopping: false,
            cancelSent: false,
            queuePaused: true,
            approvals: value.approvals.map((a) =>
              a.pending_id === value.resumingId
                ? { ...a, status: "pending", error: detail.error }
                : a,
            ),
            resumingId: undefined,
            error: detail.error || "与专家的连接已断开，请重试。",
          }));
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
      const team =
        id === "team"
          ? teamsRef.current.find((t) => t.agent_id === current.binding.agentId)
          : undefined;
      if (team) {
        const live = liveTeamSpeakers(current.teamSpeakers, frame, team);
        const text =
          frame.type === "done" && frame.team_wrapup
            ? "小通已回复"
            : live.length
            ? frame.team_wrapup
              ? "小通汇总中"
              : "团队成员回复中"
            : frame.type === "done" &&
              String(frame.speaker_agent_id ?? frame.agent_id ?? "") !==
                team.primary_agent_id
            ? "成员已回复"
            : undefined;
        updateRoom(id, {
          teamSpeakers: live,
          ...(text ? { controlStatus: text } : {}),
        });
      }
      if (
        current.resumingId &&
        [
          "token",
          "reasoning",
          "tool_call_chunk",
          "turn.resumed",
          "turn.started",
          "done",
          "hitl_required",
        ].includes(String(frame.type))
      ) {
        updateRoom(id, (value) => ({
          ...value,
          approvals: value.approvals.map((a) =>
            a.pending_id === value.resumingId
              ? {
                  ...a,
                  status: value.resumeRejected ? "rejected" : "approved",
                  error: undefined,
                }
              : a,
          ),
          resumingId: undefined,
        }));
      }
      if (["turn.started", "turn.resumed"].includes(String(frame.type))) {
        updateRoom(id, {
          activeTurnId: String(frame.turn_id || "") || undefined,
          threadId:
            typeof frame.thread_id === "string"
              ? frame.thread_id
              : current.threadId,
          busy: frame.phase !== "hitl_paused",
          awaitingApproval:
            frame.phase === "hitl_paused" &&
            !roomsRef.current[id].approvals.some((a) =>
              ["pending", "submitting"].includes(a.status),
            ),
        });
        return;
      }
      if (frame.type === "turn.ended") {
        if (frame.turn_id && frame.turn_id === current.completedTurnId) return;
        if (
          current.activeTurnId &&
          frame.turn_id &&
          frame.turn_id !== current.activeTurnId
        )
          return;
        updateRoom(id, {
          busy: false,
          awaitingApproval: frame.hitl_paused === true,
          activeTurnId: frame.hitl_paused ? current.activeTurnId : undefined,
          stopping: false,
          cancelSent: false,
          controlStatus: current.stopping
            ? "本轮已结束"
            : current.controlStatus,
        });
        return;
      }
      if (String(frame.type).startsWith("steer.")) {
        if (
          frame.type === "steer.queue_snapshot" &&
          Array.isArray(frame.items)
        ) {
          updateRoom(id, (value) => {
            const messages = [...value.messages];
            for (const item of frame.items as Record<string, unknown>[]) {
              if (
                typeof item.client_pending_id !== "string" ||
                typeof item.pending_id !== "string"
              )
                continue;
              const index = messages.findIndex(
                (m) => m.inputId === item.client_pending_id,
              );
              if (index >= 0)
                messages[index] = {
                  ...messages[index],
                  pendingId: item.pending_id,
                  delivery: "queued",
                };
              else
                messages.push({
                  id: `steer-${item.client_pending_id}`,
                  inputId: item.client_pending_id,
                  pendingId: item.pending_id,
                  role: "user",
                  text: String(item.preview || "已提交的补充"),
                  delivery: "queued",
                  previewOnly: true,
                });
            }
            return { ...value, messages };
          });
        }
        const ids = Array.isArray(frame.client_pending_ids)
          ? frame.client_pending_ids
          : [frame.client_pending_id];
        const failed =
          ["steer.rejected", "steer.expired", "steer.discarded"].includes(
            String(frame.type),
          ) || frame.status === "rejected";
        updateRoom(id, (value) => ({
          ...value,
          messages: value.messages.map((message) =>
            !message.inputId || !ids.includes(message.inputId)
              ? message
              : {
                  ...message,
                  delivery:
                    frame.status === "removed" && frame.already_drained
                      ? "applied"
                      : frame.type === "steer.removed" ||
                        frame.status === "removed"
                      ? "removed"
                      : failed
                      ? "failed"
                      : frame.type === "steer.drained"
                      ? "applied"
                      : "queued",
                  pendingId:
                    typeof frame.pending_id === "string"
                      ? frame.pending_id
                      : message.pendingId,
                  error: failed
                    ? "这条补充未执行，内容已保留，可编辑后再发。"
                    : message.error,
                },
          ),
          queuePaused: failed || value.queuePaused,
          ...(frame.type === "steer.rejected" || frame.status === "rejected"
            ? {
                busy: !!(
                  frame.active_turn_id ||
                  frame.turn_id ||
                  value.activeTurnId
                ),
                activeTurnId:
                  String(
                    frame.active_turn_id ||
                      frame.turn_id ||
                      value.activeTurnId ||
                      "",
                  ) || undefined,
              }
            : {}),
        }));
        if (
          frame.type === "steer.queue_snapshot" &&
          typeof frame.turn_id === "string"
        )
          updateRoom(id, { activeTurnId: frame.turn_id });
        return;
      }
      if (frame.type === "turn_status" && typeof frame.active === "boolean") {
        if (
          !frame.active &&
          (current.approvalStreamActive ||
            (current.busy && !current.stopping && !current.awaitingStatus))
        )
          return;
        updateRoom(id, (value) => ({
          ...value,
          busy: frame.active as boolean,
          awaitingStatus: false,
          ...(!frame.active
            ? {
                activeTurnId: undefined,
                stopping: false,
                cancelSent: false,
                controlStatus: value.stopping
                  ? "本轮已结束"
                  : value.controlStatus,
              }
            : {}),
          messages: frame.active
            ? value.messages
            : value.messages.map((message) => ({ ...message, pending: false })),
        }));
        return;
      }
      const speakerId = String(
        frame.speaker_agent_id ?? frame.agent_id ?? frame.agent ?? "",
      );
      const turnOwner = String(
        frame.turn_owner_agent_id ?? frame.agent_id ?? frame.agent ?? "",
      );
      const finished =
        frame.type === "done" &&
        !frame.team_member_continuing &&
        (!turnOwner ||
          turnOwner === current.binding.agentId ||
          frame.team_wrapup === true);
      if (frame.type === "done")
        updateRoom(id, {
          approvalStreamActive: false,
          ...(current.approvalStreamActive && finished
            ? { completedTurnId: current.activeTurnId, activeTurnId: undefined }
            : {}),
        });
      if (frame.type === "hitl_required") {
        const approval = pendingApproval(
          frame.request,
          current.binding.agentId,
        );
        if (approval)
          updateRoom(id, (value) => ({
            ...value,
            awaitingApproval: false,
            approvalStreamActive: false,
            approvals: [
              ...value.approvals.filter(
                (a) => a.pending_id !== approval.pending_id,
              ),
              approval,
            ],
          }));
        else
          updateRoom(id, {
            awaitingApproval: true,
            error: "确认内容尚未恢复，请刷新任务状态。",
            queuePaused: true,
          });
      }
      if (frame.type === "error")
        updateRoom(id, (value) => ({
          ...value,
          queuePaused: true,
          approvalStreamActive: false,
          activeTurnId: undefined,
          stopping: false,
          cancelSent: false,
          approvals: value.approvals.map((a) =>
            a.pending_id === value.resumingId
              ? {
                  ...a,
                  status: "pending",
                  error: String(
                    frame.message || "确认后未能继续，请刷新核对。",
                  ),
                }
              : a,
          ),
          resumingId: undefined,
        }));
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
        ...(finished
          ? {
              stopping: false,
              cancelSent: false,
              approvalStreamActive: false,
              controlStatus: value.stopping
                ? "本轮已结束"
                : value.controlStatus,
            }
          : {}),
        messages: consumeFrame(
          value.messages,
          frame,
          (agentId) =>
            speakerName(
              agentId,
              id === "team" ? value.binding.agentId : undefined,
            ),
          value.binding.agentId,
        ),
      }));
      if (finished || frame.type === "error")
        void native("petState", {
          state: Object.entries(roomsRef.current).some(
            ([key, value]) =>
              (key !== id && value.busy) || value.teamSpeakers.length > 0,
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

  async function send(
    queued?: QueuedInput,
    delivery: "follow_up" | "steer" = "follow_up",
    id: BoardId = active,
  ) {
    const current = roomsRef.current[id];
    const request = queued || {
      id: crypto.randomUUID(),
      text: current.draft,
      files: current.files,
    };
    const steering = delivery === "steer";
    const user = userRef.current;
    const owner = ownerRef.current;
    if (
      !user ||
      !status.authenticated ||
      status.companionAllowed === false ||
      uploading ||
      (!request.text.trim() && !request.files.length)
    )
      return;
    if (
      !current.binding.agentId ||
      (id !== "knowledge" &&
        id !== "team" &&
        !current.binding.connectors.length)
    ) {
      setShowSettings(true);
      updateRoom(id, {
        error: !current.binding.agentId
          ? "请先选择管理员已开放的专家。"
          : "先选择专家和本人已授权的连接器，再查询业务数据。",
      });
      return;
    }
    if (id === "team") {
      const problem = teamProblem(
        teamsRef.current.find((t) => t.agent_id === current.binding.agentId),
        agentsRef.current,
      );
      if (problem) {
        setShowSettings(true);
        updateRoom(id, { error: problem, queuePaused: true });
        return;
      }
    }
    if (
      !queued &&
      !steering &&
      (current.busy ||
        current.teamSpeakers.length ||
        current.activeTurnId ||
        current.awaitingApproval ||
        current.approvals.some((a) =>
          ["pending", "submitting"].includes(a.status),
        ) ||
        current.queue.length)
    ) {
      updateRoom(id, {
        queue: [...current.queue, request],
        ...(id === "team" ? { queuePaused: true } : {}),
        draft: "",
        files: [],
      });
      return;
    }
    if (
      steering &&
      (!current.busy ||
        !current.threadId ||
        !current.activeTurnId ||
        current.stopping ||
        current.awaitingApproval ||
        current.approvals.some((a) =>
          ["pending", "submitting"].includes(a.status),
        ))
    ) {
      updateRoom(id, { error: "当前不能补充本轮，请加入待发消息。" });
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
      id: request.id,
      role: "user",
      text: request.text,
      attachments: request.files,
      inputId: request.id,
      ...(steering ? { delivery: "pending" as const } : {}),
    };
    updateRoom(id, (value) => ({
      ...value,
      messages: [...value.messages, message],
      ...(!queued ? { draft: "", files: [] } : {}),
      queue: value.queue.filter((item) => item.id !== request.id),
      busy: true,
      error: undefined,
      controlStatus: undefined,
      ...(!steering ? { queuePaused: id === "team" } : {}),
    }));
    void native("stopSpeaking");
    void native("petState", { state: "working" });
    try {
      await native(
        "chatSend",
        chatCommand(id, current, {
          ...turnPayload(
            current.binding,
            sessionKey(
              current.binding.agentId,
              user.id,
              id,
              current.conversationId,
            ),
            request.text,
            request.files,
            current.threadId,
          ),
          delivery,
          client_pending_id: request.id,
          ...(steering ? { expected_turn_id: current.activeTurnId } : {}),
        }),
      );
    } catch (error) {
      if (
        ownerRef.current === owner &&
        roomsRef.current[id].conversationId === current.conversationId
      )
        updateRoom(id, (value) => ({
          ...value,
          busy: steering && value.busy,
          queuePaused: true,
          error: errorText(error),
          draft: value.draft || request.text,
          files: value.files.length ? value.files : request.files,
          messages: value.messages.map((item) =>
            item.id === request.id ? { ...item, delivery: "failed" } : item,
          ),
        }));
    }
  }

  useEffect(() => {
    if (
      !status.authenticated ||
      status.companionAllowed === false ||
      loading ||
      uploading
    )
      return;
    for (const { id } of boards)
      if (canFlushQueue(roomsRef.current[id]))
        void send(roomsRef.current[id].queue[0], "follow_up", id);
  }, [
    rooms,
    status.authenticated,
    status.companionAllowed,
    loading,
    uploading,
  ]);

  async function stop(id: BoardId) {
    const item = roomsRef.current[id],
      owner = ownerRef.current;
    if (!item.threadId || item.cancelSent) return;
    updateRoom(id, { cancelSent: true });
    try {
      await native(
        "chatSend",
        chatCommand(id, item, { type: "cancel", thread_id: item.threadId }),
      );
      for (let attempt = 0; attempt < 20; attempt++) {
        await new Promise((resolve) => setTimeout(resolve, 250));
        if (
          ownerRef.current !== owner ||
          roomsRef.current[id].conversationId !== item.conversationId ||
          !roomsRef.current[id].stopping
        )
          return;
        const value = await api<{ turn_active?: boolean }>(
          `/api/agents/${encodeURIComponent(
            item.binding.agentId,
          )}/threads/${encodeURIComponent(item.threadId)}/history?limit=1`,
        );
        if (
          ownerRef.current !== owner ||
          roomsRef.current[id].conversationId !== item.conversationId
        )
          return;
        if (value.turn_active === false) {
          updateRoom(id, (v) => ({
            ...v,
            busy: false,
            activeTurnId: undefined,
            stopping: false,
            cancelSent: false,
            controlStatus: "本轮已结束",
            messages: v.messages.map((m) => ({ ...m, pending: false })),
          }));
          void native("petState", {
            state: Object.values(roomsRef.current).some(
              (r) => r.busy || r.teamSpeakers.length,
            )
              ? "working"
              : "idle",
          });
          return;
        }
      }
      updateRoom(id, { controlStatus: "停止请求已发送，正在等待任务结束。" });
    } catch (error) {
      if (
        ownerRef.current === owner &&
        roomsRef.current[id].conversationId === item.conversationId
      )
        updateRoom(id, {
          stopping: false,
          cancelSent: false,
          error: errorText(error),
          queuePaused: true,
        });
    }
  }
  useEffect(() => {
    for (const { id } of boards) {
      const value = roomsRef.current[id];
      if (value.stopping && value.threadId && !value.cancelSent) void stop(id);
    }
  }, [rooms]);
  function requestStop() {
    updateRoom(active, (value) => ({
      ...value,
      stopping: true,
      queuePaused: true,
      cancelVersion: (value.cancelVersion || 0) + 1,
      resumingId: undefined,
      approvals: value.approvals.map((a) =>
        a.status === "submitting"
          ? {
              ...a,
              status: "pending",
              error: "本次确认已请求停止，请刷新核对任务状态。",
            }
          : a,
      ),
      controlStatus: "正在停止…",
    }));
    void native("stopSpeaking");
  }
  async function decideApproval(
    approval: Approval,
    decisions: { type: string; message?: string }[],
  ) {
    const id = active,
      item = roomsRef.current[id],
      owner = ownerRef.current;
    if (
      !item.threadId ||
      !approval.pending_id ||
      approval.status !== "pending" ||
      item.approvalStreamActive
    )
      return;
    updateRoom(id, (v) => ({
      ...v,
      busy: true,
      resumingId: approval.pending_id,
      resumeRejected: decisions.some((d) => d.type === "reject"),
      approvalStreamActive: true,
      approvals: v.approvals.map((a) =>
        a.pending_id === approval.pending_id
          ? { ...a, status: "submitting", error: undefined }
          : a,
      ),
    }));
    try {
      await native("resumeApproval", {
        ...chatCommand(id, item, {}),
        threadId: item.threadId,
        pendingId: approval.pending_id,
        decisions,
      });
    } catch (error) {
      if (
        ownerRef.current === owner &&
        roomsRef.current[id].conversationId === item.conversationId &&
        roomsRef.current[id].cancelVersion === item.cancelVersion
      )
        updateRoom(id, (v) => ({
          ...v,
          busy: false,
          resumingId: undefined,
          approvalStreamActive: false,
          queuePaused: true,
          approvals: v.approvals.map((a) =>
            a.pending_id === approval.pending_id
              ? { ...a, status: "pending", error: errorText(error) }
              : a,
          ),
        }));
    }
  }
  function previousInput(message: Message) {
    const index = room.messages.findIndex((m) => m.id === message.id);
    return room.messages
      .slice(0, index + 1)
      .filter((m) => m.role === "user")
      .at(-1);
  }
  function editMessage(message: Message) {
    const input = previousInput(message);
    if (!input) return;
    if (input.previewOnly) {
      setNotice("这条补充只有预览，请先刷新完整会话后再编辑。");
      return;
    }
    if (room.draft.trim() || room.files.length) {
      setNotice("请先发送或清空当前草稿，再编辑历史消息。");
      return;
    }
    updateRoom(active, { draft: input.text, files: input.attachments || [] });
    inputRef.current?.focus();
  }
  function retryMessage(message: Message) {
    const input = previousInput(message);
    if (!input) return;
    if (input.previewOnly) {
      setNotice("这条补充只有预览，请先刷新完整会话后再重发。");
      return;
    }
    const request = {
      id: crypto.randomUUID(),
      text: input.text,
      files: input.attachments || [],
    };
    if (room.queue.length)
      updateRoom(active, { queue: [...room.queue, request] });
    else void send(request);
  }
  async function withdraw(message: Message) {
    const id = active,
      item = roomsRef.current[id],
      owner = ownerRef.current;
    if (
      !item.threadId ||
      !item.activeTurnId ||
      !message.pendingId ||
      !message.inputId
    )
      return;
    try {
      await native(
        "chatSend",
        chatCommand(id, item, {
          type: "steer_remove",
          thread_id: item.threadId,
          turn_id: item.activeTurnId,
          pending_id: message.pendingId,
          client_pending_id: message.inputId,
        }),
      );
    } catch (error) {
      if (
        ownerRef.current === owner &&
        roomsRef.current[id].conversationId === item.conversationId
      )
        updateRoom(id, { error: errorText(error) });
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
    if (uploading) return;
    setUploading(true);
    setNotice("");
    try {
      for (const file of files.slice(0, 4 - current.files.length)) {
        const mime = attachmentMime(file.name, file.type);
        if (!mime || file.size > 12 * 1024 * 1024)
          throw new Error("请选择不超过 12 MB 的图片、Excel、CSV 或 PDF。");
        const base64 = await new Promise<string>((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(String(reader.result).split(",")[1]);
          reader.onerror = reject;
          reader.readAsDataURL(file);
        });
        const uploaded = await native<Attachment>("upload", {
          agentId: current.binding.agentId,
          filename: file.name,
          mimeType: mime,
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
            {
              ...uploaded,
              ...(mime.startsWith("image/")
                ? { preview: `data:${mime};base64,${base64}` }
                : {}),
            },
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
    if (room.busy || room.teamSpeakers.length) return;
    if (
      room.queue.length ||
      room.approvals.some((a) => ["pending", "submitting"].includes(a.status))
    ) {
      setNotice("请先处理待发消息或当前确认，再切换专家和资源。");
      return;
    }
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

  useEffect(() => {
    if (!showSettings) return;
    settingsRef.current?.querySelector<HTMLButtonElement>("button")?.focus();
    void native<{ edgeHiding: boolean }>("petPreferences")
      .then((value) => {
        if (typeof value.edgeHiding === "boolean")
          setEdgeHiding(value.edgeHiding);
      })
      .catch(() => {});
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setShowSettings(false);
        document.querySelector<HTMLButtonElement>(".settings-trigger")?.focus();
      }
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [showSettings]);
  useEffect(() => {
    if (!status.authenticated) setShowSettings(false);
  }, [status.authenticated]);

  function chooseBoard(id: BoardId) {
    if (listening) {
      void native("stopListening");
      setListening(false);
    }
    setActive(id);
    setNotice("");
  }
  function newChat() {
    if (room.teamSpeakers.length) {
      setNotice("团队成员仍在回复，请稍后新建对话。");
      return;
    }
    if (
      room.queue.length ||
      room.approvals.some((a) => ["pending", "submitting"].includes(a.status))
    ) {
      setNotice("请先处理待发消息或当前确认，再新建对话。");
      return;
    }
    void native("chatClose", { board: active });
    updateRoom(active, { ...freshRoom(room.binding), draft: room.draft });
    setShowSettings(false);
  }
  async function openSetting(op: string, args: Record<string, unknown> = {}) {
    try {
      await native(op, args);
      setShowSettings(false);
    } catch (error) {
      setNotice(errorText(error));
      setShowSettings(false);
    }
  }

  return (
    <main
      className={`shell${showSettings ? " settings-open" : ""}`}
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
          <span className="brand-glyph" aria-hidden="true">
            <MessageCircle size={14} strokeWidth={1.7} />
          </span>
          <strong>哆啦</strong>
          <span className="header-divider" aria-hidden="true" />
          <span className="current-board">{board.name}</span>
        </div>
        <button
          className="settings-trigger"
          aria-label={showSettings ? "关闭设置" : "功能与设置"}
          title={showSettings ? "返回聊天" : "功能与设置"}
          onClick={() => {
            if (!showSettings && listening) {
              void native("stopListening");
              setListening(false);
            }
            setShowSettings((value) => !value);
          }}
        >
          {showSettings ? (
            <ChevronLeft size={16} strokeWidth={1.7} />
          ) : (
            <Settings size={16} strokeWidth={1.7} />
          )}
        </button>
      </header>
      <section
        ref={settingsRef}
        className="settings-dialog settings-panel settings-page"
        hidden={!showSettings}
        role="region"
        aria-labelledby="settings-title"
      >
        <div className="section-title">
          <strong id="settings-title">功能与设置</strong>
        </div>
        {status.authenticated && status.companionAllowed !== false && (
          <>
            <nav className="boards" aria-label="选择问答板块">
              {boards.map((item) => (
                <button
                  key={item.id}
                  aria-pressed={item.id === active}
                  className={`board ${item.id} ${
                    item.id === active ? "active" : ""
                  }`}
                  onClick={() => chooseBoard(item.id)}
                >
                  {item.name}
                  {(rooms[item.id].busy ||
                    rooms[item.id].teamSpeakers.length > 0) && (
                    <LoaderCircle size={12} className="spin" />
                  )}
                </button>
              ))}
            </nav>
            {active === "team" ? (
              <TeamSettings
                teams={teams}
                experts={experts}
                selectedId={room.binding.agentId}
                locked={
                  room.busy ||
                  !!room.activeTurnId ||
                  !!room.teamSpeakers.length ||
                  !!room.queue.length ||
                  room.approvals.some((a) =>
                    ["pending", "submitting"].includes(a.status),
                  )
                }
                error={
                  teamsError ||
                  (room.binding.agentId
                    ? teamProblem(selectedTeam, agents) || ""
                    : "")
                }
                onSelect={chooseTeam}
                onSave={saveTeam}
              />
            ) : (
              <>
                <label>
                  回答专家
                  <select
                    aria-label="回答专家"
                    disabled={room.busy}
                    value={room.binding.agentId}
                    onChange={(event) =>
                      changeBinding({
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
                    {chosenAgent?.is_team && (
                      <option value={chosenAgent.id}>
                        {chosenAgent.name}（团队）
                      </option>
                    )}
                    {experts.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name}
                      </option>
                    ))}
                  </select>
                </label>
                <fieldset disabled={room.busy}>
                  <legend>
                    {active === "knowledge" ? "知识库" : "连接器（MCP）"}
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
                              changeBinding({
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
                    {!resourceChoices.length && (
                      <span className="settings-empty">暂无可用资源</span>
                    )}
                  </div>
                </fieldset>
              </>
            )}
            <div className="settings-links">
              <button
                onClick={() =>
                  void openSetting("openOctop", { path: "/experts" })
                }
              >
                创建与管理专家
              </button>
              <button
                onClick={() =>
                  void openSetting("openOctop", { path: "/connectors" })
                }
              >
                接入与管理 MCP
              </button>
              <button
                onClick={() =>
                  void openSetting("openOctop", { path: "/knowledge-bases" })
                }
              >
                管理知识库
              </button>
              <button
                onClick={() =>
                  void openSetting("openOctop", { path: "/models" })
                }
              >
                模型设置
              </button>
            </div>
            <div className="settings-footer">
              <button
                className="text-button"
                disabled={room.busy || uploading}
                onClick={newChat}
              >
                <Plus size={14} />
                新对话
              </button>
              <button
                className="text-button"
                disabled={
                  loading ||
                  Object.values(rooms).some(
                    (item) => item.busy || item.teamSpeakers.length,
                  )
                }
                onClick={() => void refresh()}
              >
                {loading ? "刷新中…" : "刷新资源"}
              </button>
            </div>
          </>
        )}
        <div className="preferences">
          <label>
            自动朗读
            <input
              type="checkbox"
              checked={voice}
              onChange={(event) => {
                setVoice(event.target.checked);
                if (!event.target.checked) void native("stopSpeaking");
              }}
            />
          </label>
          <label>
            边缘收起
            <input
              type="checkbox"
              checked={edgeHiding}
              onChange={(event) => {
                const enabled = event.target.checked;
                setEdgeHiding(enabled);
                void native("setEdgeHiding", { enabled }).catch((error) => {
                  setEdgeHiding(!enabled);
                  setNotice(errorText(error));
                  setShowSettings(false);
                });
              }}
            />
          </label>
          <button onClick={() => void openSetting("petSize")}>宠物大小</button>
          <button onClick={() => void openSetting("help")}>使用说明</button>
        </div>
        <div className="settings-footer">
          <span>{identity}</span>
          {status.authenticated && (
            <button
              className="text-button"
              disabled={Object.values(rooms).some(
                (item) => item.busy || item.teamSpeakers.length,
              )}
              onClick={() => void openSetting("logout")}
            >
              退出账号
            </button>
          )}
        </div>
      </section>
      {!status.authenticated ? (
        <section className="login-state">
          <div className="welcome-orbit">
            <ShieldCheck size={30} />
          </div>
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
        </section>
      ) : status.companionAllowed === false ? (
        <section className="login-state">
          <ShieldCheck size={30} />
          <h1>桌宠尚未开放</h1>
          <p>
            请联系超级管理员，在企业中心的成员名单中为你勾选桌宠。已有聊天和个人配置继续保留。
          </p>
          <button className="primary" onClick={() => void refresh()}>
            重新检查权限
          </button>
        </section>
      ) : (
        <>
          <div
            className="messages"
            ref={scrollRef}
            role="log"
            aria-label={`${board.name}对话`}
            aria-live="polite"
          >
            {room.messages.map((message) => (
              <MessageCard
                key={message.id}
                message={message}
                agentId={room.binding.agentId}
                onResend={() => retryMessage(message)}
                onEdit={() => editMessage(message)}
                onWithdraw={() => void withdraw(message)}
                disabled={
                  room.busy ||
                  !!room.activeTurnId ||
                  room.stopping === true ||
                  room.approvals.some((a) =>
                    ["pending", "submitting"].includes(a.status),
                  )
                }
              />
            ))}
            {room.approvals.map((approval, index) => (
              <ApprovalCard
                key={`${room.conversationId}:${approval.pending_id || index}`}
                approval={approval}
                blocked={
                  !!room.approvalStreamActive && approval.status === "pending"
                }
                onDecision={(decisions) =>
                  void decideApproval(approval, decisions)
                }
                onRefresh={() =>
                  void loadRoomHistory(active).catch((error) =>
                    setNotice(errorText(error)),
                  )
                }
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
        {!!room.queue.length && (
          <div className="queued-inputs" aria-label="待发消息">
            <div>
              <span>
                待发送 {room.queue.length}
                {room.queuePaused ? " · 已暂停" : ""}
              </span>
              {room.queuePaused && !room.busy && (
                <button
                  onClick={() =>
                    updateRoom(active, {
                      queuePaused: false,
                      error: undefined,
                      controlStatus: undefined,
                    })
                  }
                >
                  继续发送
                </button>
              )}
            </div>
            {room.queue.map((item, index) => (
              <div className="queued-input" key={item.id}>
                <span title={item.text}>
                  {item.text || item.files.map((f) => f.filename).join("、")}
                </span>
                {room.busy && room.activeTurnId && !room.stopping && (
                  <button onClick={() => void send(item, "steer")}>
                    补充本轮
                  </button>
                )}
                <button
                  aria-label={`撤回待发消息 ${index + 1}`}
                  onClick={() =>
                    updateRoom(active, {
                      queue: room.queue.filter((q) => q.id !== item.id),
                    })
                  }
                >
                  <X size={12} />
                </button>
              </div>
            ))}
          </div>
        )}
        {room.controlStatus && (
          <div className="control-status" role="status">
            {room.controlStatus}
          </div>
        )}
        <div className="attachment-strip">
          {room.files.map((item, index) => (
            <div key={`${item.path}-${index}`}>
              {item.preview ? (
                <img src={item.preview} alt={item.filename} />
              ) : (
                <span className="file-chip">{item.filename}</span>
              )}
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
          placeholder={status.authenticated ? "输入消息…" : "登录后开始提问"}
          value={room.draft}
          disabled={
            !status.authenticated ||
            status.companionAllowed === false ||
            loading
          }
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
              aria-label="添加附件"
              title="图片、Excel、CSV、PDF，也可拖入或粘贴"
              disabled={
                !status.authenticated ||
                status.companionAllowed === false ||
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
              disabled={
                !status.authenticated || status.companionAllowed === false
              }
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
                : ""}
            </span>
          </div>
          <div className="send-actions">
            {room.busy && (
              <button
                className="send stop"
                aria-label={room.stopping ? "正在停止" : "停止回答"}
                title={
                  active === "team"
                    ? "停止主持人本轮生成；已开始的成员回复仍会继续接收"
                    : "停止回答"
                }
                disabled={room.stopping}
                onClick={requestStop}
              >
                <Square size={15} />
              </button>
            )}
            {room.busy && (room.draft.trim() || room.files.length > 0) && (
              <button
                className="steer-button"
                disabled={
                  !room.activeTurnId ||
                  room.stopping ||
                  room.approvals.some((a) =>
                    ["pending", "submitting"].includes(a.status),
                  )
                }
                onClick={() => void send(undefined, "steer")}
              >
                补充本轮
              </button>
            )}
            <>
              <button
                className="send"
                aria-label={
                  room.busy ||
                  room.teamSpeakers.length > 0 ||
                  room.queue.length ||
                  room.approvals.some((a) =>
                    ["pending", "submitting"].includes(a.status),
                  )
                    ? "排队发送"
                    : "发送消息"
                }
                disabled={
                  !status.authenticated ||
                  status.companionAllowed === false ||
                  uploading ||
                  listening ||
                  (!room.draft.trim() && !room.files.length)
                }
                onClick={() => void send()}
              >
                <ArrowUp size={18} />
              </button>
            </>
          </div>
        </div>
        <input
          ref={fileRef}
          type="file"
          accept="image/png,image/jpeg,image/webp,image/gif,.xlsx,.xls,.csv,.pdf"
          multiple
          hidden
          onChange={(event) => {
            void addFiles([...(event.target.files || [])]);
            event.target.value = "";
          }}
        />
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
