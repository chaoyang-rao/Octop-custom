import { useEffect, useState } from "react";
import { Alert, Button, Card, Checkbox, Space, Typography } from "antd";
import { getAuthToken } from "../../api/request";
import { useTranslation } from "react-i18next";
import {
  enterpriseApi,
  type EnterpriseChallenge,
} from "../../api/modules/enterprise";
import { apiErrorMessage, parseApiError } from "../../utils/apiError";
import styles from "./enterprise.module.less";

export default function EnterpriseLogin({
  authority,
  localLoginAvailable = false,
  onSuccess,
}: {
  authority: string;
  localLoginAvailable?: boolean;
  onSuccess: (token: string, locale: string) => void | Promise<void>;
}) {
  const { t } = useTranslation();
  const [challenge, setChallenge] = useState<EnterpriseChallenge | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [bindCurrent, setBindCurrent] = useState(!!getAuthToken());
  const [confirmation, setConfirmation] = useState<{
    company: string;
    local: string;
  } | null>(null);

  const begin = async () => {
    setBusy(true);
    setError("");
    setChallenge(null);
    setConfirmation(null);
    try {
      setChallenge(
        await enterpriseApi.begin(t("enterprise.deviceName"), bindCurrent),
      );
    } catch (err) {
      setError(apiErrorMessage(err, t("enterprise.failed"), t));
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (!challenge) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const result = await enterpriseApi.poll(challenge.login_id);
        if (cancelled) return;
        if (result.status === "confirm") {
          setConfirmation({
            company: result.company_name || "",
            local: result.local_name || "",
          });
          return;
        }
        if (result.status === "expired") {
          setChallenge(null);
          setError(t("enterprise.expired"));
          return;
        }
        if (
          result.status === "approved" &&
          result.access_token &&
          result.user
        ) {
          await onSuccess(result.access_token, result.user.locale);
          return;
        }
        setError("");
      } catch (err) {
        if (cancelled) return;
        setError(apiErrorMessage(err, t("enterprise.failed"), t));
        const code = parseApiError(err)?.code;
        if (code && code !== "ENTERPRISE_UNAVAILABLE") {
          setChallenge(null);
          return;
        }
      }
      if (!cancelled)
        timer = setTimeout(() => void poll(), challenge.interval * 1000);
    };
    timer = setTimeout(() => void poll(), challenge.interval * 1000);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [challenge, onSuccess, t]);

  const confirmLink = async () => {
    if (!challenge) return;
    setBusy(true);
    setError("");
    try {
      const result = await enterpriseApi.poll(challenge.login_id, true);
      if (result.status === "approved" && result.access_token && result.user) {
        await onSuccess(result.access_token, result.user.locale);
      } else if (result.status === "expired") {
        setChallenge(null);
        setConfirmation(null);
        setError(t("enterprise.expired"));
      }
    } catch (err) {
      setError(apiErrorMessage(err, t("enterprise.failed"), t));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className={styles.page}>
      <Card className={styles.card}>
        <Space direction="vertical" size="large" className={styles.content}>
          <div>
            <Typography.Title level={1}>
              {t("enterprise.signIn")}
            </Typography.Title>
            <Typography.Paragraph>
              {t("enterprise.localHint")}
            </Typography.Paragraph>
            <Typography.Text className={styles.authority}>
              {authority}
            </Typography.Text>
          </div>
          {error && <Alert role="alert" type="error" message={error} />}
          {!challenge && getAuthToken() && (
            <Checkbox
              checked={bindCurrent}
              onChange={(event) => setBindCurrent(event.target.checked)}
            >
              {t("enterprise.keepLocalAccount")}
            </Checkbox>
          )}
          {!challenge && localLoginAvailable && (
            <Button href="/login?local_link=1">
              {t("enterprise.verifyLocalAccount")}
            </Button>
          )}
          {confirmation ? (
            <>
              <Alert
                type="info"
                message={t("enterprise.linkConfirm", confirmation)}
              />
              <Button
                type="primary"
                loading={busy}
                onClick={() => void confirmLink()}
              >
                {t("enterprise.confirmLink")}
              </Button>
              <Button
                onClick={() => {
                  setConfirmation(null);
                  setChallenge(null);
                }}
              >
                {t("enterprise.cancel")}
              </Button>
            </>
          ) : challenge ? (
            <>
              <Typography.Text>{t("enterprise.codeLabel")}</Typography.Text>
              <Typography.Text className={styles.code} copyable>
                {challenge.user_code}
              </Typography.Text>
              <Typography.Paragraph>
                {t("enterprise.codeHint")}
              </Typography.Paragraph>
              <Button
                type="primary"
                href={challenge.verification_uri}
                target="_blank"
                rel="noopener noreferrer"
              >
                {t("enterprise.openCenter")}
              </Button>
              <Typography.Text aria-live="polite">
                {t("enterprise.waiting")}
              </Typography.Text>
              <Button onClick={() => void begin()} loading={busy}>
                {t("enterprise.restart")}
              </Button>
              <Button onClick={() => setChallenge(null)}>
                {t("enterprise.cancel")}
              </Button>
            </>
          ) : (
            <Button type="primary" onClick={() => void begin()} loading={busy}>
              {t("enterprise.signIn")}
            </Button>
          )}
        </Space>
      </Card>
    </main>
  );
}
