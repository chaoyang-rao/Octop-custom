import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Empty,
  Form,
  Input,
  Modal,
  Space,
  Spin,
  Tag,
  Typography,
} from "antd";
import { RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  enterpriseMcpApi,
  type EnterpriseMcpCredentials,
  type EnterpriseMcpMemberEntry,
  type EnterpriseMcpNodeState,
} from "../../../api/modules/enterpriseMcp";
import { useServerTimezone } from "../../../hooks/useServerTimezone";
import { formatServerDateTime } from "../../../utils/formatMessageTime";
import { apiErrorMessage, parseApiError } from "../../../utils/apiError";
import { notifyConnectorsChanged } from "./customMcpUtils";
import styles from "../../EnterpriseMcp/enterpriseMcp.module.less";

export default function EnterpriseMcpTab() {
  const { t } = useTranslation();
  const timeZone = useServerTimezone();
  const [state, setState] = useState<EnterpriseMcpNodeState | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState("");
  const [entry, setEntry] = useState<EnterpriseMcpMemberEntry | null>(null);
  const [authorizing, setAuthorizing] = useState(false);
  const [clearing, setClearing] = useState<string | null>(null);
  const [enabling, setEnabling] = useState<string | null>(null);
  const [authorizationError, setAuthorizationError] = useState("");
  const [form] = Form.useForm<EnterpriseMcpCredentials>();
  const requestRevision = useRef(0);
  const mutating =
    authorizing || syncing || clearing !== null || enabling !== null;

  const load = useCallback(async () => {
    const revision = requestRevision.current;
    try {
      const next = await enterpriseMcpApi.nodeStatus();
      if (revision === requestRevision.current) {
        setState(next);
        setError("");
      }
    } catch (err) {
      if (revision === requestRevision.current) {
        setError(apiErrorMessage(err, t("enterpriseMcp.loadFailed"), t));
      }
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, 15_000);
    return () => window.clearInterval(timer);
  }, [load]);

  const sync = async () => {
    requestRevision.current += 1;
    setSyncing(true);
    try {
      const next = await enterpriseMcpApi.sync();
      requestRevision.current += 1;
      setState(next);
      setError("");
      notifyConnectorsChanged();
    } catch (err) {
      setError(apiErrorMessage(err, t("enterpriseMcp.syncFailed"), t));
    } finally {
      setSyncing(false);
    }
  };

  const closeAuthorization = () => {
    form.resetFields();
    setAuthorizationError("");
    setEntry(null);
  };

  useEffect(() => {
    if (!entry || !state) return;
    const current = state.entries.find(
      (item) => item.entry_id === entry.entry_id,
    );
    if (
      !current ||
      !current.enabled ||
      current.fingerprint !== entry.fingerprint ||
      current.url !== entry.url ||
      current.auth_kind !== entry.auth_kind
    ) {
      form.resetFields();
      setEntry(null);
      setAuthorizationError("");
      setError(t("enterpriseMcp.authorizationTargetChanged"));
    }
  }, [entry, form, state, t]);

  const authorize = async () => {
    if (!entry) return;
    let values: EnterpriseMcpCredentials;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    setAuthorizing(true);
    requestRevision.current += 1;
    try {
      const credentials: EnterpriseMcpCredentials =
        entry.auth_kind === "bearer"
          ? { token: values.token?.trim() }
          : { username: values.username?.trim(), password: values.password };
      const next = await enterpriseMcpApi.authorize(entry.entry_id, {
        ...credentials,
        expected_fingerprint: entry.fingerprint,
      });
      requestRevision.current += 1;
      setState(next);
      setError("");
      closeAuthorization();
      notifyConnectorsChanged();
    } catch (err) {
      if (parseApiError(err)?.code === "ENTERPRISE_MCP_CATALOG_CONFLICT") {
        closeAuthorization();
        await load();
        setError(t("enterpriseMcp.authorizationTargetChanged"));
      } else {
        setAuthorizationError(
          apiErrorMessage(err, t("enterpriseMcp.authorizationFailed"), t),
        );
      }
    } finally {
      setAuthorizing(false);
    }
  };

  const clearAuthorization = async (current: EnterpriseMcpMemberEntry) => {
    requestRevision.current += 1;
    setClearing(current.entry_id);
    try {
      const next = await enterpriseMcpApi.clearAuthorization(current.entry_id);
      requestRevision.current += 1;
      setState(next);
      setError("");
      notifyConnectorsChanged();
    } catch (err) {
      setError(apiErrorMessage(err, t("enterpriseMcp.authorizationFailed"), t));
    } finally {
      setClearing(null);
    }
  };

  const enableConnection = async (current: EnterpriseMcpMemberEntry) => {
    requestRevision.current += 1;
    setEnabling(current.entry_id);
    try {
      const next = await enterpriseMcpApi.authorize(current.entry_id, {
        expected_fingerprint: current.fingerprint,
      });
      requestRevision.current += 1;
      setState(next);
      setError("");
      notifyConnectorsChanged();
    } catch (err) {
      if (parseApiError(err)?.code === "ENTERPRISE_MCP_CATALOG_CONFLICT") {
        await load();
        setError(t("apiErrors.ENTERPRISE_MCP_CATALOG_CONFLICT"));
      } else {
        setError(
          apiErrorMessage(err, t("enterpriseMcp.authorizationFailed"), t),
        );
      }
    } finally {
      setEnabling(null);
    }
  };

  const status = (current: EnterpriseMcpMemberEntry) => {
    if (!current.enabled) return <Tag>{t("enterpriseMcp.disabled")}</Tag>;
    if (current.configuration_error || state?.configuration_error)
      return <Tag color="error">{t("enterpriseMcp.unavailable")}</Tag>;
    if (current.local_disabled && !current.authorized)
      return <Tag>{t("enterpriseMcp.locallyDisconnected")}</Tag>;
    if (current.auth_kind === "none") {
      return (
        <Tag>
          {t(
            !current.authorized
              ? current.local_disabled
                ? "enterpriseMcp.locallyDisconnected"
                : "enterpriseMcp.enableRequired"
              : state?.pending_apply
              ? "enterpriseMcp.pendingApply"
              : "enterpriseMcp.locallyEnabled",
          )}
        </Tag>
      );
    }
    if (current.needs_reauthorization)
      return (
        <Tag color="warning">{t("enterpriseMcp.reauthorizationRequired")}</Tag>
      );
    if (!current.authorized)
      return (
        <Tag color="warning">{t("enterpriseMcp.authorizationRequired")}</Tag>
      );
    if (state?.pending_apply)
      return <Tag color="processing">{t("enterpriseMcp.pendingApply")}</Tag>;
    return <Tag color="success">{t("enterpriseMcp.ready")}</Tag>;
  };

  if (loading)
    return (
      <div role="status">
        <Spin /> {t("common.loading")}
      </div>
    );

  return (
    <section className={styles.panel} aria-label={t("enterpriseMcp.title")}>
      <div className={styles.toolbar}>
        <div>
          <Typography.Title level={4} style={{ margin: 0 }}>
            {t("enterpriseMcp.title")}
          </Typography.Title>
          <Typography.Text type="secondary">
            {t("enterpriseMcp.memberHint")}
          </Typography.Text>
        </div>
        <Button
          icon={<RefreshCw size={16} />}
          onClick={() => void sync()}
          loading={syncing}
          disabled={
            !state?.enabled ||
            authorizing ||
            clearing !== null ||
            enabling !== null
          }
        >
          {t("enterpriseMcp.syncNow")}
        </Button>
      </div>
      {error && (
        <Alert
          role="alert"
          type="error"
          message={error}
          action={
            <Button onClick={() => void load()}>{t("common.retry")}</Button>
          }
        />
      )}
      {state && !state.enabled && (
        <Alert type="info" message={t("enterpriseMcp.nodeDisabled")} />
      )}
      {state?.enabled && (
        <>
          <div className={styles.summary}>
            <span>
              {t("enterpriseMcp.revision", { revision: state.revision })}
            </span>
            <span>
              {t("enterpriseMcp.lastSynced", {
                time: state.last_synced_at
                  ? formatServerDateTime(state.last_synced_at, timeZone)
                  : t("enterpriseMcp.neverSynced"),
              })}
            </span>
          </div>
          {state.authority_url && (
            <Typography.Text className={styles.url}>
              {state.authority_url}
            </Typography.Text>
          )}
          {state.sync_error && (
            <Alert
              role="alert"
              type="error"
              message={t("enterpriseMcp.syncFailed")}
              description={
                <>
                  {state.sync_error}
                  <br />
                  {t("enterpriseMcp.cachedHint")}
                </>
              }
            />
          )}
          {state.configuration_error && (
            <Alert
              role="alert"
              type="error"
              message={t("enterpriseMcp.configurationError")}
              description={state.configuration_error}
            />
          )}
          {state.pending_apply && (
            <Alert
              role="status"
              type="info"
              message={t("enterpriseMcp.pendingApply")}
              description={t("enterpriseMcp.pendingApplyHint")}
            />
          )}
          {state.entries.length === 0 ? (
            <Empty description={t("enterpriseMcp.noEntries")} />
          ) : (
            <div className={styles.entries}>
              {state.entries.map((current) => (
                <Card key={current.entry_id} className={styles.entry}>
                  <div className={styles.entryTitle}>
                    <Typography.Text strong>
                      {current.display_name}
                    </Typography.Text>
                    {status(current)}
                  </div>
                  <Typography.Paragraph type="secondary">
                    {current.description}
                  </Typography.Paragraph>
                  <Typography.Text className={styles.url}>
                    {current.url}
                  </Typography.Text>
                  {current.configuration_error && (
                    <Alert
                      role="alert"
                      type="error"
                      message={current.configuration_error}
                      style={{ marginTop: 12 }}
                    />
                  )}
                  <Space wrap style={{ marginTop: 16 }}>
                    {current.auth_kind !== "none" && (
                      <Button
                        disabled={
                          !current.enabled ||
                          mutating ||
                          !!current.configuration_error ||
                          !!state.configuration_error
                        }
                        onClick={() => {
                          form.resetFields();
                          setAuthorizationError("");
                          setEntry(current);
                        }}
                      >
                        {t(
                          current.authorized && !current.needs_reauthorization
                            ? "enterpriseMcp.updateAuthorization"
                            : "enterpriseMcp.authorize",
                        )}
                      </Button>
                    )}
                    {current.auth_kind === "none" && !current.authorized && (
                      <Button
                        loading={enabling === current.entry_id}
                        disabled={
                          !current.enabled ||
                          !!current.configuration_error ||
                          !!state.configuration_error ||
                          mutating
                        }
                        onClick={() => void enableConnection(current)}
                      >
                        {t("enterpriseMcp.enableConnection")}
                      </Button>
                    )}
                    {
                      <Button
                        danger
                        loading={clearing === current.entry_id}
                        disabled={mutating}
                        onClick={() => void clearAuthorization(current)}
                      >
                        {t(
                          current.auth_kind === "none"
                            ? "enterpriseMcp.disconnectLocal"
                            : "enterpriseMcp.clearAuthorization",
                        )}
                      </Button>
                    }
                    {current.auth_kind === "none" && (
                      <Typography.Text type="secondary">
                        {t("enterpriseMcp.noCredentialsRequired")}
                      </Typography.Text>
                    )}
                  </Space>
                </Card>
              ))}
            </div>
          )}
        </>
      )}
      <Modal
        title={
          entry
            ? t("enterpriseMcp.authorizeEntry", { name: entry.display_name })
            : t("enterpriseMcp.authorize")
        }
        open={entry !== null}
        onCancel={closeAuthorization}
        onOk={() => void authorize()}
        okText={t("enterpriseMcp.saveAuthorization")}
        cancelText={t("common.cancel")}
        confirmLoading={authorizing}
        cancelButtonProps={{ disabled: authorizing }}
        closable={!authorizing}
        keyboard={!authorizing}
        maskClosable={false}
        destroyOnHidden
      >
        {entry && (
          <Typography.Paragraph className={styles.url}>
            {entry.url}
          </Typography.Paragraph>
        )}
        <Alert
          type="info"
          message={t("enterpriseMcp.personalAuthorizationHint")}
          style={{ marginBottom: 16 }}
        />
        {authorizationError && (
          <Alert
            role="alert"
            type="error"
            message={authorizationError}
            style={{ marginBottom: 16 }}
          />
        )}
        <Form form={form} layout="vertical" preserve={false}>
          {entry?.auth_kind === "bearer" ? (
            <Form.Item
              name="token"
              label={t("enterpriseMcp.token")}
              rules={[
                {
                  required: true,
                  whitespace: true,
                  message: t("enterpriseMcp.required"),
                },
              ]}
            >
              <Input.Password autoComplete="new-password" />
            </Form.Item>
          ) : (
            <>
              <Form.Item
                name="username"
                label={t("enterpriseMcp.username")}
                rules={[
                  {
                    required: true,
                    whitespace: true,
                    message: t("enterpriseMcp.required"),
                  },
                ]}
              >
                <Input autoComplete="username" />
              </Form.Item>
              <Form.Item
                name="password"
                label={t("enterpriseMcp.password")}
                rules={[
                  { required: true, message: t("enterpriseMcp.required") },
                ]}
              >
                <Input.Password autoComplete="new-password" />
              </Form.Item>
            </>
          )}
        </Form>
      </Modal>
    </section>
  );
}
