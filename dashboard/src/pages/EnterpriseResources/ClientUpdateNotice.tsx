import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Button, Card, Modal, Progress, Space, Typography } from "antd";
import { useTranslation } from "react-i18next";
import {
  clientUpdatesApi,
  installNativeClientUpdate,
  type ClientUpdateStatus,
} from "../../api/modules/clientUpdates";
import { useCurrentUser } from "../../hooks/useCurrentUser";
import { isDesktopShell } from "../../utils/desktopChrome";
import { apiErrorMessage } from "../../utils/apiError";

export default function ClientUpdateNotice() {
  const { t } = useTranslation();
  const user = useCurrentUser();
  const [state, setState] = useState<ClientUpdateStatus | null>(null);
  const [open, setOpen] = useState(false);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [dismissed, setDismissed] = useState<number | null>(null);
  const autoInstall = useRef(false);
  const installing = useRef(false);
  const load = useCallback(async () => {
    if (!isDesktopShell()) return;
    try {
      setState(await clientUpdatesApi.status());
    } catch {
      /* Polling recovers without interrupting chat. */
    }
  }, []);
  useEffect(() => {
    if (!user) return;
    void load();
    const timer = window.setInterval(() => void load(), open ? 1000 : 30000);
    return () => window.clearInterval(timer);
  }, [user, open, load]);
  useEffect(() => {
    const show = () => {
      setDismissed(null);
      setOpen(true);
      void clientUpdatesApi
        .check()
        .then(setState)
        .catch((err) =>
          setError(apiErrorMessage(err, t("clientUpdates.failed"), t)),
        );
    };
    window.addEventListener("octop:show-client-update", show);
    return () => window.removeEventListener("octop:show-client-update", show);
  }, [t]);
  const install = useCallback(
    async (id: string) => {
      if (installing.current) return;
      installing.current = true;
      setWorking(true);
      setError("");
      try {
        const ready = await clientUpdatesApi.prepare(id);
        try {
          await installNativeClientUpdate(ready.job_id);
        } catch (err) {
          await clientUpdatesApi.abort(id);
          throw err;
        }
      } catch (err) {
        autoInstall.current = false;
        installing.current = false;
        setError(apiErrorMessage(err, t("clientUpdates.failed"), t));
        setWorking(false);
        await load();
      }
    },
    [load, t],
  );
  useEffect(() => {
    if (!state?.job || state.job.phase !== "downloaded" || !autoInstall.current)
      return;
    if (state.busy) {
      autoInstall.current = false;
      return;
    }
    autoInstall.current = false;
    void install(state.job.id);
  }, [state, install]);
  async function download() {
    setWorking(true);
    setError("");
    autoInstall.current = true;
    try {
      setState(await clientUpdatesApi.download());
      setOpen(true);
    } catch (err) {
      autoInstall.current = false;
      setError(apiErrorMessage(err, t("clientUpdates.failed"), t));
    } finally {
      setWorking(false);
    }
  }
  if (!state?.supported) return null;
  const job = state.job;
  const applying =
    installing.current ||
    (!!job &&
      [
        "applying",
        "backing_up",
        "ready_to_swap",
        "installing",
        "starting",
        "candidate_ready",
        "rolling_back",
      ].includes(job.phase));
  const show = state.available && dismissed !== state.revision;
  return (
    <>
      {show && !open && (
        <Card
          size="small"
          style={{
            position: "fixed",
            right: 20,
            bottom: 24,
            maxWidth: 390,
            zIndex: 1200,
            boxShadow: "0 8px 28px #0002",
          }}
          aria-live="polite"
        >
          <Space direction="vertical">
            <Typography.Text strong>
              {t("clientUpdates.available", { version: state.version })}
            </Typography.Text>
            <Typography.Text type="secondary">
              {t("clientUpdates.memberHint")}
            </Typography.Text>
            {state.busy && (
              <Typography.Text>{t("clientUpdates.waitIdle")}</Typography.Text>
            )}
            <Space>
              <Button type="primary" onClick={() => setOpen(true)}>
                {t("clientUpdates.viewUpdate")}
              </Button>
              <Button onClick={() => setDismissed(state.revision)}>
                {t("clientUpdates.later")}
              </Button>
            </Space>
          </Space>
        </Card>
      )}
      <Modal
        title={t("clientUpdates.title")}
        open={open}
        onCancel={() => {
          if (!applying) {
            autoInstall.current = false;
            setOpen(false);
          }
        }}
        footer={null}
        closable={!applying}
        maskClosable={false}
      >
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          <Typography.Text>
            {state.current_version} → {state.version || job?.target_version}
          </Typography.Text>
          <Alert type="info" message={t("clientUpdates.memberHint")} />
          {state.busy && (
            <Alert type="warning" message={t("clientUpdates.waitIdle")} />
          )}
          {error && <Alert role="alert" type="error" message={error} />}
          {job?.error_code && (
            <Alert
              role="alert"
              type="error"
              message={t(`apiErrors.${job.error_code}`, {
                defaultValue: t("clientUpdates.failed"),
              })}
            />
          )}
          {job && (
            <>
              <Typography.Text role="status">
                {t(`clientUpdates.phases.${job.phase}`)}
              </Typography.Text>
              <Progress
                percent={Math.min(
                  100,
                  Math.round(
                    (job.downloaded_bytes / Math.max(1, job.total_bytes)) * 100,
                  ),
                )}
              />
            </>
          )}
          <Typography.Paragraph
            style={{
              whiteSpace: "pre-wrap",
              maxHeight: 220,
              overflowY: "auto",
            }}
          >
            {state.notes}
          </Typography.Paragraph>
          <Space wrap>
            {(!job ||
              ["failed", "rolled_back", "cancelled", "accepted"].includes(
                job.phase,
              )) && (
              <Button
                type="primary"
                disabled={state.busy || !state.available}
                loading={working}
                onClick={() => void download()}
              >
                {t("clientUpdates.upgrade")}
              </Button>
            )}
            {job && ["downloaded", "waiting_idle"].includes(job.phase) && (
              <Button
                type="primary"
                loading={working}
                disabled={state.busy || !state.available}
                onClick={() => void install(job.id)}
              >
                {t("clientUpdates.installRestart")}
              </Button>
            )}
            {job?.phase === "downloading" && (
              <Button
                onClick={() => {
                  autoInstall.current = false;
                  void clientUpdatesApi
                    .cancel(job.id)
                    .then(setState)
                    .catch((err) =>
                      setError(
                        apiErrorMessage(err, t("clientUpdates.failed"), t),
                      ),
                    );
                }}
              >
                {t("clientUpdates.cancelDownload")}
              </Button>
            )}
          </Space>
        </Space>
      </Modal>
    </>
  );
}
