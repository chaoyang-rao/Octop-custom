import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Empty,
  Form,
  Input,
  Popconfirm,
  Select,
  Space,
  Spin,
  Switch,
  Tag,
  Typography,
} from "antd";
import { Plus, RefreshCw, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  enterpriseMcpApi,
  type EnterpriseMcpAdminState,
  type EnterpriseMcpEntry,
  type EnterpriseMcpMember,
} from "../../api/modules/enterpriseMcp";
import { useServerTimezone } from "../../hooks/useServerTimezone";
import { formatServerDateTime } from "../../utils/formatMessageTime";
import { apiErrorMessage, parseApiError } from "../../utils/apiError";
import styles from "./enterpriseMcp.module.less";

interface DraftForm {
  entries: EnterpriseMcpEntry[];
}

export default function EnterpriseMcpAdmin() {
  const { t } = useTranslation();
  const timeZone = useServerTimezone();
  const [state, setState] = useState<EnterpriseMcpAdminState | null>(null);
  const [members, setMembers] = useState<EnterpriseMcpMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [operation, setOperation] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [dirty, setDirty] = useState(false);
  const [rollbackRevision, setRollbackRevision] = useState<number | null>(null);
  const [form] = Form.useForm<DraftForm>();
  const errorRef = useRef<HTMLDivElement>(null);
  const publishedBy = state?.history.find(
    (version) => version.revision === state?.published.revision,
  )?.published_by;

  const apply = useCallback(
    (next: EnterpriseMcpAdminState) => {
      setState(next);
      form.setFieldsValue({
        entries: next.draft.entries.map((entry) => ({
          ...entry,
          allowed_subjects: [...entry.allowed_subjects],
        })),
      });
      setDirty(false);
      setRollbackRevision(null);
      setError("");
    },
    [form],
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [next, people] = await Promise.all([
        enterpriseMcpApi.adminCatalog(),
        enterpriseMcpApi.members(),
      ]);
      setMembers(people);
      apply(next);
    } catch (err) {
      setError(apiErrorMessage(err, t("enterpriseMcp.loadFailed"), t));
    } finally {
      setLoading(false);
    }
  }, [apply, t]);

  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    if (error) errorRef.current?.focus();
  }, [error]);

  const report = (err: unknown) => {
    const code = parseApiError(err)?.code;
    setError(
      code === "ENTERPRISE_MCP_CATALOG_CONFLICT"
        ? t("enterpriseMcp.conflict")
        : apiErrorMessage(err, t("enterpriseMcp.operationFailed"), t),
    );
  };

  const save = async () => {
    if (!state) return;
    let values: DraftForm;
    try {
      values = await form.validateFields();
    } catch {
      setError(t("enterpriseMcp.validationHint"));
      return;
    }
    const entries = (values.entries ?? []).map((entry) => ({
      ...entry,
      entry_id: entry.entry_id.trim(),
      display_name: entry.display_name.trim(),
      description: (entry.description ?? "").trim(),
      url: entry.url.trim(),
      allowed_subjects: [...new Set(entry.allowed_subjects ?? [])],
    }));
    setOperation("save");
    try {
      apply(await enterpriseMcpApi.saveDraft(entries, state.etag));
    } catch (err) {
      report(err);
    } finally {
      setOperation(null);
    }
  };

  const publish = async () => {
    if (!state || dirty) return;
    setOperation("publish");
    try {
      apply(await enterpriseMcpApi.publish(state.etag));
    } catch (err) {
      report(err);
    } finally {
      setOperation(null);
    }
  };

  const rollback = async () => {
    if (!state || dirty || rollbackRevision == null) return;
    setOperation("rollback");
    try {
      apply(await enterpriseMcpApi.rollback(rollbackRevision, state.etag));
    } catch (err) {
      report(err);
    } finally {
      setOperation(null);
    }
  };

  if (loading && !state)
    return (
      <div role="status">
        <Spin /> {t("common.loading")}
      </div>
    );

  return (
    <section
      className={styles.panel}
      aria-label={t("enterpriseMcp.adminTitle")}
    >
      <div className={styles.toolbar}>
        <div>
          <Typography.Title level={4} style={{ margin: 0 }}>
            {t("enterpriseMcp.adminTitle")}
          </Typography.Title>
          <Typography.Text type="secondary">
            {t("enterpriseMcp.adminHint")}
          </Typography.Text>
        </div>
        <Popconfirm
          title={t("enterpriseMcp.discardHint")}
          disabled={!dirty}
          onConfirm={() => void load()}
          okText={t("enterpriseMcp.reloadDraft")}
          cancelText={t("common.cancel")}
        >
          <Button
            icon={<RefreshCw size={16} />}
            loading={loading}
            disabled={operation !== null}
            onClick={() => {
              if (!dirty) void load();
            }}
          >
            {t("enterpriseMcp.reloadDraft")}
          </Button>
        </Popconfirm>
      </div>
      <Alert type="info" message={t("enterpriseMcp.definitionOnly")} />
      {error && (
        <div ref={errorRef} tabIndex={-1} className={styles.error}>
          <Alert role="alert" type="error" message={error} />
        </div>
      )}
      {state && (
        <>
          <div className={styles.summary}>
            <Tag color="processing">
              {t("enterpriseMcp.publishedRevision", {
                revision: state.published.revision,
              })}
            </Tag>
            <span>
              {t("enterpriseMcp.publishedAt", {
                time: state.published.published_at
                  ? formatServerDateTime(state.published.published_at, timeZone)
                  : t("enterpriseMcp.notPublished"),
              })}
            </span>
            {publishedBy && (
              <span>
                {t("enterpriseMcp.publishedBy", {
                  publisher: publishedBy,
                })}
              </span>
            )}
            {dirty && <Tag color="warning">{t("enterpriseMcp.unsaved")}</Tag>}
          </div>
          <Form
            form={form}
            layout="vertical"
            disabled={operation !== null || loading}
            onValuesChange={() => setDirty(true)}
          >
            <Form.List name="entries">
              {(fields, { add, remove }) => (
                <>
                  {fields.length === 0 && (
                    <Empty description={t("enterpriseMcp.noDraftEntries")} />
                  )}
                  <div className={styles.entries}>
                    {fields.map((field) => (
                      <Card
                        key={field.key}
                        title={t("enterpriseMcp.entryNumber", {
                          number: field.name + 1,
                        })}
                        extra={
                          <Button
                            type="text"
                            danger
                            icon={<Trash2 size={16} />}
                            aria-label={t("enterpriseMcp.removeEntry", {
                              number: field.name + 1,
                            })}
                            disabled={operation !== null || loading}
                            onClick={() => {
                              remove(field.name);
                              setDirty(true);
                            }}
                          />
                        }
                      >
                        <div className={styles.editorGrid}>
                          <Form.Item
                            name={[field.name, "entry_id"]}
                            label={t("enterpriseMcp.entryId")}
                            extra={t("enterpriseMcp.stableIdHint")}
                            rules={[
                              {
                                required: true,
                                whitespace: true,
                                message: t("enterpriseMcp.required"),
                              },
                              {
                                pattern: /^[A-Za-z0-9_-]{1,64}$/,
                                message: t("enterpriseMcp.idHint"),
                              },
                            ]}
                          >
                            <Input autoComplete="off" />
                          </Form.Item>
                          <Form.Item
                            name={[field.name, "display_name"]}
                            label={t("enterpriseMcp.displayName")}
                            rules={[
                              {
                                required: true,
                                whitespace: true,
                                message: t("enterpriseMcp.required"),
                              },
                            ]}
                          >
                            <Input maxLength={80} />
                          </Form.Item>
                          <Form.Item
                            className={styles.wide}
                            name={[field.name, "url"]}
                            label={t("enterpriseMcp.url")}
                            rules={[
                              {
                                required: true,
                                message: t("enterpriseMcp.required"),
                              },
                              {
                                type: "url",
                                message: t("enterpriseMcp.httpsHint"),
                              },
                              {
                                pattern: /^https:\/\//,
                                message: t("enterpriseMcp.httpsHint"),
                              },
                            ]}
                          >
                            <Input
                              autoComplete="off"
                              placeholder="https://mcp.example.com/mcp"
                            />
                          </Form.Item>
                          <Form.Item
                            name={[field.name, "auth_kind"]}
                            label={t("enterpriseMcp.authentication")}
                            rules={[{ required: true }]}
                          >
                            <Select
                              options={[
                                {
                                  value: "bearer",
                                  label: t("enterpriseMcp.authBearer"),
                                },
                                {
                                  value: "basic",
                                  label: t("enterpriseMcp.authBasic"),
                                },
                                {
                                  value: "none",
                                  label: t("enterpriseMcp.authNone"),
                                },
                              ]}
                            />
                          </Form.Item>
                          <Form.Item
                            name={[field.name, "enabled"]}
                            label={t("enterpriseMcp.enabled")}
                            valuePropName="checked"
                          >
                            <Switch />
                          </Form.Item>
                          <Form.Item
                            className={styles.wide}
                            name={[field.name, "description"]}
                            label={t("enterpriseMcp.description")}
                          >
                            <Input.TextArea
                              autoSize={{ minRows: 2, maxRows: 5 }}
                            />
                          </Form.Item>
                          <Form.Item
                            className={styles.wide}
                            name={[field.name, "allowed_subjects"]}
                            label={t("enterpriseMcp.audience")}
                            extra={t("enterpriseMcp.audienceHint")}
                          >
                            <Select
                              mode="multiple"
                              optionFilterProp="label"
                              options={members.map((member) => ({
                                value: member.subject,
                                label: member.display_name,
                              }))}
                              labelRender={({ value }) =>
                                members.find(
                                  (member) => member.subject === value,
                                )?.display_name ??
                                t("enterpriseMcp.unavailableMember")
                              }
                            />
                          </Form.Item>
                        </div>
                      </Card>
                    ))}
                  </div>
                  <Button
                    style={{ marginTop: 16 }}
                    icon={<Plus size={16} />}
                    onClick={() => {
                      add({
                        entry_id: "",
                        display_name: "",
                        description: "",
                        url: "",
                        auth_kind: "bearer",
                        enabled: true,
                        allowed_subjects: [],
                      });
                      setDirty(true);
                    }}
                  >
                    {t("enterpriseMcp.addEntry")}
                  </Button>
                </>
              )}
            </Form.List>
            <Space wrap style={{ marginTop: 16 }}>
              <Button
                onClick={() => void save()}
                loading={operation === "save"}
                disabled={operation !== null || !dirty || loading}
              >
                {t("enterpriseMcp.saveDraft")}
              </Button>
              <Button
                type="primary"
                onClick={() => void publish()}
                loading={operation === "publish"}
                disabled={operation !== null || dirty || loading}
              >
                {t("enterpriseMcp.publish")}
              </Button>
              {dirty && (
                <Typography.Text type="secondary">
                  {t("enterpriseMcp.saveBeforePublish")}
                </Typography.Text>
              )}
            </Space>
          </Form>
          <Card title={t("enterpriseMcp.history")}>
            <div className={styles.history}>
              <Select
                aria-label={t("enterpriseMcp.selectVersion")}
                placeholder={t("enterpriseMcp.selectVersion")}
                style={{ minWidth: 230 }}
                value={rollbackRevision ?? undefined}
                onChange={(revision) => setRollbackRevision(revision)}
                disabled={operation !== null || dirty || loading}
                options={state.history
                  .filter(
                    (version) => version.revision !== state.published.revision,
                  )
                  .map((version) => ({
                    value: version.revision,
                    label: t("enterpriseMcp.historyVersion", {
                      revision: version.revision,
                      time: formatServerDateTime(
                        version.published_at,
                        timeZone,
                      ),
                      publisher: version.published_by,
                    }),
                  }))}
              />
              <Button
                onClick={() => void rollback()}
                loading={operation === "rollback"}
                disabled={
                  rollbackRevision == null ||
                  operation !== null ||
                  dirty ||
                  loading
                }
              >
                {t("enterpriseMcp.rollback")}
              </Button>
              <Typography.Text type="secondary">
                {t("enterpriseMcp.rollbackHint")}
              </Typography.Text>
            </div>
          </Card>
        </>
      )}
    </section>
  );
}
