import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  App,
  Button,
  Drawer,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  Typography,
  Upload,
} from "antd";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { useAgent } from "../../context/AgentContext";
import {
  taskQueueApi,
  type QueuedTask,
  type TaskAttachment,
  type TaskAction,
  type TaskDetail,
  type TaskWorkflow,
  type WorkflowDefinition,
  type WorkflowRun,
  type WorkflowStep,
} from "../../api/modules/tasks";
import { uploadApi } from "../../api/modules/upload";
import { useServerUploadLimit } from "../../hooks/useServerUploadLimit";
import { useServerTimezone } from "../../hooks/useServerTimezone";
import { formatServerDateTime } from "../../utils/formatMessageTime";
import { workflowGraphError } from "./workflowValidation";
import { saveBlobAsFile } from "../../utils/saveBlobAsFile";
import { apiErrorMessage, parseApiError } from "../../utils/apiError";

const terminal = new Set(["completed", "failed", "cancelled", "interrupted"]);
const stateColors: Record<string, string> = {
  queued: "blue",
  running: "processing",
  waiting: "warning",
  completed: "success",
  failed: "error",
  interrupted: "warning",
};
type StepDraft = WorkflowStep;

/** Embeddable user automation surface; the existing cron screen can remain a sibling tab. */
export default function TaskQueue() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { message } = App.useApp();
  const { agents } = useAgent();
  const timeZone = useServerTimezone();
  const owned = useMemo(
    () => agents.filter((agent) => agent.is_owner && !agent.bridge),
    [agents],
  );
  const agentOptions = owned.map((agent) => ({
    value: agent.agent_id,
    label: agent.name,
  }));
  const agentName = (id: string) =>
    owned.find((agent) => agent.agent_id === id)?.name ?? id;
  const refreshVersion = useRef(0);
  const refreshing = useRef(false);
  const [tasks, setTasks] = useState<QueuedTask[]>([]);
  const [workflows, setWorkflows] = useState<TaskWorkflow[]>([]);
  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const [controls, setControls] = useState<Record<string, boolean>>({});
  const [archived, setArchived] = useState(false);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<TaskDetail | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [workflowOpen, setWorkflowOpen] = useState(false);
  const [editing, setEditing] = useState<TaskWorkflow | null>(null);
  const [webhook, setWebhook] = useState<{
    token: string | null;
    path: string;
  } | null>(null);
  const [calendarPath, setCalendarPath] = useState<string | null>(null);
  const [form] = Form.useForm();
  const [workflowForm] = Form.useForm();
  const uploadAgent = Form.useWatch("agent_id", form) as string | undefined;
  const { maxUploadBytes: uploadLimit } = useServerUploadLimit();
  const [attachments, setAttachments] = useState<TaskAttachment[]>([]);
  const [uploading, setUploading] = useState(0);
  useEffect(() => setAttachments([]), [uploadAgent]);
  const showError = useCallback(
    (error: unknown) => {
      const reason = parseApiError(error)?.details?.task_reason;
      message.error(
        typeof reason === "string"
          ? t(`taskQueue.errors.${reason}`, t("taskQueue.failed"))
          : apiErrorMessage(error, t("taskQueue.failed"), t),
      );
    },
    [message, t],
  );
  const refresh = useCallback(
    async (quiet = false) => {
      if (quiet && refreshing.current) return;
      const version = ++refreshVersion.current;
      refreshing.current = true;
      if (!quiet) setLoading(true);
      try {
        const [next, definitions, history, paused] = await Promise.all([
          taskQueueApi.list(archived),
          taskQueueApi.workflows(),
          taskQueueApi.runs(),
          taskQueueApi.controls(),
        ]);
        if (version !== refreshVersion.current) return;
        setTasks(next);
        setWorkflows(definitions);
        setRuns(history);
        setControls(paused);
      } catch (error) {
        if (!quiet && version === refreshVersion.current) showError(error);
      } finally {
        if (version === refreshVersion.current) {
          refreshing.current = false;
          if (!quiet) setLoading(false);
        }
      }
    },
    [archived, showError],
  );
  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(true), 4000);
    return () => {
      refreshVersion.current++;
      refreshing.current = false;
      window.clearInterval(timer);
    };
  }, [refresh]);
  const act = async (task: QueuedTask, action: TaskAction, target?: string) => {
    setBusy(true);
    try {
      await taskQueueApi.action(task.id, action, target);
      await refresh(true);
    } catch (error) {
      showError(error);
    } finally {
      setBusy(false);
    }
  };
  const details = async (task: QueuedTask) => {
    try {
      setSelected(await taskQueueApi.detail(task.id));
    } catch (error) {
      showError(error);
    }
  };
  const editWorkflow = (workflow?: TaskWorkflow) => {
    setEditing(workflow ?? null);
    workflowForm.setFieldsValue(
      workflow
        ? {
            name: workflow.name,
            steps: workflow.definition.steps,
            enabled: workflow.enabled,
            schedule: workflow.definition.schedule ?? "",
            failure_policy: workflow.definition.failure_policy ?? "pause",
            notify_policy: workflow.definition.quiet ? "failure" : "always",
          }
        : {
            name: "",
            enabled: true,
            schedule: "",
            failure_policy: "pause",
            notify_policy: "always",
            steps: [
              {
                key: "step1",
                title: "",
                agent_id: owned[0]?.agent_id,
                prompt: "",
                depends_on: [],
              },
            ],
          },
    );
    setWorkflowOpen(true);
  };
  const saveWorkflow = async () => {
    let values;
    try {
      values = await workflowForm.validateFields();
    } catch {
      return;
    }
    const graphError = workflowGraphError(values.steps as WorkflowStep[]);
    if (graphError) {
      message.error(t(`taskQueue.${graphError}`));
      return;
    }
    setBusy(true);
    try {
      await taskQueueApi.saveWorkflow(
        {
          name: values.name,
          enabled: values.enabled,
          definition: {
            steps: values.steps,
            schedule: values.schedule || null,
            failure_policy: values.failure_policy,
            quiet: values.notify_policy === "failure",
          } as WorkflowDefinition,
        },
        editing?.id,
      );
      setWorkflowOpen(false);
      await refresh(true);
    } catch (error) {
      showError(error);
    } finally {
      setBusy(false);
    }
  };
  const createTask = async () => {
    let values;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    setBusy(true);
    try {
      const { notify_policy, ...body } = values;
      await taskQueueApi.create({
        ...body,
        options: { quiet: notify_policy === "failure" },
        ...(attachments.length ? { attachments } : {}),
      });
      setCreateOpen(false);
      form.resetFields();
      setAttachments([]);
      await refresh(true);
    } catch (error) {
      showError(error);
    } finally {
      setBusy(false);
    }
  };
  const runWorkflow = async (workflow: TaskWorkflow) => {
    setBusy(true);
    try {
      await taskQueueApi.runWorkflow(workflow.id);
      await refresh(true);
    } catch (error) {
      showError(error);
    } finally {
      setBusy(false);
    }
  };
  const rotateWebhook = async (workflow: TaskWorkflow, enabled: boolean) => {
    try {
      const result = await taskQueueApi.webhook(workflow.id, enabled);
      if (enabled) setWebhook(result);
      await refresh(true);
    } catch (error) {
      showError(error);
    }
  };
  const status = (state: string) => (
    <Tag color={stateColors[state]}>
      {t(`taskQueue.states.${state}`, state)}
    </Tag>
  );
  const formatTime = (timestamp: number) =>
    formatServerDateTime(timestamp, timeZone);
  const taskTable = (
    <Table<QueuedTask>
      rowKey="id"
      dataSource={tasks}
      loading={loading}
      size="small"
      pagination={{ pageSize: 15 }}
      scroll={{ x: 780 }}
      columns={[
        {
          title: t("taskQueue.name"),
          dataIndex: "title",
          render: (_, task) => (
            <Button type="link" onClick={() => void details(task)}>
              {task.title}
            </Button>
          ),
        },
        {
          title: t("taskQueue.expert"),
          dataIndex: "agent_id",
          render: agentName,
        },
        { title: t("taskQueue.status"), dataIndex: "state", render: status },
        {
          title: t("taskQueue.created"),
          dataIndex: "created_at",
          render: formatTime,
        },
        {
          title: t("taskQueue.actions"),
          render: (_, task) => (
            <Space wrap size={4}>
              {task.state === "queued" && (
                <Button
                  size="small"
                  disabled={busy}
                  onClick={() => void act(task, "pause")}
                >
                  {t("taskQueue.pause")}
                </Button>
              )}
              {task.state === "paused" && (
                <Button
                  size="small"
                  disabled={busy}
                  onClick={() => void act(task, "resume")}
                >
                  {t("taskQueue.resume")}
                </Button>
              )}
              {["failed", "interrupted", "cancelled"].includes(task.state) &&
                !archived && (
                  <Popconfirm
                    title={t("taskQueue.retryConfirm")}
                    onConfirm={() => act(task, "retry")}
                  >
                    <Button size="small" disabled={busy}>
                      {t("taskQueue.retry")}
                    </Button>
                  </Popconfirm>
                )}
              {!terminal.has(task.state) && (
                <Popconfirm
                  title={t("taskQueue.cancelConfirm")}
                  onConfirm={() => act(task, "cancel")}
                >
                  <Button size="small" disabled={busy}>
                    {t("taskQueue.cancel")}
                  </Button>
                </Popconfirm>
              )}
              {!["running", "waiting", "completed"].includes(task.state) &&
                !archived && (
                  <Select
                    size="small"
                    style={{ width: 120 }}
                    placeholder={t("taskQueue.reassign")}
                    value={undefined}
                    options={agentOptions.filter(
                      (option) => option.value !== task.agent_id,
                    )}
                    onChange={(value) => void act(task, "reassign", value)}
                    disabled={busy}
                  />
                )}
              {terminal.has(task.state) && (
                <Button
                  size="small"
                  disabled={busy}
                  onClick={() =>
                    void act(task, archived ? "restore" : "archive")
                  }
                >
                  {t(archived ? "taskQueue.restore" : "taskQueue.archive")}
                </Button>
              )}
            </Space>
          ),
        },
      ]}
    />
  );
  return (
    <div style={{ padding: 16 }}>
      <Space direction="vertical" style={{ width: "100%" }} size={16}>
        <Alert type="info" showIcon message={t("taskQueue.fifoHint")} />
        <Space wrap>
          <Button
            type="primary"
            onClick={() => setCreateOpen(true)}
            disabled={!owned.length}
          >
            {t("taskQueue.create")}
          </Button>
          <Button onClick={() => editWorkflow()} disabled={!owned.length}>
            {t("taskQueue.createWorkflow")}
          </Button>
          <Button onClick={() => void refresh()}>
            {t("taskQueue.refresh")}
          </Button>
          <Button
            onClick={async () => {
              try {
                await saveBlobAsFile(
                  await taskQueueApi.calendarBlob(),
                  "octop-workflows.ics",
                );
              } catch (error) {
                showError(error);
              }
            }}
          >
            {t("taskQueue.exportCalendar")}
          </Button>
          <Button
            onClick={async () => {
              try {
                setCalendarPath((await taskQueueApi.calendarToken(true)).path);
              } catch (error) {
                showError(error);
              }
            }}
          >
            {t("taskQueue.subscribeCalendar")}
          </Button>
          <Button
            onClick={async () => {
              try {
                await taskQueueApi.calendarToken(false);
                message.success(t("taskQueue.calendarRevoked"));
              } catch (error) {
                showError(error);
              }
            }}
          >
            {t("taskQueue.revokeCalendar")}
          </Button>
          <Switch
            checked={archived}
            onChange={setArchived}
            checkedChildren={t("taskQueue.archived")}
            unCheckedChildren={t("taskQueue.active")}
          />
        </Space>
        {!!owned.length && (
          <Space wrap>
            {owned.map((agent) => (
              <Space key={agent.agent_id} size={4}>
                <Typography.Text>{agent.name}</Typography.Text>
                <Switch
                  size="small"
                  checked={!!controls[agent.agent_id]}
                  aria-label={t("taskQueue.pauseQueueFor", {
                    name: agent.name,
                  })}
                  onChange={async (paused) => {
                    try {
                      await taskQueueApi.pauseQueue(agent.agent_id, paused);
                      setControls((current) => ({
                        ...current,
                        [agent.agent_id]: paused,
                      }));
                    } catch (error) {
                      showError(error);
                    }
                  }}
                />
                <Typography.Text type="secondary">
                  {t("taskQueue.pauseNext")}
                </Typography.Text>
              </Space>
            ))}
          </Space>
        )}
        <Tabs
          items={[
            { key: "tasks", label: t("taskQueue.tasks"), children: taskTable },
            {
              key: "workflows",
              label: t("taskQueue.workflows"),
              children: (
                <Table<TaskWorkflow>
                  rowKey="id"
                  dataSource={workflows}
                  size="small"
                  columns={[
                    { title: t("taskQueue.name"), dataIndex: "name" },
                    {
                      title: t("taskQueue.nextRun"),
                      render: (_, row) =>
                        row.next_run_at ? formatTime(row.next_run_at) : "—",
                    },
                    {
                      title: t("taskQueue.steps"),
                      render: (_, row) => row.definition.steps.length,
                    },
                    {
                      title: t("taskQueue.status"),
                      render: (_, row) => (
                        <Tag
                          color={row.schedule_paused ? "warning" : undefined}
                        >
                          {t(
                            row.schedule_paused
                              ? "taskQueue.schedulePaused"
                              : row.enabled
                              ? "taskQueue.enabled"
                              : "taskQueue.disabled",
                          )}
                        </Tag>
                      ),
                    },
                    {
                      title: t("taskQueue.actions"),
                      render: (_, row) => (
                        <Space wrap>
                          <Button
                            size="small"
                            onClick={() => editWorkflow(row)}
                          >
                            {t("taskQueue.edit")}
                          </Button>
                          <Button
                            size="small"
                            disabled={busy}
                            onClick={() => void runWorkflow(row)}
                          >
                            {t("taskQueue.run")}
                          </Button>
                          {row.definition.schedule && (
                            <Button
                              size="small"
                              onClick={async () => {
                                try {
                                  await taskQueueApi.pauseSchedule(
                                    row.id,
                                    !row.schedule_paused,
                                  );
                                  await refresh(true);
                                } catch (error) {
                                  showError(error);
                                }
                              }}
                            >
                              {t(
                                row.schedule_paused
                                  ? "taskQueue.resumeSchedule"
                                  : "taskQueue.pauseSchedule",
                              )}
                            </Button>
                          )}
                          <Popconfirm
                            title={t("taskQueue.deleteWorkflowConfirm")}
                            onConfirm={async () => {
                              try {
                                await taskQueueApi.deleteWorkflow(row.id);
                                await refresh(true);
                              } catch (error) {
                                showError(error);
                              }
                            }}
                          >
                            <Button size="small" danger>
                              {t("taskQueue.deleteWorkflow")}
                            </Button>
                          </Popconfirm>
                          <Popconfirm
                            title={t("taskQueue.rotateConfirm")}
                            onConfirm={() => rotateWebhook(row, true)}
                          >
                            <Button size="small">
                              {t("taskQueue.webhook")}
                            </Button>
                          </Popconfirm>
                          {row.webhook_enabled && (
                            <Button
                              size="small"
                              onClick={() => void rotateWebhook(row, false)}
                            >
                              {t("taskQueue.revokeWebhook")}
                            </Button>
                          )}
                        </Space>
                      ),
                    },
                  ]}
                />
              ),
            },
            {
              key: "runs",
              label: t("taskQueue.runs"),
              children: (
                <Table<WorkflowRun>
                  rowKey="run_id"
                  dataSource={runs}
                  size="small"
                  columns={[
                    { title: t("taskQueue.name"), dataIndex: "name" },
                    {
                      title: t("taskQueue.status"),
                      dataIndex: "state",
                      render: status,
                    },
                    {
                      title: t("taskQueue.created"),
                      dataIndex: "created_at",
                      render: formatTime,
                    },
                  ]}
                  expandable={{
                    expandedRowRender: (row) => (
                      <Space direction="vertical">
                        {row.tasks.map((task) => (
                          <Space key={task.id}>
                            <Button
                              type="link"
                              onClick={() => void details(task)}
                            >
                              {task.title}
                            </Button>
                            {agentName(task.agent_id)}
                            {status(task.state)}
                          </Space>
                        ))}
                      </Space>
                    ),
                  }}
                />
              ),
            },
          ]}
        />
      </Space>
      <Modal
        open={createOpen}
        title={t("taskQueue.create")}
        onCancel={() => setCreateOpen(false)}
        onOk={() => void createTask()}
        confirmLoading={busy}
        okButtonProps={{ disabled: uploading > 0 }}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="agent_id"
            label={t("taskQueue.expert")}
            rules={[{ required: true }]}
          >
            <Select options={agentOptions} />
          </Form.Item>
          <Form.Item
            name="title"
            label={t("taskQueue.name")}
            rules={[{ required: true, whitespace: true, max: 200 }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name="prompt"
            label={t("taskQueue.prompt")}
            rules={[{ required: true, whitespace: true, max: 32000 }]}
          >
            <Input.TextArea rows={6} />
          </Form.Item>
          <Form.Item
            label={t("taskQueue.attachments")}
            extra={t("taskQueue.attachmentHint")}
          >
            <Upload
              showUploadList={false}
              multiple
              beforeUpload={async (file) => {
                const agentId = form.getFieldValue("agent_id") as
                  | string
                  | undefined;
                if (!agentId) {
                  message.error(t("taskQueue.chooseExpertFirst"));
                  return Upload.LIST_IGNORE;
                }
                if (
                  attachments.length >= 10 ||
                  file.size > Math.min(uploadLimit, 25 * 1024 * 1024)
                ) {
                  message.error(t("taskQueue.errors.attachment_limit"));
                  return Upload.LIST_IGNORE;
                }
                setUploading((value) => value + 1);
                try {
                  const result = await uploadApi.uploadFile(agentId, file);
                  if (form.getFieldValue("agent_id") === agentId)
                    setAttachments((previous) => [
                      ...previous,
                      {
                        workspace_path: result.workspace_path,
                        filename: result.filename,
                        mime_type: result.media_type,
                        size: file.size,
                        upload_receipt: result.upload_receipt,
                      },
                    ]);
                } catch (error) {
                  showError(error);
                } finally {
                  setUploading((value) => value - 1);
                }
                return Upload.LIST_IGNORE;
              }}
            >
              <Button disabled={!uploadAgent || uploading > 0}>
                {t("taskQueue.upload")}
              </Button>
            </Upload>
            <Space direction="vertical" style={{ width: "100%", marginTop: 8 }}>
              {attachments.map((item) => (
                <Space key={item.workspace_path}>
                  <Typography.Text>{item.filename}</Typography.Text>
                  <Button
                    type="text"
                    size="small"
                    onClick={() =>
                      setAttachments((current) =>
                        current.filter(
                          (ref) => ref.workspace_path !== item.workspace_path,
                        ),
                      )
                    }
                  >
                    {t("taskQueue.remove")}
                  </Button>
                </Space>
              ))}
            </Space>
          </Form.Item>
          <Form.Item
            name="notify_policy"
            initialValue="always"
            label={t("taskQueue.notifyPolicy")}
            extra={t("taskQueue.quietHint")}
          >
            <Select
              options={[
                {
                  value: "always",
                  label: t("taskQueue.notifyEveryCompletion"),
                },
                { value: "failure", label: t("taskQueue.onlyFailures") },
              ]}
            />
          </Form.Item>
        </Form>
      </Modal>
      <Modal
        open={workflowOpen}
        title={t("taskQueue.createWorkflow")}
        onCancel={() => setWorkflowOpen(false)}
        onOk={() => void saveWorkflow()}
        confirmLoading={busy}
        width={800}
        destroyOnClose
      >
        <Alert
          type="info"
          message={t("taskQueue.workflowHint")}
          style={{ marginBottom: 16 }}
        />
        <Form form={workflowForm} layout="vertical">
          <Form.Item
            name="name"
            label={t("taskQueue.name")}
            rules={[{ required: true, whitespace: true }]}
          >
            <Input maxLength={200} />
          </Form.Item>
          <Form.Item
            name="enabled"
            label={t("taskQueue.enabled")}
            valuePropName="checked"
          >
            <Switch />
          </Form.Item>
          <Form.Item
            name="schedule"
            label={t("taskQueue.schedule")}
            extra={t("taskQueue.scheduleHint")}
          >
            <Input placeholder="cron:0 9 * * *" maxLength={200} />
          </Form.Item>
          <Form.Item name="failure_policy" label={t("taskQueue.failurePolicy")}>
            <Select
              options={[
                { value: "pause", label: t("taskQueue.pauseOnFailure") },
                { value: "continue", label: t("taskQueue.continueOnFailure") },
              ]}
            />
          </Form.Item>
          <Form.Item
            name="notify_policy"
            label={t("taskQueue.notifyPolicy")}
            extra={t("taskQueue.quietHint")}
          >
            <Select
              options={[
                {
                  value: "always",
                  label: t("taskQueue.notifyEveryCompletion"),
                },
                { value: "failure", label: t("taskQueue.onlyFailures") },
              ]}
            />
          </Form.Item>
          <Form.List name="steps">
            {(fields, { add, remove }) => (
              <Space direction="vertical" style={{ width: "100%" }}>
                {fields.map((field) => (
                  <div
                    key={field.key}
                    style={{
                      padding: 12,
                      border: "1px solid var(--ant-color-border, #8884)",
                      borderRadius: 8,
                    }}
                  >
                    <Space align="start" wrap>
                      <Form.Item
                        name={[field.name, "key"]}
                        label={t("taskQueue.stepKey")}
                        rules={[
                          {
                            required: true,
                            pattern: /^[a-zA-Z][a-zA-Z0-9_-]*$/,
                          },
                        ]}
                      >
                        <Input style={{ width: 120 }} />
                      </Form.Item>
                      <Form.Item
                        name={[field.name, "title"]}
                        label={t("taskQueue.name")}
                        rules={[{ required: true, whitespace: true }]}
                      >
                        <Input />
                      </Form.Item>
                      <Form.Item
                        name={[field.name, "agent_id"]}
                        label={t("taskQueue.expert")}
                        rules={[{ required: true }]}
                      >
                        <Select options={agentOptions} style={{ width: 160 }} />
                      </Form.Item>
                      <Button
                        size="small"
                        onClick={() => remove(field.name)}
                        disabled={fields.length === 1}
                      >
                        {t("taskQueue.remove")}
                      </Button>
                    </Space>
                    <Form.Item
                      name={[field.name, "prompt"]}
                      label={t("taskQueue.prompt")}
                      rules={[{ required: true, whitespace: true, max: 32000 }]}
                    >
                      <Input.TextArea rows={3} />
                    </Form.Item>
                    <Form.Item noStyle shouldUpdate>
                      {() => {
                        const steps = (workflowForm.getFieldValue("steps") ??
                          []) as StepDraft[];
                        return (
                          <Form.Item
                            name={[field.name, "depends_on"]}
                            label={t("taskQueue.dependsOn")}
                          >
                            <Select
                              mode="multiple"
                              allowClear
                              options={steps
                                .filter(
                                  (step, index) =>
                                    index !== field.name && step?.key,
                                )
                                .map((step) => ({
                                  value: step.key,
                                  label: step.title || step.key,
                                }))}
                            />
                          </Form.Item>
                        );
                      }}
                    </Form.Item>
                  </div>
                ))}
                <Button
                  onClick={() =>
                    (() => {
                      const used = new Set(
                        (
                          (workflowForm.getFieldValue("steps") ??
                            []) as StepDraft[]
                        ).map((step) => step.key),
                      );
                      let next = 1;
                      while (used.has(`step${next}`)) next++;
                      add({
                        key: `step${next}`,
                        title: "",
                        prompt: "",
                        agent_id: owned[0]?.agent_id,
                        depends_on: [],
                      });
                    })()
                  }
                  disabled={fields.length >= 32}
                >
                  {t("taskQueue.addStep")}
                </Button>
              </Space>
            )}
          </Form.List>
        </Form>
      </Modal>
      <Drawer
        open={!!selected}
        title={selected?.title}
        onClose={() => setSelected(null)}
        width={600}
      >
        {selected && (
          <Space direction="vertical" style={{ width: "100%" }}>
            <Space>
              {status(selected.state)}
              <Typography.Text>{agentName(selected.agent_id)}</Typography.Text>
            </Space>
            {selected.error_code && (
              <Alert
                type="warning"
                message={t(
                  `taskQueue.resultErrors.${selected.error_code}`,
                  t("taskQueue.failed"),
                )}
              />
            )}
            {selected.thread_id && (
              <Button
                onClick={() =>
                  navigate(
                    `/chat/${encodeURIComponent(
                      selected.agent_id,
                    )}/${encodeURIComponent(selected.thread_id!)}`,
                  )
                }
              >
                {t("taskQueue.openConversation")}
              </Button>
            )}
            <Typography.Title level={5}>
              {t("taskQueue.prompt")}
            </Typography.Title>
            <Typography.Paragraph style={{ whiteSpace: "pre-wrap" }}>
              {selected.prompt}
            </Typography.Paragraph>
            <Typography.Title level={5}>
              {t("taskQueue.output")}
            </Typography.Title>
            <Typography.Paragraph style={{ whiteSpace: "pre-wrap" }}>
              {selected.result || t("taskQueue.noOutput")}
            </Typography.Paragraph>
            <Typography.Title level={5}>
              {t("taskQueue.history")}
            </Typography.Title>
            {selected.events.map((event, index) => (
              <Space key={index}>
                {formatTime(event.created_at)}
                {status(event.state)}
              </Space>
            ))}
          </Space>
        )}
      </Drawer>
      <Modal
        open={!!calendarPath}
        title={t("taskQueue.subscribeCalendar")}
        onCancel={() => setCalendarPath(null)}
        footer={
          <Button onClick={() => setCalendarPath(null)}>
            {t("taskQueue.close")}
          </Button>
        }
        destroyOnClose
      >
        <Alert type="info" message={t("taskQueue.calendarHint")} />
        <Typography.Paragraph copyable style={{ marginTop: 16 }}>
          {calendarPath ? window.location.origin + calendarPath : ""}
        </Typography.Paragraph>
      </Modal>
      <Modal
        open={!!webhook}
        title={t("taskQueue.webhook")}
        footer={
          <Button onClick={() => setWebhook(null)}>
            {t("taskQueue.close")}
          </Button>
        }
        onCancel={() => setWebhook(null)}
        destroyOnClose
      >
        <Alert type="warning" message={t("taskQueue.tokenOnce")} />
        <Typography.Paragraph copyable style={{ marginTop: 16 }}>
          {webhook?.token}
        </Typography.Paragraph>
        <Typography.Paragraph copyable>{webhook?.path}</Typography.Paragraph>
        <Typography.Text>{t("taskQueue.webhookUsage")}</Typography.Text>
      </Modal>
    </div>
  );
}
