import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  App,
  Button,
  Checkbox,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
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
  conversationsApi,
  type Conversation,
  type ImportPreview,
  type ImportResult,
} from "../../api/modules/conversations";
import { apiErrorMessage } from "../../utils/apiError";
import { saveBlobAsFile } from "../../utils/saveBlobAsFile";
import { useServerTimezone } from "../../hooks/useServerTimezone";
import { formatServerDateTime } from "../../utils/formatMessageTime";

export default function ConversationLibrary() {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const { agents, refresh: refreshAgents } = useAgent();
  const owned = useMemo(
    () => agents.filter((agent) => !agent.bridge && agent.is_owner !== false),
    [agents],
  );
  const navigate = useNavigate();
  const timeZone = useServerTimezone();
  const [archived, setArchived] = useState(false);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<string>();
  const [rows, setRows] = useState<Conversation[]>([]);
  const [offset, setOffset] = useState(0);
  const [more, setMore] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [keys, setKeys] = useState<string[]>([]);
  const [target, setTarget] = useState<string>();
  const [names, setNames] = useState<Record<string, string>>({});
  const [exportIds, setExportIds] = useState<string[]>([]);
  const [files, setFiles] = useState(false);
  const [skills, setSkills] = useState(true);
  const [workflows, setWorkflows] = useState(false);
  const [history, setHistory] = useState(false);
  const sequence = useRef(0);
  const showError = useCallback(
    (error: unknown) =>
      message.error(
        apiErrorMessage(error, t("conversationLibrary.actionFailed"), t),
      ),
    [message, t],
  );
  const load = useCallback(async () => {
    const request = ++sequence.current;
    setLoading(true);
    try {
      const data = await conversationsApi.list({
        archived,
        agent_id: filter,
        query,
        offset,
      });
      if (sequence.current !== request) return;
      setRows(data.conversations);
      setMore(data.has_more);
    } catch (error) {
      if (sequence.current === request) showError(error);
    } finally {
      if (sequence.current === request) setLoading(false);
    }
  }, [archived, filter, query, offset, showError]);
  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 150);
    return () => {
      window.clearTimeout(timer);
      sequence.current++;
    };
  }, [load]);
  const closeImport = async () => {
    if (busy) return;
    if (preview?.state === "preview" && !result) {
      try {
        await conversationsApi.discard(preview.id);
      } catch (error) {
        showError(error);
      }
    }
    setImportOpen(false);
    setPreview(null);
    setResult(null);
    setKeys([]);
    setNames({});
  };
  const selectZip = async (file: File) => {
    if (file.size > 100 * 1024 * 1024) {
      message.error(t("conversationLibrary.archiveLimit"));
      return false;
    }
    setBusy(true);
    try {
      if (preview) await conversationsApi.discard(preview.id);
      const data = await conversationsApi.stage(file);
      setPreview(data);
      setResult(null);
      setKeys(
        data.items.filter((item) => !item.duplicate).map((item) => item.key),
      );
      setNames({});
    } catch (error) {
      showError(error);
    } finally {
      setBusy(false);
    }
    return false;
  };
  const confirm = async () => {
    if (!preview) return;
    setBusy(true);
    try {
      const data = await conversationsApi.confirm(preview.id, {
        keys,
        names,
        target_agent_id: target,
        include_files: files,
        include_skills: skills,
        include_workflows: workflows,
        skip_duplicates: true,
      });
      setResult(data);
      await refreshAgents();
      await load();
    } catch (error) {
      showError(error);
    } finally {
      setBusy(false);
    }
  };
  const doExport = async () => {
    setBusy(true);
    try {
      const blob = await conversationsApi.export({
        agent_ids: exportIds,
        include_files: files,
        include_skills: skills,
        include_conversations: history,
        include_workflows: workflows,
      });
      saveBlobAsFile(blob, "octop-transfer.zip");
      setExportOpen(false);
    } catch (error) {
      showError(error);
    } finally {
      setBusy(false);
    }
  };
  const openChat = (agentId: string, threadId: string) =>
    navigate(
      `/chat/${encodeURIComponent(agentId)}/${encodeURIComponent(threadId)}`,
    );
  const choices = owned.map((agent) => ({
    value: agent.agent_id,
    label: agent.name,
  }));
  return (
    <div style={{ padding: 24, maxWidth: 1200, margin: "0 auto" }}>
      <Space direction="vertical" size="middle" style={{ width: "100%" }}>
        <Space wrap style={{ justifyContent: "space-between", width: "100%" }}>
          <Typography.Title level={3} style={{ margin: 0 }}>
            {t("conversationLibrary.title")}
          </Typography.Title>
          <Space>
            <Button
              onClick={() => {
                setFiles(false);
                setImportOpen(true);
              }}
            >
              {t("conversationLibrary.import")}
            </Button>
            <Button
              onClick={() => {
                setExportIds(owned.map((agent) => agent.agent_id));
                setFiles(false);
                setExportOpen(true);
              }}
            >
              {t("conversationLibrary.export")}
            </Button>
          </Space>
        </Space>
        <Tabs
          activeKey={archived ? "archived" : "active"}
          onChange={(key) => {
            setArchived(key === "archived");
            setOffset(0);
          }}
          items={[
            { key: "active", label: t("conversationLibrary.active") },
            { key: "archived", label: t("conversationLibrary.archiveTab") },
          ]}
        />
        <Space wrap>
          <Input.Search
            allowClear
            placeholder={t("conversationLibrary.search")}
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setOffset(0);
            }}
            style={{ width: 280 }}
          />
          <Select
            allowClear
            placeholder={t("conversationLibrary.expert")}
            options={choices}
            value={filter}
            onChange={(value) => {
              setFilter(value);
              setOffset(0);
            }}
            style={{ width: 180 }}
          />
          <Button onClick={() => void load()}>
            {t("conversationLibrary.refresh")}
          </Button>
        </Space>
        <Table<Conversation>
          rowKey="thread_id"
          loading={loading}
          dataSource={rows}
          pagination={false}
          size="small"
          columns={[
            {
              title: t("conversationLibrary.conversation"),
              key: "title",
              render: (_, row) => (
                <Space direction="vertical" size={0}>
                  <Button
                    type="link"
                    style={{ padding: 0, height: "auto", maxWidth: 400 }}
                    onClick={() => openChat(row.agent_id, row.thread_id)}
                  >
                    {row.title || t("conversationLibrary.untitled")}
                  </Button>
                  <Space>
                    {row.project_name && <Tag>{row.project_name}</Tag>}
                    {row.origin && <Tag color="blue">{row.origin.source}</Tag>}
                  </Space>
                </Space>
              ),
            },
            {
              title: t("conversationLibrary.expert"),
              dataIndex: "agent_name",
              key: "agent",
            },
            {
              title: t("conversationLibrary.updated"),
              key: "updated",
              render: (_, row) =>
                formatServerDateTime(
                  row.last_active || row.created_at,
                  timeZone,
                ),
            },
            {
              title: t("conversationLibrary.actions"),
              key: "actions",
              render: (_, row) => (
                <Button
                  size="small"
                  disabled={busy}
                  onClick={async () => {
                    setBusy(true);
                    try {
                      await conversationsApi.archive(
                        row.thread_id,
                        !row.archived,
                      );
                      await load();
                    } catch (error) {
                      showError(error);
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  {t(
                    row.archived
                      ? "conversationLibrary.restore"
                      : "conversationLibrary.archive",
                  )}
                </Button>
              ),
            },
          ]}
        />
        <Space>
          <Button
            disabled={!offset || loading}
            onClick={() => setOffset(Math.max(0, offset - 50))}
          >
            {t("conversationLibrary.previous")}
          </Button>
          <Button
            disabled={!more || loading}
            onClick={() => setOffset(offset + 50)}
          >
            {t("conversationLibrary.next")}
          </Button>
        </Space>
      </Space>
      <Modal
        open={importOpen}
        title={t("conversationLibrary.import")}
        onCancel={() => void closeImport()}
        width={780}
        footer={null}
        maskClosable={!busy}
        closable={!busy}
      >
        <Space direction="vertical" style={{ width: "100%" }}>
          <Alert type="info" message={t("conversationLibrary.importHint")} />
          {!result && (
            <Upload
              accept=".zip,application/zip"
              showUploadList={false}
              beforeUpload={selectZip}
              disabled={busy}
            >
              <Button loading={busy}>
                {t("conversationLibrary.chooseZip")}
              </Button>
            </Upload>
          )}
          {preview && !result && (
            <>
              <Typography.Text type="secondary">
                {t("conversationLibrary.previewStats", {
                  count: preview.items.length,
                  omitted: preview.omitted_messages,
                  ignored: preview.ignored_files,
                })}
              </Typography.Text>
              <Typography.Text
                type="secondary"
                style={{ fontSize: 11, overflowWrap: "anywhere" }}
              >
                SHA-256: {preview.sha256}
              </Typography.Text>
              {preview.kind === "grok-history" ? (
                <Select
                  placeholder={t("conversationLibrary.targetExpert")}
                  options={choices}
                  value={target}
                  onChange={setTarget}
                  style={{ width: "100%" }}
                />
              ) : (
                <Space wrap>
                  <Checkbox
                    checked={files}
                    onChange={(event) => setFiles(event.target.checked)}
                  >
                    {t("conversationLibrary.includeFiles")}
                  </Checkbox>
                  <Checkbox
                    checked={skills}
                    onChange={(event) => setSkills(event.target.checked)}
                  >
                    {t("conversationLibrary.includeSkills")}
                  </Checkbox>
                  <Checkbox
                    checked={workflows}
                    onChange={(event) => setWorkflows(event.target.checked)}
                  >
                    {t("conversationLibrary.includeWorkflows")}
                  </Checkbox>
                </Space>
              )}
              <Table
                rowKey="key"
                size="small"
                pagination={{ pageSize: 10 }}
                dataSource={preview.items}
                rowSelection={{
                  selectedRowKeys: keys,
                  onChange: (values) => setKeys(values.map(String)),
                  getCheckboxProps: (item) => ({ disabled: item.duplicate }),
                }}
                columns={[
                  {
                    title: t("conversationLibrary.name"),
                    key: "name",
                    render: (_, item) => (
                      <Space direction="vertical" size={2}>
                        {preview.kind === "transfer" ? (
                          <Input
                            value={names[item.key] ?? item.name}
                            onChange={(event) =>
                              setNames({
                                ...names,
                                [item.key]: event.target.value,
                              })
                            }
                          />
                        ) : (
                          item.name
                        )}
                        {item.name_conflict && (
                          <Tag color="warning">
                            {t("conversationLibrary.nameConflict")}
                          </Tag>
                        )}
                        {item.duplicate && (
                          <Tag>{t("conversationLibrary.duplicate")}</Tag>
                        )}
                      </Space>
                    ),
                  },
                  {
                    title: t("conversationLibrary.messages"),
                    dataIndex: "messages",
                    key: "messages",
                  },
                  {
                    title: t("conversationLibrary.files"),
                    dataIndex: "files",
                    key: "files",
                  },
                  {
                    title: t("conversationLibrary.skills"),
                    dataIndex: "skills",
                    key: "skills",
                  },
                ]}
              />
              {preview.warnings.map((warning) => (
                <Alert
                  key={warning}
                  type="warning"
                  message={t(`conversationLibrary.warnings.${warning}`, {
                    defaultValue: t("conversationLibrary.reviewWarning"),
                  })}
                />
              ))}
              <Popconfirm
                title={t("conversationLibrary.confirmImport")}
                description={t("conversationLibrary.insertOnly")}
                onConfirm={() => void confirm()}
              >
                <Button
                  type="primary"
                  loading={busy}
                  disabled={
                    !keys.length || (preview.kind === "grok-history" && !target)
                  }
                >
                  {t("conversationLibrary.confirm")}
                </Button>
              </Popconfirm>
            </>
          )}
          {result && (
            <>
              <Alert
                type="success"
                message={t("conversationLibrary.imported", {
                  agents: result.agents.length,
                  chats: result.threads.length,
                  skipped: result.skipped,
                })}
              />
              {result.threads.map((thread) => (
                <Button
                  type="link"
                  key={thread.thread_id}
                  onClick={() => openChat(thread.agent_id, thread.thread_id)}
                >
                  {thread.title}
                </Button>
              ))}
              {result.agents.map((agent) => (
                <Tag key={agent.agent_id}>{agent.name}</Tag>
              ))}
              {result.warnings.map((warning) => (
                <Alert
                  key={warning}
                  type="warning"
                  message={t(`conversationLibrary.warnings.${warning}`, {
                    defaultValue: t("conversationLibrary.reviewWarning"),
                  })}
                />
              ))}
            </>
          )}
        </Space>
      </Modal>
      <Modal
        open={exportOpen}
        title={t("conversationLibrary.export")}
        onCancel={() => {
          if (!busy) setExportOpen(false);
        }}
        confirmLoading={busy}
        onOk={() => void doExport()}
        okButtonProps={{ disabled: !exportIds.length }}
      >
        <Space direction="vertical" style={{ width: "100%" }}>
          <Alert type="info" message={t("conversationLibrary.exportHint")} />
          <Select
            mode="multiple"
            options={choices}
            value={exportIds}
            onChange={setExportIds}
            style={{ width: "100%" }}
          />
          <Checkbox
            checked={skills}
            onChange={(event) => setSkills(event.target.checked)}
          >
            {t("conversationLibrary.includeSkills")}
          </Checkbox>
          <Checkbox
            checked={files}
            onChange={(event) => setFiles(event.target.checked)}
          >
            {t("conversationLibrary.includeFiles")}
          </Checkbox>
          <Checkbox
            checked={history}
            onChange={(event) => setHistory(event.target.checked)}
          >
            {t("conversationLibrary.includeConversations")}
          </Checkbox>
          <Checkbox
            checked={workflows}
            onChange={(event) => setWorkflows(event.target.checked)}
          >
            {t("conversationLibrary.includeWorkflows")}
          </Checkbox>
        </Space>
      </Modal>
    </div>
  );
}
