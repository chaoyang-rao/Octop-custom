import { useEffect, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import { useTranslation } from "react-i18next";
import {
  clientUpdatesApi,
  type ClientUpdateAdmin as AdminState,
  type ClientReleaseOption,
} from "../../api/modules/clientUpdates";
import {
  enterpriseMcpApi,
  type EnterpriseMcpMember,
} from "../../api/modules/enterpriseMcp";
import { apiErrorMessage } from "../../utils/apiError";
import { useServerTimezone } from "../../hooks/useServerTimezone";
import { formatServerDateTime } from "../../utils/formatMessageTime";

export default function ClientUpdateAdmin() {
  const { t } = useTranslation();
  const timezone = useServerTimezone();
  const [state, setState] = useState<AdminState | null>(null);
  const [releases, setReleases] = useState<ClientReleaseOption[]>([]);
  const [tag, setTag] = useState<string>();
  const [members, setMembers] = useState<EnterpriseMcpMember[]>([]);
  const [audience, setAudience] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (err) {
      setError(apiErrorMessage(err, t("clientUpdates.failed"), t));
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    void run(async () => {
      const [next, people] = await Promise.all([
        clientUpdatesApi.admin(),
        enterpriseMcpApi.members(),
      ]);
      setState(next);
      setMembers(people);
    });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }}>
      <Alert type="info" showIcon message={t("clientUpdates.adminHint")} />
      {error && <Alert role="alert" type="error" message={error} />}
      {state && !state.signing_configured && (
        <Alert type="warning" message={t("clientUpdates.noSigner")} />
      )}
      <Card title={t("clientUpdates.publishTitle")}>
        <Space direction="vertical" style={{ width: "100%" }}>
          <Space wrap>
            <Button
              loading={busy}
              onClick={() =>
                void run(async () =>
                  setReleases(await clientUpdatesApi.releases()),
                )
              }
            >
              {t("clientUpdates.findReleases")}
            </Button>
            <Select
              aria-label={t("clientUpdates.selectRelease")}
              placeholder={t("clientUpdates.selectRelease")}
              value={tag}
              style={{ minWidth: 280 }}
              options={releases.map((item) => ({
                value: item.tag,
                label: item.version,
              }))}
              onChange={setTag}
            />
            <Button
              disabled={!tag || !state || busy}
              onClick={() =>
                void run(async () =>
                  setState(await clientUpdatesApi.import(tag!, state!.etag)),
                )
              }
            >
              {t("clientUpdates.importDraft")}
            </Button>
          </Space>
          {releases.length === 0 && (
            <Typography.Text type="secondary">
              {t("clientUpdates.completeReleaseOnly")}
            </Typography.Text>
          )}
          <Typography.Text>
            {t("clientUpdates.draftVersion")} {state?.draft?.version || "—"}
          </Typography.Text>
          <Select
            mode="multiple"
            allowClear
            aria-label={t("clientUpdates.audience")}
            placeholder={t("clientUpdates.allMembers")}
            value={audience}
            options={members.map((member) => ({
              value: member.subject,
              label: member.display_name,
            }))}
            onChange={setAudience}
            style={{ width: "100%" }}
          />
          <Space>
            <Button
              type="primary"
              loading={busy}
              disabled={!state?.draft || !state.signing_configured}
              onClick={() =>
                void run(async () =>
                  setState(
                    await clientUpdatesApi.publish(state!.etag, audience),
                  ),
                )
              }
            >
              {t("clientUpdates.publish")}
            </Button>
            <Button
              danger
              disabled={!state?.published?.release.enabled || busy}
              onClick={() =>
                void run(async () =>
                  setState(await clientUpdatesApi.withdraw(state!.etag)),
                )
              }
            >
              {t("clientUpdates.withdraw")}
            </Button>
            <Button
              disabled={busy}
              onClick={() =>
                void run(async () => setState(await clientUpdatesApi.admin()))
              }
            >
              {t("common.refresh")}
            </Button>
          </Space>
          <Typography.Text>
            {t("clientUpdates.currentRelease")}{" "}
            {state?.published?.release.version || "—"}{" "}
            {state?.published && !state.published.release.enabled && (
              <Tag>{t("clientUpdates.withdrawn")}</Tag>
            )}
          </Typography.Text>
        </Space>
      </Card>
      <Card title={t("clientUpdates.devicesTitle")}>
        <Alert
          type="info"
          message={t("clientUpdates.bootstrapHint")}
          style={{ marginBottom: 16 }}
        />
        <Table
          dataSource={state?.devices || []}
          rowKey="device_id"
          loading={busy}
          scroll={{ x: 860 }}
          pagination={{ pageSize: 15 }}
          columns={[
            { title: t("clientUpdates.member"), dataIndex: "display_name" },
            {
              title: t("clientUpdates.device"),
              render: (_, row) => (
                <>
                  <div>{row.device_name || row.device_id.slice(0, 12)}</div>
                  <Typography.Text type="secondary">
                    {row.platform}
                  </Typography.Text>
                </>
              ),
            },
            {
              title: t("clientUpdates.currentVersion"),
              dataIndex: "current_version",
            },
            {
              title: t("clientUpdates.targetVersion"),
              dataIndex: "target_version",
              render: (value) => value || "—",
            },
            {
              title: t("clientUpdates.phaseTitle"),
              dataIndex: "phase",
              render: (value) => (
                <Tag>{t(`clientUpdates.phases.${value}`)}</Tag>
              ),
            },
            {
              title: t("clientUpdates.lastSeen"),
              dataIndex: "last_seen_at",
              render: (value) => formatServerDateTime(value * 1000, timezone),
            },
            {
              title: t("clientUpdates.result"),
              dataIndex: "error_code",
              render: (value) =>
                value
                  ? t(`apiErrors.${value}`, {
                      defaultValue: t("clientUpdates.failed"),
                    })
                  : "—",
            },
          ]}
        />
      </Card>
    </Space>
  );
}
