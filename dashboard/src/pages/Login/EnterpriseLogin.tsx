import { useEffect, useState } from "react";
import { Alert, Button, Card, Checkbox, Space, Steps, Typography } from "antd";
import { getAuthToken } from "../../api/request";
import { useTranslation } from "react-i18next";
import {
  enterpriseApi,
  type EnterpriseChallenge,
} from "../../api/modules/enterprise";
import { apiErrorMessage, parseApiError } from "../../utils/apiError";
import styles from "./enterprise.module.less";
import { enterpriseVerificationUrl } from "../../utils/enterpriseApproval";

export default function EnterpriseLogin({
  authority,
  localLoginAvailable = false,
  remember = true,
  onRememberChange,
  onSuccess,
}: {
  authority: string;
  localLoginAvailable?: boolean;
  remember?: boolean;
  onRememberChange?: (remember: boolean) => void;
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
      const next = await enterpriseApi.begin(
        t(
          (window as Window & { __DORA_CLIENT__?: boolean }).__DORA_CLIENT__
            ? "companion.deviceName"
            : "enterprise.deviceName",
        ),
        bindCurrent,
      );
      setChallenge(next);
      // The desktop bridge opens this in the system browser. Browser users
      // retain the ordinary link below if their popup policy blocks opening.
      window.open(
        enterpriseVerificationUrl(next.verification_uri, next.user_code),
        "_blank",
        "noopener,noreferrer",
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
          </div>
          <Steps
            size="small"
            current={challenge ? 1 : 0}
            items={[
              { title: t("enterprise.stepSignIn") },
              { title: t("enterprise.stepConfirm") },
              { title: t("enterprise.stepReady") },
            ]}
          />
          {error && <Alert role="alert" type="error" message={error} />}
          {!challenge && (getAuthToken() || localLoginAvailable) && (
            <details className={styles.details}>
              <summary>{t("enterprise.existingAccount")}</summary>
              {getAuthToken() && (
                <Checkbox
                  checked={bindCurrent}
                  onChange={(event) => setBindCurrent(event.target.checked)}
                >
                  {t("enterprise.keepLocalAccount")}
                </Checkbox>
              )}
              {localLoginAvailable && (
                <Button href="/login?local_link=1">
                  {t("enterprise.verifyLocalAccount")}
                </Button>
              )}
            </details>
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
              <Alert
                type="info"
                showIcon
                message={t("enterprise.browserStep")}
                description={t("enterprise.browserStepHint")}
              />
              <Button
                type="primary"
                href={enterpriseVerificationUrl(
                  challenge.verification_uri,
                  challenge.user_code,
                )}
                target="_blank"
                rel="noopener noreferrer"
              >
                {t("enterprise.openCenter")}
              </Button>
              <Typography.Text aria-live="polite">
                {t("enterprise.waiting")}
              </Typography.Text>
              <details className={styles.details}>
                <summary>{t("enterprise.codeFallback")}</summary>
                <Typography.Paragraph>
                  {t("enterprise.codeHint")}
                </Typography.Paragraph>
                <Typography.Text className={styles.code} copyable>
                  {challenge.user_code}
                </Typography.Text>
              </details>
              <Button onClick={() => void begin()} loading={busy}>
                {t("enterprise.restart")}
              </Button>
              <Button onClick={() => setChallenge(null)}>
                {t("enterprise.cancel")}
              </Button>
            </>
          ) : (
            <Button
              type="primary"
              size="large"
              block
              onClick={() => void begin()}
              loading={busy}
            >
              {t("enterprise.signIn")}
            </Button>
          )}
          {!challenge && onRememberChange && (
            <Checkbox
              checked={remember}
              onChange={(e) => onRememberChange(e.target.checked)}
            >
              {t("login.remember")}
            </Checkbox>
          )}
          <details className={styles.details}>
            <summary>{t("enterprise.connectionDetails")}</summary>
            <Typography.Text className={styles.authority}>
              {authority}
            </Typography.Text>
          </details>
        </Space>
      </Card>
    </main>
  );
}
