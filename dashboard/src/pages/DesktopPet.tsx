import { useEffect, useRef, useState } from "react";
import { Alert, Button, Card, Space, Spin, Typography } from "antd";
import { Bot } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useLocation } from "react-router-dom";
import { request } from "../api/request";
import { isCompanionSupported } from "../utils/desktopCompanion";
import { apiErrorMessage } from "../utils/apiError";

interface Access {
  allowed: boolean;
  managed: boolean;
  supported: boolean;
}
interface Launched {
  opened: boolean;
  installed: boolean;
  update_pending: boolean;
  version: string;
}
export default function DesktopPet() {
  const { t } = useTranslation();
  const location = useLocation();
  const [access, setAccess] = useState<Access>();
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [done, setDone] = useState<Launched>();
  const started = useRef(false);
  const supported = isCompanionSupported();
  async function launch() {
    setBusy(true);
    setError("");
    setDone(undefined);
    try {
      setDone(
        await request<Launched>("/companion/launch", {
          method: "POST",
          body: JSON.stringify({ action: "open" }),
        }),
      );
    } catch (e) {
      setError(apiErrorMessage(e, t("companion.prepareFailed"), t));
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    let live = true;
    request<Access>("/companion/access")
      .then((next) => {
        if (!live) return;
        setAccess(next);
        if (
          next.allowed &&
          next.supported &&
          supported &&
          new URLSearchParams(location.search).get("autostart") === "1" &&
          !started.current
        ) {
          started.current = true;
          void launch();
        }
      })
      .catch((e) => {
        if (live) setError(apiErrorMessage(e, t("common.loadFailed"), t));
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [location.search, supported]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <main style={{ maxWidth: 680, margin: "32px auto", padding: 20 }}>
      <Card>
        <Space direction="vertical" size="large" style={{ width: "100%" }}>
          <Bot size={32} aria-hidden />
          <Typography.Title level={2} style={{ margin: 0 }}>
            {t("companion.title")}
          </Typography.Title>
          <Typography.Paragraph>
            {t("companion.independentHint")}
          </Typography.Paragraph>
          {loading ? (
            <Spin />
          ) : !supported || access?.supported === false ? (
            <Alert type="info" message={t("companion.macOnly")} />
          ) : access && !access.allowed ? (
            <Alert
              role="alert"
              type="warning"
              message={t("companion.notOpened")}
              description={t("companion.contactAdmin")}
            />
          ) : null}
          {error && <Alert role="alert" type="error" message={error} />}{" "}
          {busy && (
            <Alert
              role="status"
              type="info"
              message={t("companion.preparing")}
              description={t("companion.firstInstallHint")}
            />
          )}{" "}
          {done && (
            <Alert
              role="status"
              type={done.update_pending ? "info" : "success"}
              message={t(
                done.update_pending
                  ? "companion.updatePending"
                  : "companion.opened",
              )}
              description={t("companion.independentHint")}
            />
          )}
          <Button
            type="primary"
            size="large"
            loading={busy}
            disabled={
              loading ||
              busy ||
              !supported ||
              !access?.allowed ||
              !access.supported
            }
            onClick={() => void launch()}
          >
            {t("companion.open")}
          </Button>
        </Space>
      </Card>
    </main>
  );
}
