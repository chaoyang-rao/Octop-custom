import { Alert, Button, Checkbox, Space, Spin, Typography } from "antd";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { request } from "../../api/request";
import { message } from "../../utils/antdMessage";
import { apiErrorMessage } from "../../utils/apiError";
import type { ResourceEntry } from "../../api/modules/enterpriseResources";

interface State {
  etag: string;
  expert_ids: string[];
  experts: ResourceEntry[];
}
const endpoint = "/enterprise/companion/admin/experts";

export default function CompanionAdmin() {
  const { t } = useTranslation();
  const [state, setState] = useState<State>();
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function load() {
    setBusy(true);
    setError("");
    try {
      const next = await request<State>(endpoint);
      setState(next);
      setSelected(
        next.expert_ids.filter((id) =>
          next.experts.some((e) => e.resource_id === id && e.enabled),
        ),
      );
    } catch (e) {
      setError(apiErrorMessage(e, t("common.loadFailed"), t));
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    void load();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  async function save() {
    if (!state) return;
    setBusy(true);
    setError("");
    try {
      const next = await request<State>(endpoint, {
        method: "PUT",
        body: JSON.stringify({
          policy: { expert_ids: selected },
          expected_etag: state.etag,
        }),
      });
      setState(next);
      setSelected(next.expert_ids);
      message.success(t("companion.policySaved"));
    } catch (e) {
      setError(apiErrorMessage(e, t("common.saveFailed"), t));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }}>
      <Alert type="info" showIcon message={t("companion.policyHint")} />
      {error && <Alert type="error" showIcon message={error} />}
      <Spin spinning={busy}>
        <Checkbox.Group
          value={selected}
          onChange={(values) => setSelected(values as string[])}
          disabled={busy}
        >
          <Space direction="vertical" size="middle">
            {state?.experts.map((expert) => (
              <Checkbox
                key={expert.resource_id}
                value={expert.resource_id}
                disabled={!expert.enabled}
              >
                <strong>{expert.display_name}</strong>
                <Typography.Text
                  type="secondary"
                  style={{ marginInlineStart: 10 }}
                >
                  {expert.description}
                </Typography.Text>
              </Checkbox>
            ))}
          </Space>
        </Checkbox.Group>
        {state && !state.experts.length && (
          <Typography.Paragraph>
            {t("companion.publishFirst")}
          </Typography.Paragraph>
        )}
      </Spin>
      <Space>
        <Button
          type="primary"
          disabled={!state || busy}
          onClick={() => void save()}
        >
          {t("companion.savePolicy")}
        </Button>
        <Button disabled={busy} onClick={() => void load()}>
          {t("common.refresh")}
        </Button>
      </Space>
      <Typography.Text type="secondary">
        {t("companion.policyPreservesData")}
      </Typography.Text>
    </Space>
  );
}
