import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  List,
  Space,
  Typography,
} from "antd";
import { useTranslation } from "react-i18next";
import { authApi } from "../../api/modules/auth";
import { clearAuthToken } from "../../api/request";
import {
  enterpriseApi,
  type CompanyDevice,
} from "../../api/modules/enterprise";
import { useCurrentUser } from "../../hooks/useCurrentUser";
import { apiErrorMessage } from "../../utils/apiError";
import { parseApiError } from "../../utils/apiError";
import {
  enterpriseDeviceCode,
  enterpriseApprovalPath,
  enterpriseApprovalLoginPath,
} from "../../utils/enterpriseApproval";
import styles from "./enterprise.module.less";

export default function EnterpriseApprove() {
  const { t } = useTranslation();
  const user = useCurrentUser();
  const queryCode = enterpriseDeviceCode(
    new URLSearchParams(window.location.search).get("code"),
  );
  const [code, setCode] = useState(queryCode);
  const [preview, setPreview] = useState<{ name: string; code: string } | null>(
    null,
  );
  const [devices, setDevices] = useState<CompanyDevice[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  const [needsFeishu, setNeedsFeishu] = useState(false);
  const refresh = useCallback(
    async () => setDevices(await enterpriseApi.devices()),
    [],
  );
  useEffect(() => {
    void refresh().catch(() => {});
  }, [refresh]);

  useEffect(() => {
    if (!queryCode) return;
    let cancelled = false;
    setBusy(true);
    setError("");
    void enterpriseApi
      .inspect(queryCode)
      .then((value) => {
        if (!cancelled) setPreview({ ...value, code: queryCode });
      })
      .catch((err) => {
        if (!cancelled) {
          setError(apiErrorMessage(err, t("enterprise.failed"), t));
          setNeedsFeishu(
            parseApiError(err)?.code === "ENTERPRISE_FEISHU_REQUIRED",
          );
        }
      })
      .finally(() => {
        if (!cancelled) setBusy(false);
      });
    return () => {
      cancelled = true;
    };
  }, [queryCode, t]);

  const action = async (task: () => Promise<unknown>) => {
    setBusy(true);
    setError("");
    try {
      await task();
    } catch (err) {
      setError(apiErrorMessage(err, t("enterprise.failed"), t));
    } finally {
      setBusy(false);
    }
  };
  const bind = async () => {
    const { authorization_url } = await authApi.startOauthBind(
      "feishu",
      enterpriseApprovalPath(queryCode || code),
    );
    window.location.assign(authorization_url);
  };
  const switchAccount = async () => {
    const destination = `${enterpriseApprovalLoginPath(
      done ? undefined : queryCode || code,
    )}&switch_account=1`;
    setPreview(null);
    setDone(false);
    await authApi.logout();
    clearAuthToken();
    window.location.assign(destination);
  };

  return (
    <main className={styles.page}>
      <Card className={styles.card}>
        <Space direction="vertical" size="large" className={styles.content}>
          <div>
            <Typography.Title level={1}>
              {t("enterprise.approveTitle")}
            </Typography.Title>
            <Typography.Paragraph>
              {t("enterprise.approveHint")}
            </Typography.Paragraph>
            <Space wrap>
              <Typography.Text>
                {t("enterprise.currentAccount", {
                  name: user?.display_name || user?.username || "",
                })}
              </Typography.Text>
              <Button
                disabled={busy}
                onClick={() => void action(switchAccount)}
              >
                {t("enterprise.switchAccount")}
              </Button>
            </Space>
            <Typography.Paragraph type="secondary">
              {t(
                done
                  ? "enterprise.switchAfterApprovalHint"
                  : "enterprise.switchAccountHint",
              )}
            </Typography.Paragraph>
          </div>
          {error && <Alert role="alert" type="error" message={error} />}
          {done && (
            <Alert
              role="status"
              type="success"
              message={t("enterprise.approved")}
            />
          )}
          {!done && (
            <details className={styles.details} open={!queryCode || !!error}>
              <summary>{t("enterprise.codeFallback")}</summary>
              <Form
                layout="vertical"
                onFinish={() =>
                  void action(async () => {
                    setDone(false);
                    setPreview({
                      ...(await enterpriseApi.inspect(code)),
                      code,
                    });
                  })
                }
              >
                <Form.Item
                  label={t("enterprise.codeLabel")}
                  htmlFor="enterprise-device-code"
                >
                  <Input
                    id="enterprise-device-code"
                    aria-label={t("enterprise.codeLabel")}
                    value={code}
                    disabled={busy}
                    autoComplete="one-time-code"
                    maxLength={12}
                    onChange={(e) => {
                      setCode(e.target.value);
                      setPreview(null);
                      setDone(false);
                    }}
                  />
                </Form.Item>
                <Button
                  htmlType="submit"
                  loading={busy}
                  disabled={!code.trim()}
                >
                  {t("enterprise.inspect")}
                </Button>
              </Form>
            </details>
          )}
          {preview && (
            <>
              <Alert
                type="info"
                message={preview.name}
                description={t("enterprise.confirmHint")}
              />
              <Button
                type="primary"
                loading={busy}
                onClick={() =>
                  void action(async () => {
                    await enterpriseApi.approve(preview.code);
                    setPreview(null);
                    setDone(true);
                    await refresh();
                  })
                }
              >
                {t("enterprise.confirm")}
              </Button>
            </>
          )}
          {(needsFeishu ||
            !user?.sso_identities?.some(
              (identity) => identity.kind === "feishu",
            )) && (
            <Button onClick={() => void action(bind)}>
              {t("enterprise.bindFeishu")}
            </Button>
          )}
          {done && (
            <Typography.Paragraph>
              {t("enterprise.returnToApp")}
            </Typography.Paragraph>
          )}
          <details className={styles.details}>
            <summary>{t("enterprise.deviceManagement")}</summary>
            <Typography.Title level={2}>
              {t("enterprise.devices")}
            </Typography.Title>
            <List
              dataSource={devices}
              locale={{ emptyText: t("enterprise.noDevices") }}
              renderItem={(device) => (
                <List.Item
                  actions={[
                    <Button
                      key="revoke"
                      disabled={!!device.revoked_at || busy}
                      onClick={() =>
                        void action(async () => {
                          await enterpriseApi.revoke(device.device_id);
                          await refresh();
                        })
                      }
                    >
                      {device.revoked_at
                        ? t("enterprise.revoked")
                        : t("enterprise.revoke")}
                    </Button>,
                  ]}
                >
                  {device.name}
                </List.Item>
              )}
            />
            {(user?.role === "admin" ||
              user?.permissions?.includes("users")) && (
              <Button href="/enterprise/admin">{t("enterprise.manage")}</Button>
            )}
          </details>
        </Space>
      </Card>
    </main>
  );
}
