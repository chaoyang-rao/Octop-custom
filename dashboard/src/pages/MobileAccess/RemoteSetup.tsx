import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Input,
  Space,
  Tag,
  Typography,
  message,
} from "antd";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import {
  mobileRemoteApi,
  type RemoteCheck,
  type RemoteStatus,
} from "../../api/modules/mobileAccess";
import { useCurrentUser } from "../../hooks/useCurrentUser";

export default function RemoteSetup({
  onAddress,
}: {
  onAddress: (url: string) => void;
}) {
  const { t } = useTranslation();
  const user = useCurrentUser();
  const operator =
    user?.role === "admin" || !!user?.permissions?.includes("tls");
  const [status, setStatus] = useState<RemoteStatus | null>(null);
  const [url, setUrl] = useState("");
  const [check, setCheck] = useState<RemoteCheck | null>(null);
  const [busy, setBusy] = useState(false);
  const [tailscale, setTailscale] = useState<{
    authenticated: boolean;
    url: string | null;
    owned: boolean;
  } | null>(null);
  const refresh = useCallback(async () => {
    try {
      const result = await mobileRemoteApi.status();
      setStatus(result);
      setUrl(result.public_url ?? "");
      setCheck(result.last_check);
      if (result.public_url) onAddress(result.public_url);
    } catch {
      message.error(t("mobileAccess.remoteLoadFailed"));
    }
  }, [onAddress, t]);
  useEffect(() => {
    void refresh();
  }, [refresh]);
  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    try {
      await action();
    } catch {
      message.error(t("mobileAccess.remoteActionFailed"));
    } finally {
      setBusy(false);
    }
  };
  const save = () =>
    run(async () => {
      const result = await mobileRemoteApi.configure(url);
      onAddress(result.url);
      await refresh();
    });
  const diagnose = () =>
    run(async () => {
      setCheck(await mobileRemoteApi.check(url));
    });
  const tsStatus = () =>
    run(async () => {
      setTailscale(await mobileRemoteApi.tailscaleStatus());
    });
  const enable = () =>
    run(async () => {
      const result = await mobileRemoteApi.enableTailscale();
      onAddress(result.url);
      await refresh();
      setTailscale(await mobileRemoteApi.tailscaleStatus());
    });
  const disable = () =>
    run(async () => {
      await mobileRemoteApi.disableTailscale();
      setTailscale(await mobileRemoteApi.tailscaleStatus());
      await refresh();
    });
  return (
    <Card title={t("mobileAccess.remoteSetup")}>
      <Space direction="vertical" style={{ width: "100%" }} size="middle">
        <Typography.Paragraph>
          {t("mobileAccess.remoteSetupHint")}
        </Typography.Paragraph>
        <Space.Compact style={{ width: "100%", maxWidth: 780 }}>
          <Input
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            placeholder="https://your-octop.example"
            aria-label={t("mobileAccess.publicUrl")}
            disabled={!operator}
          />
          <Button
            onClick={() => void save()}
            disabled={!operator || !url}
            loading={busy}
          >
            {t("common.save")}
          </Button>
          <Button
            onClick={() => void diagnose()}
            disabled={!operator || !url}
            loading={busy}
          >
            {t("mobileAccess.checkConnection")}
          </Button>
        </Space.Compact>
        {status && (
          <Typography.Text type="secondary">
            {t("mobileAccess.localListener")}:{" "}
            <Typography.Text code>{status.listener}</Typography.Text>
          </Typography.Text>
        )}
        {check && (
          <Alert
            type={check.ok ? "success" : "warning"}
            showIcon
            message={t(
              `mobileAccess.checkReason.${check.reason}`,
              check.reason,
            )}
            description={
              <Space wrap>
                <Tag color={check.dns ? "green" : "default"}>DNS</Tag>
                <Tag color={check.tls ? "green" : "default"}>TLS</Tag>
                <Tag color={check.identity_matches ? "green" : "default"}>
                  {t("mobileAccess.hostIdentity")}
                </Tag>
              </Space>
            }
          />
        )}
        {operator && (
          <Space wrap>
            <Link to="/admin/advanced?tab=https">
              {t("mobileAccess.openTls")}
            </Link>
            <Typography.Link
              href="https://github.com/chaoyang-rao/Octop-custom/tree/custom/main/clients/mobile"
              target="_blank"
              rel="noreferrer"
            >
              {t("mobileAccess.deploymentGuide")}
            </Typography.Link>
          </Space>
        )}
        {operator && (
          <Card size="small" title="Tailscale Serve">
            <Space direction="vertical" style={{ width: "100%" }}>
              <Typography.Paragraph type="secondary">
                {t("mobileAccess.tailscaleHint")}
              </Typography.Paragraph>
              <Space wrap>
                <Tag color={status?.tailscale_installed ? "green" : "default"}>
                  {t(
                    status?.tailscale_installed
                      ? "mobileAccess.cliInstalled"
                      : "mobileAccess.cliMissing",
                  )}
                </Tag>
                <Button
                  size="small"
                  disabled={!status?.tailscale_installed}
                  onClick={() => void tsStatus()}
                  loading={busy}
                >
                  {t("mobileAccess.inspectTailscale")}
                </Button>
                <Typography.Link
                  href="https://tailscale.com/download"
                  target="_blank"
                  rel="noreferrer"
                >
                  {t("mobileAccess.installTailscale")}
                </Typography.Link>
              </Space>
              {tailscale && (
                <Alert
                  type={tailscale.authenticated ? "info" : "warning"}
                  message={t(
                    tailscale.authenticated
                      ? "mobileAccess.tailscaleSignedIn"
                      : "mobileAccess.tailscaleSignIn",
                  )}
                />
              )}
              <Space wrap>
                <Button
                  disabled={
                    !status?.tailscale_installed || !tailscale?.authenticated
                  }
                  onClick={() => void enable()}
                  loading={busy}
                >
                  {t("mobileAccess.enableTailscale")}
                </Button>
                <Button
                  danger
                  disabled={!tailscale?.owned}
                  onClick={() => void disable()}
                  loading={busy}
                >
                  {t("mobileAccess.disableTailscale")}
                </Button>
              </Space>
            </Space>
          </Card>
        )}
      </Space>
    </Card>
  );
}
