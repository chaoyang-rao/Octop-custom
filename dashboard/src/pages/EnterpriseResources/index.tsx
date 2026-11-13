import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Empty,
  Modal,
  Radio,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
} from "antd";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import PageShell from "../../layouts/PageShell";
import {
  resourcesApi,
  decodeText,
  downloadResource,
  type ResourceNodeState,
  type ResourceDetail,
  type ResourceExportOption,
} from "../../api/modules/enterpriseResources";
import { apiErrorMessage } from "../../utils/apiError";
import { useServerTimezone } from "../../hooks/useServerTimezone";
import { formatServerDateTime } from "../../utils/formatMessageTime";

export default function EnterpriseResources() {
  const { t } = useTranslation();
  const zone = useServerTimezone();
  const [state, setState] = useState<ResourceNodeState | null>(null);
  const [options, setOptions] = useState<ResourceExportOption[]>([]);
  const [selected, setSelected] = useState<number>();
  const [detail, setDetail] = useState<ResourceDetail | null>(null);
  const [choices, setChoices] = useState<Record<string, "local" | "remote">>(
    {},
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const run = async (op: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await op();
    } catch (e) {
      setError(apiErrorMessage(e, t("enterpriseResources.syncFailed")));
    } finally {
      setBusy(false);
    }
  };
  const refresh = useCallback(async () => {
    try {
      setState(await resourcesApi.status());
    } catch (e) {
      setError(apiErrorMessage(e, t("enterpriseResources.syncFailed")));
    }
  }, [t]);
  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 15000);
    return () => clearInterval(timer);
  }, [refresh]);
  useEffect(() => {
    resourcesApi
      .exports()
      .then(setOptions)
      .catch((e) =>
        setError(apiErrorMessage(e, t("enterpriseResources.syncFailed"))),
      );
  }, [t]);
  function pathLabel(path: string) {
    const labels: Record<string, string> = {
      "@name": t("enterpriseResources.name"),
      "@description": t("enterpriseResources.description"),
      "@avatar": t("enterpriseResources.avatar"),
      "@skill_package_ids": t("enterpriseResources.skills"),
      "@mcp_servers": t("enterpriseResources.mcp"),
    };
    return labels[path] ?? path;
  }
  function preview(value: string | null) {
    if (value === null) return t("enterpriseResources.absent");
    return decodeText(value) ?? t("enterpriseResources.binary");
  }
  const problem =
    error ||
    (state?.error
      ? t(`apiErrors.${state.error}`, {
          defaultValue: t("enterpriseResources.syncFailed"),
        })
      : "");
  return (
    <PageShell
      title={t("enterpriseResources.title")}
      actions={
        <Button
          loading={busy}
          disabled={!state?.enabled}
          onClick={() =>
            void run(async () => setState(await resourcesApi.sync()))
          }
        >
          {t("enterpriseResources.sync")}
        </Button>
      }
    >
      <Space direction="vertical" size="middle" style={{ width: "100%" }}>
        <Alert
          showIcon
          type="info"
          message={t("enterpriseResources.nodeHint")}
        />
        {problem && (
          <div role="alert">
            <Alert showIcon type="error" message={problem} />
          </div>
        )}
        {!state && !error && <Spin />}
        {state && !state.enabled && (
          <Alert
            type="warning"
            message={t("enterpriseResources.notConfigured")}
          />
        )}
        {state && (
          <Space wrap>
            <Tag>
              {t("enterpriseResources.version", { revision: state.revision })}
            </Tag>
            <Typography.Text type="secondary">
              {state.last_synced_at
                ? t("enterpriseResources.lastSync", {
                    time: formatServerDateTime(state.last_synced_at, zone),
                  })
                : t("enterpriseResources.waitingSync")}
            </Typography.Text>
          </Space>
        )}
        {state?.resources.length === 0 && (
          <Empty description={t("enterpriseResources.noResources")} />
        )}
        {state?.resources.map((item) => (
          <Card
            key={item.resource_id}
            size="small"
            title={
              <Space wrap>
                <Tag>{t(`enterpriseResources.${item.kind}`)}</Tag>
                <span>{item.display_name}</span>
                <Tag
                  color={
                    item.status === "conflict" || item.status === "error"
                      ? "orange"
                      : item.status === "current"
                      ? "green"
                      : "blue"
                  }
                >
                  {t(
                    `enterpriseResources.status.${
                      !item.enabled
                        ? "retired"
                        : item.paused
                        ? "paused"
                        : item.status
                    }`,
                  )}
                </Tag>
              </Space>
            }
          >
            <Space direction="vertical" style={{ width: "100%" }}>
              {item.local_modified && (
                <Tag>{t("enterpriseResources.localModified")}</Tag>
              )}
              {item.error && (
                <Alert
                  type="warning"
                  showIcon
                  message={t(`apiErrors.${item.error}`, {
                    defaultValue: t("enterpriseResources.syncFailed"),
                  })}
                />
              )}
              {item.conflicts.length > 0 && (
                <Typography.Text>
                  {t("enterpriseResources.conflictCount", {
                    count: item.conflicts.length,
                  })}
                  : {item.conflicts.map(pathLabel).join(", ")}
                </Typography.Text>
              )}
              <Space wrap>
                {item.target_id && (
                  <Link
                    to={
                      item.kind === "expert"
                        ? `/chat/${item.target_id}`
                        : "/skill-packages"
                    }
                  >
                    {t("enterpriseResources.openLocal")}
                  </Link>
                )}
                {item.enabled && item.target_id && (
                  <Button
                    disabled={busy}
                    onClick={() =>
                      void run(async () => {
                        setDetail(await resourcesApi.detail(item.resource_id));
                        setChoices({});
                      })
                    }
                  >
                    {t(
                      item.status === "conflict"
                        ? "enterpriseResources.resolve"
                        : "enterpriseResources.inspect",
                    )}
                  </Button>
                )}
                {item.enabled && item.target_id && (
                  <Button
                    disabled={busy}
                    onClick={() =>
                      void run(async () =>
                        setState(
                          await resourcesApi.pause(
                            item.resource_id,
                            !item.paused,
                          ),
                        ),
                      )
                    }
                  >
                    {t(
                      item.paused
                        ? "enterpriseResources.resume"
                        : "enterpriseResources.pause",
                    )}
                  </Button>
                )}
              </Space>
            </Space>
          </Card>
        ))}
        <Card size="small" title={t("enterpriseResources.exportTitle")}>
          <Typography.Paragraph type="secondary">
            {t("enterpriseResources.exportHint")}
          </Typography.Paragraph>
          <Space wrap>
            <Select
              style={{ minWidth: 260, maxWidth: "100%" }}
              aria-label={t("enterpriseResources.exportTitle")}
              value={selected}
              onChange={setSelected}
              options={options.map((v, i) => ({
                label: `${t(`enterpriseResources.${v.kind}`)} · ${v.name}`,
                value: i,
              }))}
            />
            <Button
              disabled={busy || selected === undefined}
              onClick={() =>
                void run(async () => {
                  if (selected !== undefined)
                    downloadResource(
                      await resourcesApi.export(options[selected]),
                    );
                })
              }
            >
              {t("enterpriseResources.export")}
            </Button>
          </Space>
        </Card>
      </Space>
      <Modal
        open={!!detail}
        title={t("enterpriseResources.resolve")}
        width={1100}
        maskClosable={false}
        onCancel={() => setDetail(null)}
        cancelButtonProps={{ disabled: busy }}
        closable={!busy}
        confirmLoading={busy}
        okText={t("enterpriseResources.applyChoices")}
        okButtonProps={{
          disabled:
            !detail?.conflicts.length ||
            detail.conflicts.some((c) => !choices[c.path]),
        }}
        onOk={() =>
          void run(async () => {
            if (detail) {
              setState(
                await resourcesApi.resolve(
                  detail.resource_id,
                  detail.ticket,
                  choices,
                ),
              );
              setDetail(null);
            }
          })
        }
      >
        {error && (
          <div role="alert">
            <Alert type="error" message={error} style={{ marginBottom: 16 }} />
          </div>
        )}
        <Alert
          showIcon
          type="info"
          message={t("enterpriseResources.conflictHint")}
          style={{ marginBottom: 16 }}
        />
        {detail?.conflicts.length === 0 && (
          <Alert
            type="success"
            message={t("enterpriseResources.noConflicts")}
          />
        )}
        {detail?.conflicts.map((c) => (
          <Card
            key={c.path}
            size="small"
            title={pathLabel(c.path)}
            style={{ marginBottom: 16 }}
          >
            <div
              style={{
                display: "grid",
                gridTemplateColumns:
                  "repeat(auto-fit, minmax(min(220px, 100%), 1fr))",
                gap: 12,
              }}
            >
              {(["base", "local", "remote"] as const).map((side) => (
                <section key={side}>
                  <Typography.Text strong>
                    {t(`enterpriseResources.${side}`)}
                  </Typography.Text>
                  <pre
                    style={{
                      whiteSpace: "pre-wrap",
                      overflowWrap: "anywhere",
                      maxHeight: 240,
                      overflow: "auto",
                      padding: 12,
                      background: "var(--fn-bg-layout)",
                      borderRadius: 8,
                    }}
                  >
                    {preview(c[side])}
                  </pre>
                </section>
              ))}
            </div>
            <Radio.Group
              aria-label={c.path}
              value={choices[c.path]}
              disabled={busy}
              onChange={(e) =>
                setChoices((current) => ({
                  ...current,
                  [c.path]: e.target.value,
                }))
              }
              options={[
                { label: t("enterpriseResources.keepLocal"), value: "local" },
                { label: t("enterpriseResources.useRemote"), value: "remote" },
              ]}
            />
          </Card>
        ))}
        {!detail?.conflicts.length && detail && (
          <Space direction="vertical" style={{ width: "100%", marginTop: 12 }}>
            {Object.entries(detail.local_files).map(([path, value]) => (
              <details key={path}>
                <summary style={{ cursor: "pointer" }}>{path}</summary>
                <pre
                  style={{
                    whiteSpace: "pre-wrap",
                    overflowWrap: "anywhere",
                    maxHeight: 240,
                    overflow: "auto",
                  }}
                >
                  {preview(value)}
                </pre>
              </details>
            ))}
          </Space>
        )}
      </Modal>
    </PageShell>
  );
}
