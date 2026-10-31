import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Empty,
  Form,
  Input,
  List,
  Modal,
  Popconfirm,
  Select,
  Space,
  Tabs,
  Tag,
  Typography,
} from "antd";
import { useTranslation } from "react-i18next";
import {
  accountConnectionsApi as api,
  type VaultConnection,
  type VaultReference,
  type VaultUseRequest,
  type VaultItem,
  type OAuthApp,
} from "../../api/modules/accountConnections";
import {
  connectorsApi,
  type ConnectorCatalogEntry,
} from "../../api/modules/connectors";
import { getApiUrl } from "../../api/config";
import { message } from "../../utils/antdMessage";
import { apiErrorMessage } from "../../utils/apiError";
import { useServerTimezone } from "../../hooks/useServerTimezone";
import { formatServerDateTime } from "../../utils/formatMessageTime";
import PageShell from "../../layouts/PageShell";

type ConnectionForm = {
  provider: "onepassword" | "bitwarden";
  name: string;
  hosts?: string;
  service_account_token?: string;
};
type ReferenceForm = {
  connection_id: string;
  item_id: string;
  vault_id?: string;
  field_name: string;
  label?: string;
};

export function AccountConnectionsPanel() {
  const { t, i18n } = useTranslation();
  const translationRef = useRef(t);
  translationRef.current = t;
  const timeZone = useServerTimezone();
  const [connections, setConnections] = useState<VaultConnection[]>([]);
  const [references, setReferences] = useState<VaultReference[]>([]);
  const [requests, setRequests] = useState<VaultUseRequest[]>([]);
  const [catalog, setCatalog] = useState<ConnectorCatalogEntry[]>([]);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<VaultConnection | null | undefined>();
  const [unlocking, setUnlocking] = useState<VaultConnection | null>(null);
  const [session, setSession] = useState("");
  const [items, setItems] = useState<{
    connection: VaultConnection;
    rows: VaultItem[];
    search: string;
    more: boolean;
  } | null>(null);
  const [referenceOpen, setReferenceOpen] = useState(false);
  const [review, setReview] = useState<VaultUseRequest | null>(null);
  const [oauthKind, setOauthKind] = useState<string>();
  const [oauthPreview, setOauthPreview] = useState<OAuthApp | null>(null);
  const [connectionForm] = Form.useForm<ConnectionForm>();
  const [referenceForm] = Form.useForm<ReferenceForm>();
  const [oauthForm] = Form.useForm();
  const [useForm] = Form.useForm();
  const provider = Form.useWatch("provider", connectionForm);
  const refConnection = Form.useWatch("connection_id", referenceForm);
  const selectedConnection = connections.find(
    (row) => row.id === refConnection,
  );
  const notifyError = useCallback((error: unknown) => {
    const translate = translationRef.current;
    message.error(
      apiErrorMessage(error, translate("common.unknownError"), translate),
    );
  }, []);

  const refresh = useCallback(async () => {
    const result = await Promise.all([
      api.vaults(),
      api.references(),
      api.requests(),
    ]);
    setConnections(result[0]);
    setReferences(result[1]);
    setRequests(result[2]);
  }, []);
  useEffect(() => {
    let active = true;
    void Promise.all([
      api.vaults(),
      api.references(),
      api.requests(),
      connectorsApi.catalog(),
    ])
      .then(([vaults, refs, pending, entries]) => {
        if (!active) return;
        setConnections(vaults);
        setReferences(refs);
        setRequests(pending);
        setCatalog(entries.filter((entry) => entry.auth_kind === "oauth2"));
      })
      .catch((error) => {
        if (active) notifyError(error);
      });
    const timer = window.setInterval(() => {
      if (!document.hidden) void refresh().catch(() => undefined);
    }, 15000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [refresh, notifyError, i18n.language]);
  useEffect(() => {
    if (!oauthKind) return;
    let active = true;
    setOauthPreview(null);
    oauthForm.resetFields();
    void api
      .oauthApp(oauthKind)
      .then((value) => {
        if (!active) return;
        setOauthPreview(value);
        oauthForm.setFieldsValue({
          client_id: value.client_id,
          scopes: value.scopes,
        });
      })
      .catch((error) => {
        if (active) notifyError(error);
      });
    return () => {
      active = false;
    };
  }, [oauthKind, oauthForm, notifyError]);

  async function act(operation: () => Promise<unknown>) {
    setBusy(true);
    try {
      await operation();
      await refresh();
    } catch (error) {
      notifyError(error);
    } finally {
      setBusy(false);
    }
  }
  function openConnection(connection?: VaultConnection) {
    connectionForm.resetFields();
    connectionForm.setFieldsValue(
      connection
        ? {
            provider: connection.provider,
            name: connection.name,
            hosts: connection.allowed_hosts.join("\n"),
          }
        : { provider: "onepassword" },
    );
    setEditing(connection ?? null);
  }
  async function saveConnection(values: ConnectionForm) {
    await act(async () => {
      await api.saveVault(
        {
          provider: values.provider,
          name: values.name,
          allowed_hosts: (values.hosts ?? "").split(/[,\s]+/).filter(Boolean),
          service_account_token: values.service_account_token || undefined,
        },
        editing?.id,
      );
      connectionForm.resetFields();
      setEditing(undefined);
    });
  }
  async function showItems(connection: VaultConnection) {
    await act(async () => {
      const rows = await api.items(connection.id);
      setItems({ connection, rows, search: "", more: rows.length === 100 });
    });
  }
  function addReference(connection?: VaultConnection, item?: VaultItem) {
    referenceForm.resetFields();
    referenceForm.setFieldsValue({
      connection_id: connection?.id,
      item_id: item?.item_id,
      vault_id: item?.vault_id,
      label: item?.title,
      field_name: "password",
    });
    setReferenceOpen(true);
  }
  const pendingCount = requests.filter(
    (value) => value.state === "pending",
  ).length;
  const callback = new URL(
    getApiUrl("/connectors/oauth/callback"),
    window.location.origin,
  ).href;

  const vaultPanel = (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        message={t("accountConnections.vaultIntro")}
      />
      <Space wrap>
        <Button type="primary" onClick={() => openConnection()}>
          {t("accountConnections.addVault")}
        </Button>
        <Button onClick={() => addReference()} disabled={!connections.length}>
          {t("accountConnections.createReference")}
        </Button>
      </Space>
      <List
        dataSource={connections}
        locale={{
          emptyText: <Empty description={t("accountConnections.noVaults")} />,
        }}
        renderItem={(connection) => (
          <List.Item
            actions={[
              <Button
                key="items"
                disabled={busy || !connection.ready}
                onClick={() => void showItems(connection)}
              >
                {t("accountConnections.items")}
              </Button>,
              connection.provider === "bitwarden" ? (
                <Button
                  key="session"
                  disabled={busy}
                  onClick={() =>
                    connection.ready
                      ? void act(() => api.lock(connection.id))
                      : (setSession(""), setUnlocking(connection))
                  }
                >
                  {t(
                    connection.ready
                      ? "accountConnections.lock"
                      : "accountConnections.unlock",
                  )}
                </Button>
              ) : null,
              <Button key="edit" onClick={() => openConnection(connection)}>
                {t("common.edit")}
              </Button>,
              <Popconfirm
                key="delete"
                title={t("accountConnections.disconnectConfirm")}
                onConfirm={() => act(() => api.disconnect(connection.id))}
              >
                <Button danger disabled={busy}>
                  {t("accountConnections.disconnect")}
                </Button>
              </Popconfirm>,
            ].filter(Boolean)}
          >
            <List.Item.Meta
              title={
                <Space>
                  {connection.name}
                  <Tag>
                    {connection.provider === "onepassword"
                      ? "1Password"
                      : "Bitwarden"}
                  </Tag>
                  <Tag color={connection.ready ? "green" : "default"}>
                    {t(
                      connection.ready
                        ? "accountConnections.ready"
                        : "accountConnections.locked",
                    )}
                  </Tag>
                </Space>
              }
              description={
                <>
                  <div>
                    {connection.allowed_hosts.length
                      ? connection.allowed_hosts.join(", ")
                      : t("accountConnections.deliveryDisabled")}
                  </div>
                  {connection.profile_path && (
                    <Typography.Text type="secondary" copyable>
                      {connection.profile_path}
                    </Typography.Text>
                  )}
                </>
              }
            />
          </List.Item>
        )}
      />
      <Card size="small" title={t("accountConnections.references")}>
        <List
          size="small"
          dataSource={references}
          locale={{ emptyText: t("accountConnections.noReferences") }}
          renderItem={(reference) => (
            <List.Item>
              <Space direction="vertical" size={0}>
                <span>
                  {reference.label} · {reference.field_name}
                </span>
                <Typography.Text code copyable>
                  {reference.reference}
                </Typography.Text>
              </Space>
            </List.Item>
          )}
        />
      </Card>
    </Space>
  );

  const approvalsPanel = (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        message={t("accountConnections.approvalIntro")}
      />
      <List
        dataSource={[...requests].reverse()}
        locale={{ emptyText: t("accountConnections.noRequests") }}
        renderItem={(value) => (
          <List.Item
            actions={
              value.state === "pending"
                ? [
                    <Button
                      key="review"
                      type="primary"
                      disabled={busy}
                      onClick={() => setReview(value)}
                    >
                      {t("accountConnections.review")}
                    </Button>,
                    <Button
                      key="reject"
                      disabled={busy}
                      onClick={() =>
                        void act(() => api.reject(value.request_id))
                      }
                    >
                      {t("accountConnections.reject")}
                    </Button>,
                  ]
                : []
            }
          >
            <List.Item.Meta
              title={
                <Space>
                  {value.purpose}
                  <Tag>
                    {t(`accountConnections.states.${value.state}`, value.state)}
                  </Tag>
                  {value.status_code && <Tag>HTTP {value.status_code}</Tag>}
                </Space>
              }
              description={
                <Space direction="vertical" size={0}>
                  <Typography.Text code>
                    {value.method} {value.url}
                  </Typography.Text>
                  <span>
                    {t("accountConnections.expires")}:{" "}
                    {formatServerDateTime(value.expires_at, timeZone)}
                  </span>
                </Space>
              }
            />
          </List.Item>
        )}
      />
      <Card size="small" title={t("accountConnections.requestUse")}>
        <Form
          form={useForm}
          layout="vertical"
          onFinish={(values) =>
            void act(async () => {
              await api.requestUse({
                ...values,
                body: values.body_json?.trim()
                  ? JSON.parse(values.body_json)
                  : undefined,
              });
              useForm.resetFields();
            })
          }
          initialValues={{
            method: "GET",
            header_name: "Authorization",
            prefix: "Bearer ",
          }}
        >
          <Form.Item
            name="reference"
            label={t("accountConnections.reference")}
            rules={[{ required: true }]}
          >
            <Select
              options={references.map((value) => ({
                value: value.reference,
                label: value.label,
              }))}
            />
          </Form.Item>
          <Space align="start" style={{ width: "100%" }}>
            <Form.Item name="method" label={t("accountConnections.method")}>
              <Select
                style={{ width: 100 }}
                options={["GET", "POST", "PUT", "PATCH", "DELETE"].map(
                  (value) => ({ value }),
                )}
              />
            </Form.Item>
            <Form.Item
              name="url"
              label="HTTPS URL"
              rules={[{ required: true }]}
            >
              <Input style={{ width: "min(420px, 55vw)" }} />
            </Form.Item>
          </Space>
          <Form.Item name="header_name" label={t("accountConnections.header")}>
            <Select
              options={["Authorization", "X-API-Key", "Api-Key"].map(
                (value) => ({ value }),
              )}
            />
          </Form.Item>
          <Form.Item name="prefix" label={t("accountConnections.prefix")}>
            <Input maxLength={32} />
          </Form.Item>
          <Form.Item
            name="body_json"
            label={t("accountConnections.requestBody")}
            rules={[
              {
                validator: async (_, value) => {
                  if (!String(value ?? "").trim()) return;
                  const parsed = JSON.parse(String(value));
                  if (
                    !parsed ||
                    typeof parsed !== "object" ||
                    Array.isArray(parsed)
                  )
                    throw new Error(t("accountConnections.bodyObject"));
                },
              },
            ]}
          >
            <Input.TextArea rows={3} />
          </Form.Item>
          <Form.Item
            name="purpose"
            label={t("accountConnections.purpose")}
            rules={[{ required: true }]}
          >
            <Input maxLength={500} />
          </Form.Item>
          <Button htmlType="submit" disabled={busy || !references.length}>
            {t("accountConnections.requestUse")}
          </Button>
        </Form>
      </Card>
    </Space>
  );

  const oauthPanel = (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        message={t("accountConnections.oauthIntro")}
      />
      <Select
        style={{ width: "min(420px, 100%)" }}
        placeholder={t("accountConnections.chooseService")}
        value={oauthKind}
        onChange={setOauthKind}
        options={catalog.map((entry) => ({
          value: entry.kind,
          label: entry.name,
        }))}
      />
      {oauthKind && (
        <>
          <Typography.Paragraph>
            {t("accountConnections.callback")}:{" "}
            <Typography.Text code copyable>
              {callback}
            </Typography.Text>
          </Typography.Paragraph>
          <Form
            form={oauthForm}
            layout="vertical"
            onFinish={(values) =>
              void act(async () => {
                const next = await api.saveOauthApp(oauthKind, values);
                setOauthPreview(next);
                oauthForm.setFieldValue("client_secret", "");
                message.success(t("accountConnections.saved"));
              })
            }
          >
            <Form.Item
              name="client_id"
              label="Client ID"
              rules={[{ required: true }]}
            >
              <Input autoComplete="off" />
            </Form.Item>
            <Form.Item name="client_secret" label="Client Secret">
              <Input.Password
                autoComplete="new-password"
                placeholder={
                  oauthPreview?.secret_configured
                    ? t("accountConnections.secretConfigured")
                    : undefined
                }
              />
            </Form.Item>
            <Form.Item name="scopes" label={t("accountConnections.scopes")}>
              <Input placeholder={t("accountConnections.scopesHint")} />
            </Form.Item>
            <Space>
              <Button htmlType="submit" type="primary" loading={busy}>
                {t("common.save")}
              </Button>
              <Popconfirm
                title={t("accountConnections.removeOauthConfirm")}
                onConfirm={() =>
                  act(async () => {
                    await api.deleteOauthApp(oauthKind);
                    setOauthPreview(null);
                    oauthForm.resetFields();
                  })
                }
              >
                <Button danger disabled={busy || !oauthPreview?.configured}>
                  {t("common.delete")}
                </Button>
              </Popconfirm>
            </Space>
          </Form>
          <Typography.Paragraph type="secondary">
            {t("accountConnections.oauthNext")}
          </Typography.Paragraph>
        </>
      )}
    </Space>
  );

  return (
    <>
      <Tabs
        items={[
          {
            key: "vaults",
            label: t("accountConnections.vaults"),
            children: vaultPanel,
          },
          {
            key: "requests",
            label: `${t("accountConnections.approvals")}${
              pendingCount ? ` (${pendingCount})` : ""
            }`,
            children: approvalsPanel,
          },
          {
            key: "oauth",
            label: t("accountConnections.oauthApps"),
            children: oauthPanel,
          },
        ]}
      />
      <Modal
        open={editing !== undefined}
        title={t(
          editing
            ? "accountConnections.editVault"
            : "accountConnections.addVault",
        )}
        onCancel={() => {
          setEditing(undefined);
          connectionForm.resetFields();
        }}
        onOk={() => connectionForm.submit()}
        confirmLoading={busy}
        destroyOnHidden
      >
        <Form
          form={connectionForm}
          layout="vertical"
          onFinish={(values) => void saveConnection(values)}
        >
          <Form.Item
            name="provider"
            label={t("accountConnections.provider")}
            rules={[{ required: true }]}
          >
            <Select
              disabled={!!editing}
              options={[
                { value: "onepassword", label: "1Password" },
                { value: "bitwarden", label: "Bitwarden" },
              ]}
            />
          </Form.Item>
          <Form.Item
            name="name"
            label={t("accountConnections.name")}
            rules={[{ required: true }]}
          >
            <Input maxLength={100} />
          </Form.Item>
          {provider === "onepassword" ? (
            <Form.Item
              name="service_account_token"
              label={t("accountConnections.serviceToken")}
              rules={editing ? [] : [{ required: true }]}
              extra={t("accountConnections.onepasswordHelp")}
            >
              <Input.Password
                autoComplete="new-password"
                placeholder={
                  editing ? t("accountConnections.secretConfigured") : undefined
                }
              />
            </Form.Item>
          ) : (
            <Alert
              type="info"
              message={t("accountConnections.bitwardenHelp")}
              style={{ marginBottom: 16 }}
            />
          )}
          <Form.Item
            name="hosts"
            label={t("accountConnections.allowedHosts")}
            extra={t("accountConnections.hostsHelp")}
          >
            <Input.TextArea rows={2} placeholder="api.example.com" />
          </Form.Item>
        </Form>
      </Modal>
      <Modal
        open={!!unlocking}
        title={t("accountConnections.unlock")}
        onCancel={() => {
          setUnlocking(null);
          setSession("");
        }}
        onOk={() =>
          unlocking &&
          void act(async () => {
            await api.unlock(unlocking.id, session);
            setSession("");
            setUnlocking(null);
          })
        }
        confirmLoading={busy}
        okButtonProps={{ disabled: !session.trim() }}
        destroyOnHidden
      >
        <Alert
          type="info"
          message={t("accountConnections.bitwardenUnlockHelp")}
          style={{ marginBottom: 16 }}
        />
        <Input.Password
          value={session}
          onChange={(event) => setSession(event.target.value)}
          autoComplete="new-password"
          aria-label="BW_SESSION"
        />
      </Modal>
      <Modal
        open={!!items}
        title={items?.connection.name}
        onCancel={() => setItems(null)}
        footer={null}
        destroyOnHidden
      >
        <Input.Search
          placeholder={t("common.search")}
          onSearch={(search) =>
            items &&
            void act(async () => {
              const rows = await api.items(items.connection.id, 0, search);
              setItems({
                connection: items.connection,
                rows,
                search,
                more: rows.length === 100,
              });
            })
          }
          maxLength={200}
          style={{ marginBottom: 12 }}
        />
        {items?.more && (
          <Button
            disabled={busy}
            onClick={() =>
              void act(async () => {
                const next = await api.items(
                  items.connection.id,
                  items.rows.length,
                  items.search,
                );
                setItems({
                  ...items,
                  rows: [...items.rows, ...next],
                  more: next.length === 100,
                });
              })
            }
          >
            {t("accountConnections.loadMore")}
          </Button>
        )}
        <List
          dataSource={items?.rows ?? []}
          locale={{ emptyText: t("accountConnections.noItems") }}
          renderItem={(item) => (
            <List.Item
              actions={[
                <Button
                  key="reference"
                  onClick={() => items && addReference(items.connection, item)}
                >
                  {t("accountConnections.createReference")}
                </Button>,
              ]}
            >
              <List.Item.Meta title={item.title} description={item.item_id} />
            </List.Item>
          )}
        />
      </Modal>
      <Modal
        open={referenceOpen}
        title={t("accountConnections.createReference")}
        onCancel={() => {
          setReferenceOpen(false);
          referenceForm.resetFields();
        }}
        onOk={() => referenceForm.submit()}
        confirmLoading={busy}
        destroyOnHidden
      >
        <Form
          form={referenceForm}
          layout="vertical"
          onFinish={(values) =>
            void act(async () => {
              await api.createReference(values);
              referenceForm.resetFields();
              setReferenceOpen(false);
            })
          }
        >
          <Form.Item
            name="connection_id"
            label={t("accountConnections.vault")}
            rules={[{ required: true }]}
          >
            <Select
              options={connections.map((value) => ({
                value: value.id,
                label: value.name,
              }))}
            />
          </Form.Item>
          <Form.Item
            name="item_id"
            label="Item ID"
            rules={[{ required: true }]}
          >
            <Input />
          </Form.Item>
          {selectedConnection?.provider === "onepassword" && (
            <Form.Item
              name="vault_id"
              label="Vault ID"
              rules={[{ required: true }]}
            >
              <Input />
            </Form.Item>
          )}
          <Form.Item
            name="field_name"
            label={t("accountConnections.field")}
            rules={[{ required: true }]}
          >
            {selectedConnection?.provider === "bitwarden" ? (
              <Select
                options={["password", "username", "totp"].map((value) => ({
                  value,
                }))}
              />
            ) : (
              <Input />
            )}
          </Form.Item>
          <Form.Item name="label" label={t("accountConnections.name")}>
            <Input maxLength={200} />
          </Form.Item>
        </Form>
      </Modal>
      <Modal
        open={!!review}
        title={t("accountConnections.review")}
        onCancel={() => setReview(null)}
        okText={t("accountConnections.approveOnce")}
        onOk={() =>
          review?.approval_token &&
          void act(async () => {
            const result = await api.approve(
              review.request_id,
              review.approval_token!,
            );
            setReview(null);
            message.success(`HTTP ${result.status_code}`);
          })
        }
        okButtonProps={{ disabled: !review?.approval_token }}
        confirmLoading={busy}
        destroyOnHidden
      >
        {review && (
          <Space direction="vertical" style={{ width: "100%" }}>
            <Typography.Paragraph>{review.purpose}</Typography.Paragraph>
            <Typography.Text code>{review.reference}</Typography.Text>
            <Typography.Paragraph code style={{ overflowWrap: "anywhere" }}>
              {review.method} {review.url}
            </Typography.Paragraph>
            <Typography.Text>
              {review.header_name}: {review.prefix}
              {t("accountConnections.secretPlaceholder")}
            </Typography.Text>
            {review.body && (
              <pre
                style={{
                  whiteSpace: "pre-wrap",
                  maxHeight: 240,
                  overflow: "auto",
                }}
              >
                {JSON.stringify(review.body, null, 2)}
              </pre>
            )}
            <Alert type="info" message={t("accountConnections.approveHelp")} />
          </Space>
        )}
      </Modal>
    </>
  );
}

export default function AccountConnectionsPage() {
  const { t } = useTranslation();
  return (
    <PageShell title={t("accountConnections.title")}>
      <AccountConnectionsPanel />
    </PageShell>
  );
}
