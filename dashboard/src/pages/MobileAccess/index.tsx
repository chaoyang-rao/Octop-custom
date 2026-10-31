import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Input,
  Modal,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import { QRCodeSVG } from "qrcode.react";
import { useTranslation } from "react-i18next";
import {
  mobileAccessApi,
  type MobileDevice,
  type MobilePairingPreview,
  type MobileScope,
} from "../../api/modules/mobileAccess";
import { useCurrentUser } from "../../hooks/useCurrentUser";
import { useServerTimezone } from "../../hooks/useServerTimezone";
import PageShell from "../../layouts/PageShell";
import { formatServerDateTime } from "../../utils/formatMessageTime";

import PushConfiguration from "./PushConfiguration";
import RemoteSetup from "./RemoteSetup";

const defaults: MobileScope[] = ["chat", "files", "notifications", "tasks"];
const controlPermissions = {
  browser: "browser",
  desktop: "desktop",
  terminal: "terminal",
  phone: "mobile",
  manage_agents: "experts",
} as const;

export default function MobileAccess() {
  const { t } = useTranslation();
  const user = useCurrentUser();
  const timezone = useServerTimezone();
  const [devices, setDevices] = useState<MobileDevice[]>([]);
  const [loading, setLoading] = useState(false);
  const [code, setCode] = useState("");
  const [preview, setPreview] = useState<MobilePairingPreview | null>(null);
  const [scopes, setScopes] = useState<MobileScope[]>(defaults);
  const [busy, setBusy] = useState(false);
  const allowed = useCallback(
    (permission: string) =>
      user?.role === "admin" || !!user?.permissions?.includes(permission),
    [user],
  );
  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setDevices(await mobileAccessApi.list());
    } catch {
      message.error(t("mobileAccess.loadFailed"));
    } finally {
      setLoading(false);
    }
  }, [t]);
  useEffect(() => {
    void refresh();
  }, [refresh]);
  const inspect = async () => {
    setBusy(true);
    try {
      setPreview(await mobileAccessApi.inspect(code));
      setScopes(
        defaults.filter((scope) => scope !== "tasks" || allowed("tasks")),
      );
    } catch {
      message.error(t("mobileAccess.invalidCode"));
    } finally {
      setBusy(false);
    }
  };
  const approve = async () => {
    setBusy(true);
    try {
      await mobileAccessApi.approve(code, scopes);
      setPreview(null);
      setCode("");
      await refresh();
      message.success(t("mobileAccess.approved"));
    } catch {
      message.error(t("mobileAccess.approveFailed"));
    } finally {
      setBusy(false);
    }
  };
  const revoke = (device: MobileDevice) =>
    Modal.confirm({
      title: t("mobileAccess.revokeTitle", { name: device.name }),
      content: t("mobileAccess.revokeHint"),
      okText: t("mobileAccess.revoke"),
      cancelText: t("common.cancel"),
      okButtonProps: { danger: true },
      onOk: async () => {
        await mobileAccessApi.revoke(device.device_id);
        await refresh();
      },
    });
  const [serverUrl, setServerUrl] = useState(window.location.origin);
  const https = serverUrl.startsWith("https://");
  return (
    <PageShell
      title={t("mobileAccess.title")}
      subtitle={t("mobileAccess.subtitle")}
      actions={
        <Button onClick={() => void refresh()} loading={loading}>
          {t("common.refresh")}
        </Button>
      }
    >
      <Space
        direction="vertical"
        size="middle"
        style={{ width: "100%", padding: 16 }}
      >
        <Alert
          type={https ? "info" : "warning"}
          showIcon
          message={t(
            https ? "mobileAccess.howTo" : "mobileAccess.httpsRequired",
          )}
        />
        <RemoteSetup onAddress={setServerUrl} />
        <Card title={t("mobileAccess.serverAddress")}>
          <Space wrap align="start" size="large">
            <QRCodeSVG
              value={serverUrl}
              size={112}
              aria-label={t("mobileAccess.addressQr")}
            />
            <Space direction="vertical">
              <Typography.Text copyable code>
                {serverUrl}
              </Typography.Text>
              <Typography.Paragraph type="secondary" style={{ maxWidth: 480 }}>
                {t("mobileAccess.addressHint")}
              </Typography.Paragraph>
            </Space>
          </Space>
        </Card>
        <Card title={t("mobileAccess.approveDevice")}>
          <Space.Compact style={{ maxWidth: 400, width: "100%" }}>
            <Input
              aria-label={t("mobileAccess.pairingCode")}
              placeholder="ABCD-EFGH"
              value={code}
              maxLength={20}
              onChange={(event) => setCode(event.target.value.toUpperCase())}
              onPressEnter={() => void inspect()}
            />
            <Button
              loading={busy}
              disabled={code.replace(/[\s-]/g, "").length !== 8}
              onClick={() => void inspect()}
            >
              {t("mobileAccess.inspect")}
            </Button>
          </Space.Compact>
        </Card>
        <Table<MobileDevice>
          size="small"
          rowKey="device_id"
          loading={loading}
          dataSource={devices}
          pagination={false}
          scroll={{ x: 720 }}
          columns={[
            {
              title: t("mobileAccess.device"),
              key: "name",
              render: (_, device) => (
                <Space direction="vertical" size={0}>
                  <Typography.Text>{device.name}</Typography.Text>
                  <Typography.Text type="secondary">
                    {device.platform}
                  </Typography.Text>
                </Space>
              ),
            },
            {
              title: t("mobileAccess.capabilities"),
              key: "scopes",
              render: (_, device) => (
                <Space size={4} wrap>
                  {device.scopes.map((scope) => (
                    <Tag key={scope}>{t(`mobileAccess.scope.${scope}`)}</Tag>
                  ))}
                </Space>
              ),
            },
            {
              title: t("mobileAccess.expiry"),
              key: "expires_at",
              render: (_, device) =>
                formatServerDateTime(device.expires_at, timezone),
            },
            {
              title: t("mobileAccess.status"),
              key: "status",
              render: (_, device) => (
                <Tag
                  color={
                    device.revoked_at || device.expires_at <= Date.now() / 1000
                      ? "default"
                      : "green"
                  }
                >
                  {t(
                    device.revoked_at
                      ? "mobileAccess.revoked"
                      : device.expires_at <= Date.now() / 1000
                      ? "mobileAccess.expired"
                      : "mobileAccess.active",
                  )}
                </Tag>
              ),
            },
            {
              title: "",
              key: "actions",
              render: (_, device) => (
                <Button
                  danger
                  size="small"
                  disabled={!!device.revoked_at}
                  onClick={() => revoke(device)}
                >
                  {t("mobileAccess.revoke")}
                </Button>
              ),
            },
          ]}
        />
        {user?.role === "admin" && <PushConfiguration />}
        <Typography.Paragraph type="secondary">
          {t("mobileAccess.notificationHint")}
        </Typography.Paragraph>
      </Space>
      <Modal
        open={!!preview}
        title={t("mobileAccess.confirmTitle")}
        onCancel={() => !busy && setPreview(null)}
        onOk={() => void approve()}
        confirmLoading={busy}
        okButtonProps={{ disabled: scopes.length === 0 }}
        okText={t("mobileAccess.approve")}
      >
        {preview && (
          <Space direction="vertical" size="middle" style={{ width: "100%" }}>
            <Alert
              type="info"
              showIcon
              message={`${preview.name} · ${preview.platform}`}
              description={t("mobileAccess.confirmDeviceHint")}
            />
            <Typography.Text code copyable>
              {preview.host_fingerprint}
            </Typography.Text>
            <Typography.Text type="secondary">
              {t("mobileAccess.expiresAt", {
                time: formatServerDateTime(preview.expires_at, timezone),
              })}
            </Typography.Text>
            <Checkbox.Group
              value={scopes}
              onChange={(value) => setScopes(value as MobileScope[])}
              options={(
                [
                  "chat",
                  "files",
                  "notifications",
                  "tasks",
                  ...Object.keys(controlPermissions),
                ] as MobileScope[]
              ).map((scope) => ({
                value: scope,
                label: t(`mobileAccess.scope.${scope}`),
                disabled:
                  scope === "tasks"
                    ? !allowed("tasks")
                    : scope in controlPermissions
                    ? !allowed(
                        controlPermissions[
                          scope as keyof typeof controlPermissions
                        ],
                      )
                    : false,
              }))}
            />
            <Typography.Paragraph type="secondary">
              {t("mobileAccess.capabilityHint")}
            </Typography.Paragraph>
          </Space>
        )}
      </Modal>
    </PageShell>
  );
}
