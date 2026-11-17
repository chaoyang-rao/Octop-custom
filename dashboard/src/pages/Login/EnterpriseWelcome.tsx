import { useEffect, useState } from "react";
import { Alert, Button, Card, Space, Spin, Steps, Typography } from "antd";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { providerApi } from "../../api/modules/provider";
import { octopAgentsApi } from "../../api/modules/octopAgents";
import { useCurrentUser } from "../../hooks/useCurrentUser";
import { apiErrorMessage } from "../../utils/apiError";
import styles from "./enterprise.module.less";

/** Signed-in employees wait here for usable models and their primary expert. */
export default function EnterpriseWelcome() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const user = useCurrentUser();
  const [stage, setStage] = useState(0),
    [error, setError] = useState(""),
    [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const started = Date.now();
    let primary: string | undefined;
    setStage(0);
    setError("");
    const prepare = async () => {
      try {
        if (!primary) {
          const models = await providerApi.listResolvedModels();
          if (disposed) return;
          if (!models.length) {
            if (Date.now() - started > 90_000)
              throw new Error(t("enterprise.prepareModelsUnavailable"));
            timer = setTimeout(() => void prepare(), 3000);
            return;
          }
          setStage(1);
          primary = (await octopAgentsApi.ensurePrimary()).agent_id;
          // Assign the member default to a newly-created primary as well.
          await providerApi.listResolvedModels();
        }
        const status = await octopAgentsApi.preparationStatus(primary);
        if (disposed) return;
        if (status.state === "running") {
          setStage(2);
          navigate(`/chat/${primary}`, { replace: true });
          return;
        }
        if (status.state === "failed" || Date.now() - started > 90_000)
          throw new Error(t("enterprise.prepareExpertUnavailable"));
        timer = setTimeout(() => void prepare(), 1000);
      } catch (err) {
        if (!disposed)
          setError(apiErrorMessage(err, t("enterprise.prepareFailed"), t));
      }
    };
    void prepare();
    return () => {
      disposed = true;
      if (timer) clearTimeout(timer);
    };
  }, [attempt, navigate, t]);
  return (
    <main className={styles.page}>
      <Card className={styles.card}>
        <Space direction="vertical" size="large" className={styles.content}>
          <div>
            <Typography.Title level={1}>
              {t("enterprise.prepareTitle", { name: user?.display_name || "" })}
            </Typography.Title>
            <Typography.Paragraph>
              {t("enterprise.prepareHint")}
            </Typography.Paragraph>
          </div>
          <Steps
            direction="vertical"
            current={stage}
            status={error ? "error" : "process"}
            items={[
              {
                title: t("enterprise.prepareModels"),
                description: t("enterprise.prepareModelsHint"),
              },
              {
                title: t("enterprise.prepareExpert"),
                description: t("enterprise.prepareExpertHint"),
              },
              {
                title: t("enterprise.prepareChat"),
                description: t("enterprise.prepareChatHint"),
              },
            ]}
          />
          {error ? (
            <>
              <Alert
                role="alert"
                type="error"
                showIcon
                message={error}
                description={t("enterprise.prepareRecoveryHint")}
              />
              <Button type="primary" onClick={() => setAttempt((v) => v + 1)}>
                {t("common.retry")}
              </Button>
            </>
          ) : (
            <div role="status" aria-live="polite">
              <Spin size="small" /> {t("enterprise.preparing")}
            </div>
          )}
          <Typography.Text type="secondary">
            {t("enterprise.toolsAccessHint")}
          </Typography.Text>
        </Space>
      </Card>
    </main>
  );
}
