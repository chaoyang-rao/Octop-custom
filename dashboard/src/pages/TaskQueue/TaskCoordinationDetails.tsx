import { useEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  Checkbox,
  Form,
  Input,
  Space,
  Tag,
  Typography,
} from "antd";
import { useTranslation } from "react-i18next";
import type {
  CoordinationContinue,
  TaskCoordination,
} from "../../api/modules/tasks";
import { coordinationStatus, taskActionError } from "./dispatchPresentation";

export function CoordinationStatusTag({ scope }: { scope: TaskCoordination }) {
  const { t } = useTranslation();
  const status = coordinationStatus(scope);
  return <Tag color={status.color}>{t(status.key)}</Tag>;
}

interface Props {
  scope: TaskCoordination;
  isCoding: boolean;
  onContinue?: (body: CoordinationContinue) => Promise<void>;
  onStop?: () => Promise<void>;
}

export default function TaskCoordinationDetails({
  scope,
  isCoding,
  onContinue,
  onStop,
}: Props) {
  const { t } = useTranslation();
  const [form] = Form.useForm();
  const [pendingAction, setPendingAction] = useState<
    "continue" | "stop" | null
  >(null);
  const busy = pendingAction !== null;
  const [error, setError] = useState<string | null>(null);
  const [allowPublish, setAllowPublish] = useState(
    scope.allow_publish === true,
  );
  const canContinue =
    scope.state === "needs_user" || scope.state === "interrupted";
  const canStop =
    ["pending", "running", "needs_user", "interrupted"].includes(scope.state) ||
    (scope.state === "idle" && scope.decision === "continue");
  const currentPublish = useRef(scope.allow_publish === true);
  currentPublish.current = scope.allow_publish === true;
  useEffect(() => {
    if (canContinue) setAllowPublish(currentPublish.current);
  }, [canContinue, isCoding, scope.scope_id]);
  const question =
    typeof scope.question === "string" ? scope.question.trim() : "";
  const summary = typeof scope.summary === "string" ? scope.summary.trim() : "";
  const submit = async ({ prompt }: { prompt: string }) => {
    if (!onContinue) return;
    setPendingAction("continue");
    setError(null);
    try {
      await onContinue({
        prompt: prompt.trim(),
        ...(isCoding ? { allow_publish: allowPublish } : {}),
      });
      form.resetFields();
    } catch (error) {
      setError(taskActionError(error, t));
    } finally {
      setPendingAction(null);
    }
  };
  const stop = async () => {
    if (!onStop || busy) return;
    setPendingAction("stop");
    setError(null);
    try {
      await onStop();
    } catch (error) {
      setError(taskActionError(error, t));
    } finally {
      setPendingAction(null);
    }
  };
  return (
    <Space direction="vertical" size={10} style={{ width: "100%" }}>
      <Space wrap>
        <Typography.Title level={5} style={{ margin: 0 }}>
          {t("taskQueue.coordinationTitle")}
        </Typography.Title>
        <CoordinationStatusTag scope={scope} />
        {scope.room?.agent_id && scope.room?.thread_id && (
          <Button
            size="small"
            href={`/chat/${encodeURIComponent(
              scope.room.agent_id,
            )}/${encodeURIComponent(scope.room.thread_id)}`}
            title={t("taskQueue.taskRoomHint")}
          >
            {t("taskQueue.openTaskRoom")}
          </Button>
        )}
        {canStop && onStop && (
          <Button
            size="small"
            danger
            disabled={busy}
            loading={pendingAction === "stop"}
            title={t("taskQueue.coordinationStopHint")}
            onClick={() => void stop()}
          >
            {t("taskQueue.coordinationStop")}
          </Button>
        )}
      </Space>
      {summary && (
        <Typography.Paragraph
          style={{
            whiteSpace: "pre-wrap",
            overflowWrap: "anywhere",
            margin: 0,
          }}
        >
          {summary}
        </Typography.Paragraph>
      )}
      {question && scope.state !== "stopped" && (
        <Alert
          type={canContinue ? "warning" : "info"}
          message={question}
          style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}
        />
      )}
      {error && <Alert type="error" message={error} />}
      {canContinue && onContinue && (
        <Form
          form={form}
          layout="vertical"
          onFinish={(values: { prompt: string }) => void submit(values)}
          style={{ width: "100%" }}
        >
          <Form.Item
            name="prompt"
            label={t("taskQueue.coordinationInput")}
            extra={t("taskQueue.coordinationContinueHint")}
            rules={[{ required: true, whitespace: true, max: 32000 }]}
          >
            <Input.TextArea
              rows={3}
              disabled={busy}
              onChange={() => setError(null)}
            />
          </Form.Item>
          {isCoding && (
            <Form.Item extra={t("taskQueue.coordinationPublishHint")}>
              <Checkbox
                checked={allowPublish}
                disabled={busy}
                onChange={(event) => setAllowPublish(event.target.checked)}
              >
                {t("taskQueue.coordinationAllowPublish")}
              </Checkbox>
            </Form.Item>
          )}
          <Button
            htmlType="submit"
            type="primary"
            disabled={busy}
            loading={pendingAction === "continue"}
          >
            {t("taskQueue.coordinationContinue")}
          </Button>
        </Form>
      )}
    </Space>
  );
}
