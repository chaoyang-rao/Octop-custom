import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Spin,
  Switch,
  Tag,
  Typography,
} from "antd";
import { useTranslation } from "react-i18next";
import {
  resourcesApi,
  decodeText,
  encodeText,
  type ResourceDefinition,
  type ResourceAdminState,
  type ResourceEntry,
} from "../../api/modules/enterpriseResources";
import {
  enterpriseMcpApi,
  type EnterpriseMcpMember,
} from "../../api/modules/enterpriseMcp";
import { apiErrorMessage } from "../../utils/apiError";
import { useServerTimezone } from "../../hooks/useServerTimezone";
import { formatServerDateTime } from "../../utils/formatMessageTime";

export default function ResourceAdmin() {
  const { t } = useTranslation();
  const zone = useServerTimezone();
  const [state, setState] = useState<ResourceAdminState | null>(null);
  const [members, setMembers] = useState<EnterpriseMcpMember[]>([]);
  const [mcp, setMcp] = useState<{ label: string; value: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<ResourceDefinition | null>(null);
  const [files, setFiles] = useState<ResourceDefinition["files"]>([]);
  const [selected, setSelected] = useState("");
  const [revision, setRevision] = useState<number>();
  const [form] = Form.useForm<ResourceDefinition>();
  const input = useRef<HTMLInputElement>(null);
  const errorRef = useRef<HTMLDivElement>(null);
  const run = async (op: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await op();
    } catch (e) {
      setError(apiErrorMessage(e, t("enterpriseResources.syncFailed")));
      requestAnimationFrame(() => errorRef.current?.focus());
    } finally {
      setBusy(false);
    }
  };
  const load = useCallback(async () => {
    setBusy(true);
    try {
      const [catalog, people, connectors] = await Promise.all([
        resourcesApi.admin(),
        resourcesApi.members(),
        enterpriseMcpApi.adminCatalog(),
      ]);
      setState(catalog);
      setMembers(people);
      setMcp(
        connectors.draft.entries.map((e) => ({
          label: e.display_name,
          value: e.entry_id,
        })),
      );
      setError("");
    } catch (e) {
      setError(apiErrorMessage(e, t("enterpriseResources.syncFailed")));
    } finally {
      setBusy(false);
    }
  }, [t]);
  useEffect(() => {
    void load();
  }, [load]);
  function edit(resource: ResourceDefinition) {
    setEditing(resource);
    setFiles(resource.files);
    setSelected(resource.files[0]?.path ?? "");
    form.setFieldsValue(resource);
  }
  function create(kind: "expert" | "skill") {
    edit({
      resource_id: "",
      kind,
      display_name: "",
      description: "",
      enabled: true,
      allowed_subjects: [],
      skill_refs: [],
      mcp_refs: [],
      files: [
        {
          path: kind === "expert" ? "SOUL.md" : "SKILL.md",
          content_base64: encodeText(
            kind === "expert"
              ? ""
              : "---\nname: skill-name\ndescription: Skill description\n---\n",
          ),
        },
      ],
    });
  }
  async function openEntry(entry: ResourceEntry) {
    await run(async () => {
      const bundle = await resourcesApi.bundle(entry.digest);
      edit({
        ...bundle,
        enabled: entry.enabled,
        allowed_subjects: entry.allowed_subjects,
      });
    });
  }
  const active = files.find((f) => f.path === selected);
  const text = active ? decodeText(active.content_base64) : null;
  const kind = Form.useWatch("kind", form) ?? editing?.kind;
  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        message={t("enterpriseResources.adminHint")}
      />
      {error && (
        <div role="alert" tabIndex={-1} ref={errorRef}>
          <Alert type="error" message={error} />
        </div>
      )}
      <Space wrap>
        <Typography.Title level={4} style={{ margin: 0 }}>
          {t("enterpriseResources.version", {
            revision: state?.published.revision ?? 0,
          })}
        </Typography.Title>
        <Button loading={busy} onClick={() => void load()}>
          {t("enterpriseResources.refresh")}
        </Button>
        <Button disabled={busy} onClick={() => create("expert")}>
          {t("enterpriseResources.addExpert")}
        </Button>
        <Button disabled={busy} onClick={() => create("skill")}>
          {t("enterpriseResources.addSkill")}
        </Button>
        <Button disabled={busy} onClick={() => input.current?.click()}>
          {t("enterpriseResources.import")}
        </Button>
        <input
          type="file"
          accept=".json,application/json"
          ref={input}
          style={{ display: "none" }}
          aria-label={t("enterpriseResources.import")}
          onChange={(e) => {
            const file = e.target.files?.[0];
            e.target.value = "";
            if (file)
              void run(async () => {
                if (file.size > 12 * 1024 * 1024)
                  throw new Error(t("enterpriseResources.invalidPack"));
                const value: unknown = JSON.parse(await file.text());
                if (
                  !value ||
                  typeof value !== "object" ||
                  !("files" in value) ||
                  !Array.isArray(value.files) ||
                  !("kind" in value) ||
                  !["expert", "skill"].includes(String(value.kind)) ||
                  !value.files.length ||
                  value.files.some(
                    (f) =>
                      typeof f.path !== "string" ||
                      typeof f.content_base64 !== "string",
                  )
                )
                  throw new Error(t("enterpriseResources.invalidPack"));
                edit(value as ResourceDefinition);
              });
          }}
        />
        <Popconfirm
          title={t("enterpriseResources.publishConfirm")}
          disabled={!state || busy}
          onConfirm={() =>
            run(async () => {
              if (state) setState(await resourcesApi.publish(state.etag));
            })
          }
        >
          <Button type="primary" disabled={!state || busy}>
            {t("enterpriseResources.publish")}
          </Button>
        </Popconfirm>
      </Space>
      {busy && !state && <Spin />}
      {state?.draft.length === 0 && (
        <Empty description={t("enterpriseResources.emptyDraft")} />
      )}
      {state?.draft.map((entry) => (
        <Card
          key={entry.resource_id}
          size="small"
          title={
            <Space wrap>
              <Tag>{t(`enterpriseResources.${entry.kind}`)}</Tag>
              <span>{entry.display_name}</span>
              <Typography.Text type="secondary">
                {entry.resource_id}
              </Typography.Text>
              <Tag color={entry.enabled ? "green" : "default"}>
                {t(
                  entry.enabled
                    ? "enterpriseResources.enabled"
                    : "enterpriseResources.disabled",
                )}
              </Tag>
            </Space>
          }
          extra={
            <Space>
              <Button disabled={busy} onClick={() => void openEntry(entry)}>
                {t("enterpriseResources.edit")}
              </Button>
              <Popconfirm
                title={t("enterpriseResources.removeConfirm")}
                onConfirm={() =>
                  run(async () =>
                    setState(
                      await resourcesApi.remove(entry.resource_id, state.etag),
                    ),
                  )
                }
              >
                <Button danger disabled={busy}>
                  {t("enterpriseResources.remove")}
                </Button>
              </Popconfirm>
            </Space>
          }
        >
          <Typography.Paragraph style={{ margin: 0 }}>
            {entry.description}
          </Typography.Paragraph>
          <Typography.Text type="secondary">
            {t("enterpriseResources.visibility")}:{" "}
            {entry.allowed_subjects.length
              ? entry.allowed_subjects
                  .map(
                    (s) =>
                      members.find((m) => m.subject === s)?.display_name ??
                      s.slice(0, 8),
                  )
                  .join(", ")
              : t("enterpriseResources.allMembers")}
          </Typography.Text>
        </Card>
      ))}
      {!!state?.history.length && (
        <Card size="small" title={t("enterpriseResources.history")}>
          <Space wrap>
            <Select
              style={{ minWidth: 260 }}
              aria-label={t("enterpriseResources.history")}
              value={revision}
              onChange={setRevision}
              options={state.history.map((v) => ({
                value: v.revision,
                label: `v${v.revision} · ${formatServerDateTime(
                  v.published_at,
                  zone,
                )}`,
              }))}
            />
            <Popconfirm
              title={t("enterpriseResources.rollbackConfirm")}
              disabled={!revision || busy}
              onConfirm={() =>
                run(async () => {
                  if (revision)
                    setState(await resourcesApi.rollback(revision, state.etag));
                })
              }
            >
              <Button disabled={!revision || busy}>
                {t("enterpriseResources.rollback")}
              </Button>
            </Popconfirm>
          </Space>
        </Card>
      )}
      <Modal
        title={t("enterpriseResources.edit")}
        open={!!editing}
        width={900}
        maskClosable={false}
        closable={!busy}
        cancelButtonProps={{ disabled: busy }}
        onCancel={() => setEditing(null)}
        confirmLoading={busy}
        okText={t("enterpriseResources.saveDraft")}
        onOk={() =>
          void run(async () => {
            const values = await form.validateFields();
            if (!state || !editing) return;
            const next = { ...editing, ...values, files };
            setState(await resourcesApi.save(next, state.etag));
            setEditing(null);
          })
        }
      >
        <Alert
          type="info"
          showIcon
          message={t("enterpriseResources.reviewContent")}
          style={{ marginBottom: 16 }}
        />
        {error && (
          <Alert type="error" message={error} style={{ marginBottom: 16 }} />
        )}
        <Form form={form} layout="vertical" disabled={busy}>
          <Form.Item name="kind" hidden>
            <Input />
          </Form.Item>
          <Form.Item
            name="resource_id"
            label={t("enterpriseResources.resourceId")}
            rules={[
              {
                required: true,
                pattern: /^[a-z0-9][a-z0-9_-]{0,47}$/,
                message: t("enterpriseResources.idHint"),
              },
            ]}
          >
            <Input
              disabled={
                !!editing &&
                !!state?.draft.some(
                  (e) => e.resource_id === editing.resource_id,
                )
              }
            />
          </Form.Item>
          <Form.Item
            name="display_name"
            label={t("enterpriseResources.name")}
            rules={[{ required: true }]}
          >
            <Input maxLength={80} />
          </Form.Item>
          <Form.Item
            name="description"
            label={t("enterpriseResources.description")}
          >
            <Input.TextArea
              maxLength={2000}
              autoSize={{ minRows: 2, maxRows: 4 }}
            />
          </Form.Item>
          <Form.Item
            name="enabled"
            label={t("enterpriseResources.enabled")}
            valuePropName="checked"
          >
            <Switch />
          </Form.Item>
          <Form.Item
            name="allowed_subjects"
            label={t("enterpriseResources.visibility")}
            extra={t("enterpriseResources.allMembersHint")}
          >
            <Select
              mode="multiple"
              options={members.map((m) => ({
                label: m.display_name,
                value: m.subject,
              }))}
            />
          </Form.Item>
          {kind === "expert" && (
            <>
              <Form.Item
                name="skill_refs"
                label={t("enterpriseResources.skills")}
              >
                <Select
                  mode="multiple"
                  options={state?.draft
                    .filter((e) => e.kind === "skill" && e.enabled)
                    .map((e) => ({
                      label: e.display_name,
                      value: e.resource_id,
                    }))}
                />
              </Form.Item>
              <Form.Item
                name="mcp_refs"
                label={t("enterpriseResources.mcp")}
                extra={t("enterpriseResources.memberAuth")}
              >
                <Select mode="multiple" options={mcp} />
              </Form.Item>
            </>
          )}
        </Form>
        <Typography.Title level={5}>
          {t("enterpriseResources.files")}
        </Typography.Title>
        <Space wrap style={{ marginBottom: 12 }}>
          <Select
            aria-label={t("enterpriseResources.files")}
            style={{ minWidth: 240 }}
            value={selected}
            options={files.map((f) => ({ value: f.path, label: f.path }))}
            onChange={setSelected}
          />
          <Button
            disabled={busy || kind !== "expert" || files.length >= 6}
            onClick={() => {
              const path =
                kind === "expert"
                  ? [
                      "SOUL.md",
                      "AGENTS.md",
                      "IDENTITY.md",
                      "TOOLS.md",
                      "HEARTBEAT.md",
                      "PROACTIVE.md",
                    ].find((p) => !files.some((f) => f.path === p))
                  : undefined;
              if (path) {
                setFiles([...files, { path, content_base64: "" }]);
                setSelected(path);
              }
            }}
          >
            {t("enterpriseResources.addPrompt")}
          </Button>
          <label>
            <input
              type="file"
              multiple
              disabled={busy}
              aria-label={t("enterpriseResources.addFiles")}
              onChange={(e) => {
                const uploads = Array.from(e.target.files ?? []);
                e.target.value = "";
                void run(async () => {
                  if (
                    uploads.reduce((sum, f) => sum + f.size, 0) >
                    8 * 1024 * 1024
                  )
                    throw new Error(t("enterpriseResources.invalidPack"));
                  const additions = await Promise.all(
                    uploads.map(async (f) => {
                      const bytes = new Uint8Array(await f.arrayBuffer());
                      return {
                        path: f.name,
                        content_base64: btoa(
                          Array.from(bytes, (c) => String.fromCharCode(c)).join(
                            "",
                          ),
                        ),
                      };
                    }),
                  );
                  setFiles((current) => [
                    ...current.filter(
                      (f) => !additions.some((a) => a.path === f.path),
                    ),
                    ...additions,
                  ]);
                  if (additions[0]) setSelected(additions[0].path);
                });
              }}
            />
          </label>
          <Button
            danger
            disabled={busy || files.length < 2}
            onClick={() => {
              const next = files.filter((f) => f.path !== selected);
              setFiles(next);
              setSelected(next[0]?.path ?? "");
            }}
          >
            {t("enterpriseResources.removeFile")}
          </Button>
        </Space>
        {kind === "skill" && active && (
          <Form.Item label={t("enterpriseResources.path")}>
            <Input
              aria-label={t("enterpriseResources.path")}
              value={selected}
              disabled={busy}
              onChange={(e) => {
                const path = e.target.value;
                setFiles((current) =>
                  current.map((f) =>
                    f.path === selected ? { ...f, path } : f,
                  ),
                );
                setSelected(path);
              }}
            />
          </Form.Item>
        )}
        {active &&
          (text !== null ? (
            <Input.TextArea
              aria-label={selected}
              value={text}
              disabled={busy}
              autoSize={{ minRows: 8, maxRows: 18 }}
              style={{ fontFamily: "monospace" }}
              onChange={(e) =>
                setFiles((current) =>
                  current.map((f) =>
                    f.path === selected
                      ? { ...f, content_base64: encodeText(e.target.value) }
                      : f,
                  ),
                )
              }
            />
          ) : (
            <Typography.Text type="secondary">
              {t("enterpriseResources.binary")}
            </Typography.Text>
          ))}
      </Modal>
    </Space>
  );
}
