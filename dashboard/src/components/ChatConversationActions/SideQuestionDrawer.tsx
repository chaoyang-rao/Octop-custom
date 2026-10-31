import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  Collapse,
  Drawer,
  Input,
  Space,
  Typography,
} from "antd";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import {
  conversationsApi,
  type SideQuestion,
} from "../../api/modules/conversations";
import { buildDashboardChatWsUrl } from "../../api/modules/wsChat";
import { apiErrorMessage } from "../../utils/apiError";

type Reply = { role: "user" | "assistant"; text: string };
type Approval = {
  pending_id?: string;
  action_requests?: unknown[];
  [key: string]: unknown;
};

/** Independent WS consumer; deliberately does not import the primary chat store. */
export function SideQuestionDrawer({
  branch,
  open,
  onClose,
}: {
  branch: SideQuestion;
  open: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState("");
  const [replies, setReplies] = useState<Reply[]>([]);
  const [busy, setBusy] = useState(false);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState("");
  const [approval, setApproval] = useState<Approval | null>(null);
  const socket = useRef<WebSocket | null>(null);
  const live = useRef(true);
  const receive = useCallback(
    (data: Record<string, unknown>) => {
      if (data.thread_id && data.thread_id !== branch.thread_id) return;
      if (data.type === "token" && typeof data.content === "string")
        setReplies((rows) => {
          const last = rows[rows.length - 1];
          return last?.role === "assistant"
            ? [
                ...rows.slice(0, -1),
                { role: "assistant", text: last.text + data.content },
              ]
            : [...rows, { role: "assistant", text: data.content as string }];
        });
      if (data.type === "hitl_required") {
        const request =
          data.request && typeof data.request === "object"
            ? (data.request as Approval)
            : {};
        setApproval({
          ...request,
          pending_id:
            typeof data.pending_id === "string"
              ? data.pending_id
              : request.pending_id,
        });
        setBusy(false);
      }
      if (data.type === "error") {
        setError(
          String(
            data.message || data.content || t("conversationLibrary.sideFailed"),
          ),
        );
        setBusy(false);
      }
      if (data.type === "turn.ended") setBusy(false);
    },
    [branch.thread_id, t],
  );
  useEffect(() => {
    if (!open || socket.current) return;
    live.current = true;
    const ws = new WebSocket(buildDashboardChatWsUrl(branch.agent_id));
    socket.current = ws;
    ws.onopen = () => {
      setConnected(true);
      ws.send(
        JSON.stringify({ type: "subscribe", thread_id: branch.thread_id }),
      );
    };
    ws.onmessage = (event) => {
      try {
        receive(JSON.parse(String(event.data)) as Record<string, unknown>);
      } catch {
        /* Ignore non-JSON keepalive frames. */
      }
    };
    ws.onerror = () => setError(t("conversationLibrary.connectionFailed"));
    ws.onclose = () => {
      socket.current = null;
      if (live.current) {
        setConnected(false);
        setBusy(false);
      }
    };
  }, [open, branch.agent_id, branch.thread_id, receive, t]);
  useEffect(
    () => () => {
      live.current = false;
      socket.current?.close();
      socket.current = null;
    },
    [branch.thread_id],
  );
  const send = () => {
    if (!draft.trim() || !socket.current || !connected || busy || approval)
      return;
    const text = draft.trim();
    socket.current.send(
      JSON.stringify({
        type: "user_turn",
        text,
        thread_id: branch.thread_id,
        session_key: branch.session_key,
        conversation_mode: "ask",
        delivery: "follow_up",
      }),
    );
    setReplies((rows) => [...rows, { role: "user", text }]);
    setDraft("");
    setBusy(true);
    setError("");
  };
  const decide = async (type: "approve" | "reject") => {
    if (!approval) return;
    setBusy(true);
    setError("");
    try {
      const count = Math.max(1, approval.action_requests?.length || 0);
      const result = await conversationsApi.resumeSide(
        branch.agent_id,
        branch.thread_id,
        approval.pending_id,
        Array.from({ length: count }, () => ({ type })),
      );
      setApproval(null);
      const reader = result.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder
            .decode(value, { stream: true })
            .replace(/\r\n/g, "\n");
          let end;
          while ((end = buffer.indexOf("\n\n")) >= 0) {
            const event = buffer.slice(0, end);
            buffer = buffer.slice(end + 2);
            const raw = event
              .split("\n")
              .filter((line) => line.startsWith("data:"))
              .map((line) => line.slice(5).trimStart())
              .join("\n");
            if (raw) {
              try {
                receive(JSON.parse(raw) as Record<string, unknown>);
              } catch {
                /* SSE comments carry no JSON. */
              }
            }
          }
        }
      } finally {
        reader.releaseLock();
      }
    } catch (reason) {
      setError(
        apiErrorMessage(reason, t("conversationLibrary.actionFailed"), t),
      );
    } finally {
      setBusy(false);
    }
  };
  return (
    <Drawer
      title={t("conversationLibrary.sideQuestion")}
      open={open}
      onClose={onClose}
      width={520}
    >
      <Space direction="vertical" style={{ width: "100%" }}>
        <Alert
          type="info"
          showIcon
          message={t("conversationLibrary.sideHint", {
            count: branch.copied_messages,
          })}
        />
        <Link
          to={`/chat/${encodeURIComponent(
            branch.agent_id,
          )}/${encodeURIComponent(branch.thread_id)}`}
        >
          {t("conversationLibrary.openBranch")}
        </Link>
        {replies.map((reply, index) => (
          <div
            key={index}
            style={{
              padding: "8px 12px",
              borderRadius: 10,
              background:
                reply.role === "user"
                  ? "var(--ant-color-primary-bg)"
                  : "var(--ant-color-fill-quaternary)",
              whiteSpace: "pre-wrap",
              overflowWrap: "anywhere",
            }}
          >
            <Typography.Text type="secondary">
              {t(`conversationLibrary.role.${reply.role}`)}
            </Typography.Text>
            <div>{reply.text}</div>
          </div>
        ))}
        {error && <Alert type="error" message={error} />}
        {approval && (
          <Alert
            type="warning"
            message={t("conversationLibrary.approvalRequired")}
            description={
              <Space direction="vertical" style={{ width: "100%" }}>
                <Collapse
                  size="small"
                  items={[
                    {
                      key: "approval",
                      label: t("conversationLibrary.approvalDetails"),
                      children: (
                        <pre
                          style={{
                            whiteSpace: "pre-wrap",
                            maxHeight: 240,
                            overflow: "auto",
                          }}
                        >
                          {JSON.stringify(
                            approval.action_requests || approval,
                            null,
                            2,
                          )}
                        </pre>
                      ),
                    },
                  ]}
                />
                <Space>
                  <Button
                    disabled={busy}
                    onClick={() => void decide("approve")}
                  >
                    {t("conversationLibrary.approve")}
                  </Button>
                  <Button disabled={busy} onClick={() => void decide("reject")}>
                    {t("conversationLibrary.reject")}
                  </Button>
                </Space>
              </Space>
            }
          />
        )}
        <Input.TextArea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          autoSize={{ minRows: 2, maxRows: 6 }}
          placeholder={t("conversationLibrary.sidePlaceholder")}
          onKeyDown={(event) => {
            if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
              event.preventDefault();
              send();
            }
          }}
        />
        <Button
          type="primary"
          loading={busy}
          disabled={!connected || !draft.trim() || Boolean(approval)}
          onClick={send}
        >
          {t("conversationLibrary.send")}
        </Button>
      </Space>
    </Drawer>
  );
}
