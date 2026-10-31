import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";
import { App, Button, Dropdown, Space, Tag, Typography } from "antd";
import {
  CommentOutlined,
  InboxOutlined,
  MessageOutlined,
  RollbackOutlined,
  SmileOutlined,
  CloseOutlined,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import {
  conversationsApi,
  type MessageLocator,
  type QuoteDraft,
  type Reaction,
  type QuotedMessage,
  type SideQuestion,
} from "../../api/modules/conversations";
import { apiErrorMessage } from "../../utils/apiError";
import { SideQuestionDrawer } from "./SideQuestionDrawer";

const allowed = ["👍", "❤️", "🎉", "💡", "🤔", "👎"];
const ReactionContext = createContext<{
  rows: Reaction[];
  update: (rows: Reaction[]) => void;
  agentId?: string | null;
  threadId?: string | null;
  onQuote?: (draft: QuoteDraft) => void;
} | null>(null);

export function ConversationAnnotations({
  threadId,
  children,
  agentId,
  onQuote,
}: {
  threadId?: string | null;
  children: ReactNode;
  agentId?: string | null;
  onQuote?: (draft: QuoteDraft) => void;
}) {
  const [rows, update] = useState<Reaction[]>([]);
  useEffect(() => {
    let active = true;
    update([]);
    if (threadId)
      void conversationsApi
        .annotations(threadId)
        .then((data) => {
          if (active) update(data.reactions);
        })
        .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [threadId]);
  const value = useMemo(
    () => ({ rows, update, agentId, threadId, onQuote }),
    [rows, agentId, threadId, onQuote],
  );
  return (
    <ReactionContext.Provider value={value}>
      {children}
    </ReactionContext.Provider>
  );
}

export function ScopedMessageActions({
  messageId,
  role,
  content,
}: {
  messageId?: string;
  role: "user" | "assistant";
  content: string;
}) {
  const scope = useContext(ReactionContext);
  if (!scope?.agentId || !scope.threadId) return null;
  return (
    <ChatMessageActions
      agentId={scope.agentId}
      threadId={scope.threadId}
      messageId={messageId}
      role={role}
      content={content}
      onQuote={scope.onQuote}
    />
  );
}

export function QuotedReplyExcerpt({ quote }: { quote: QuotedMessage }) {
  const { t } = useTranslation();
  return (
    <blockquote
      style={{
        margin: "0 0 6px",
        borderInlineStart: "3px solid var(--ant-color-primary)",
        paddingInlineStart: 8,
        opacity: 0.85,
        fontSize: 12,
      }}
    >
      <Typography.Text ellipsis={{ tooltip: quote.content }}>
        {t("conversationLibrary.quoting")}{" "}
        {quote.speaker_name || t(`conversationLibrary.role.${quote.role}`)}:{" "}
        {quote.content.slice(0, 200)}
      </Typography.Text>
    </blockquote>
  );
}

export function QuotedReplyDraft({
  draft,
  onClear,
}: {
  draft: QuoteDraft;
  onClear: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div
      style={{
        borderInlineStart: "3px solid var(--ant-color-primary)",
        padding: "4px 8px",
        display: "flex",
        gap: 8,
        alignItems: "center",
        fontSize: 12,
      }}
    >
      <CommentOutlined />
      <Typography.Text ellipsis style={{ flex: 1 }}>
        {t("conversationLibrary.quoting")}{" "}
        {draft.resolved.speaker_name || draft.resolved.role}:{" "}
        {draft.resolved.content.slice(0, 300)}
      </Typography.Text>
      <Button
        type="text"
        size="small"
        icon={<CloseOutlined />}
        aria-label={t("conversationLibrary.clearQuote")}
        onClick={onClear}
      />
    </div>
  );
}

export function ChatConversationActions({
  threadId,
  archived = false,
  onArchived,
}: {
  threadId?: string | null;
  archived?: boolean;
  onArchived?: (archived: boolean) => void;
}) {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const [busy, setBusy] = useState(false);
  if (!threadId) return null;
  return (
    <Button
      size="small"
      type="text"
      loading={busy}
      icon={archived ? <RollbackOutlined /> : <InboxOutlined />}
      onClick={async () => {
        setBusy(true);
        try {
          await conversationsApi.archive(threadId, !archived);
          onArchived?.(!archived);
          message.success(
            t(
              archived
                ? "conversationLibrary.restored"
                : "conversationLibrary.archived",
            ),
          );
        } catch (error) {
          message.error(
            apiErrorMessage(error, t("conversationLibrary.actionFailed"), t),
          );
        } finally {
          setBusy(false);
        }
      }}
    >
      {t(
        archived
          ? "conversationLibrary.restore"
          : "conversationLibrary.archive",
      )}
    </Button>
  );
}

export function ChatMessageActions({
  agentId,
  threadId,
  messageId,
  role,
  content,
  ordinalFromEnd,
  onQuote,
}: {
  agentId: string;
  threadId: string;
  messageId?: string;
  role: "user" | "assistant";
  content: string;
  ordinalFromEnd?: number;
  onQuote?: (draft: QuoteDraft) => void;
}) {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const shared = useContext(ReactionContext);
  const [localRows, setLocalRows] = useState<Reaction[]>([]);
  const [canonicalKey, setCanonicalKey] = useState(messageId);
  const [digest, setDigest] = useState("");
  const [busy, setBusy] = useState(false);
  const [side, setSide] = useState<SideQuestion | null>(null);
  const [sideOpen, setSideOpen] = useState(false);
  const activeThread = useRef(threadId);
  activeThread.current = threadId;
  const locator: MessageLocator = {
    message_id: messageId,
    role,
    content,
    ordinal_from_end: ordinalFromEnd,
  };
  useEffect(() => {
    setCanonicalKey(messageId);
    setLocalRows([]);
    setSide(null);
    setSideOpen(false);
  }, [threadId, messageId]);
  useEffect(() => {
    let active = true;
    if (globalThis.crypto?.subtle)
      void crypto.subtle
        .digest("SHA-256", new TextEncoder().encode(`${role}\0${content}`))
        .then((buffer) => {
          if (active)
            setDigest(
              Array.from(new Uint8Array(buffer), (byte) =>
                byte.toString(16).padStart(2, "0"),
              ).join(""),
            );
        });
    return () => {
      active = false;
    };
  }, [role, content]);
  const rows = shared?.rows ?? localRows;
  const reactions = rows.filter(
    (row) =>
      row.message_key === canonicalKey ||
      (row.message_key === `content:${digest}` &&
        digest &&
        row.message_digest === digest &&
        row.message_role === role),
  );
  const run = useCallback(
    async (action: () => Promise<void>) => {
      setBusy(true);
      try {
        await action();
      } catch (error) {
        message.error(
          apiErrorMessage(error, t("conversationLibrary.actionFailed"), t),
        );
      } finally {
        setBusy(false);
      }
    },
    [message, t],
  );
  return (
    <>
      <Space size={2} wrap>
        <Dropdown
          trigger={["click"]}
          menu={{
            items: allowed.map((emoji) => ({
              key: emoji,
              label: (
                <span>
                  {emoji}{" "}
                  {reactions.some((row) => row.emoji === emoji) ? "✓" : ""}
                </span>
              ),
            })),
            onClick: ({ key }) =>
              void run(async () => {
                const result = await conversationsApi.react(
                  threadId,
                  locator,
                  key,
                  !reactions.some((row) => row.emoji === key),
                );
                if (activeThread.current !== threadId) return;
                setCanonicalKey(result.message_key);
                (shared?.update ?? setLocalRows)(result.reactions);
              }),
          }}
        >
          <Button
            type="text"
            size="small"
            disabled={busy}
            icon={<SmileOutlined />}
            aria-label={t("conversationLibrary.react")}
          />
        </Dropdown>
        {onQuote && (
          <Button
            type="text"
            size="small"
            disabled={busy}
            icon={<CommentOutlined />}
            aria-label={t("conversationLibrary.quote")}
            onClick={() =>
              void run(async () => {
                const resolved = await conversationsApi.resolve(
                  threadId,
                  locator,
                );
                if (activeThread.current === threadId)
                  onQuote({
                    reference: {
                      source_thread_id: threadId,
                      message: { ...locator, message_id: resolved.message_key },
                    },
                    resolved,
                  });
              })
            }
          />
        )}
        {role === "assistant" && content && (
          <Button
            type="text"
            size="small"
            disabled={busy}
            icon={<MessageOutlined />}
            aria-label={t("conversationLibrary.sideQuestion")}
            onClick={() =>
              void run(async () => {
                const branch =
                  side ?? (await conversationsApi.side(threadId, locator));
                if (activeThread.current === threadId) {
                  setSide(branch);
                  setSideOpen(true);
                }
              })
            }
          />
        )}
        {reactions.map((row) => (
          <Tag key={row.emoji} style={{ marginInlineEnd: 2 }}>
            {row.emoji}
          </Tag>
        ))}
      </Space>
      {side && (
        <SideQuestionDrawer
          branch={{ ...side, agent_id: agentId }}
          open={sideOpen}
          onClose={() => setSideOpen(false)}
        />
      )}
    </>
  );
}
