import {
  Alert,
  Button,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Spin,
  Switch,
  Typography,
} from "antd";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { request } from "../../api/request";
import { message } from "../../utils/antdMessage";
import { apiErrorMessage } from "../../utils/apiError";

interface State {
  etag: string;
  enabled: boolean;
  base_url: string;
  default_model: string;
  models: { id: string; enabled?: boolean }[];
  stream_usage: boolean;
  max_output_tokens: number;
  requests_per_minute: number;
  concurrent_per_user: number;
  key_configured: boolean;
}
const endpoint = "/enterprise/companion/admin/inference";

export default function InferenceAdmin() {
  const { t } = useTranslation();
  const [form] = Form.useForm();
  const [state, setState] = useState<State>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function load() {
    setBusy(true);
    setError("");
    try {
      const next = await request<State>(endpoint);
      setState(next);
      form.setFieldsValue(next);
    } catch (e) {
      setError(apiErrorMessage(e, t("companion.modelServiceLoadFailed"), t));
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    void load();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  async function save() {
    if (!state) return;
    let values;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    setBusy(true);
    setError("");
    try {
      const next = await request<State>(endpoint, {
        method: "PUT",
        body: JSON.stringify({
          expected_etag: state.etag,
          enabled: values.enabled,
          base_url: values.base_url,
          default_model: values.default_model,
          models: state.models,
          stream_usage: state.stream_usage,
          max_output_tokens: values.max_output_tokens,
          requests_per_minute: values.requests_per_minute,
          concurrent_per_user: values.concurrent_per_user,
          ...(values.api_key ? { api_key: values.api_key } : {}),
        }),
      });
      setState(next);
      form.setFieldsValue({ ...next, api_key: "" });
      message.success(t("companion.modelServiceSaved"));
    } catch (e) {
      setError(apiErrorMessage(e, t("common.saveFailed"), t));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Space
      direction="vertical"
      size="large"
      style={{ width: "100%", maxWidth: 760 }}
    >
      <Alert type="info" showIcon message={t("companion.modelServiceHint")} />
      {error && <Alert type="error" showIcon message={error} />}
      <Spin spinning={busy}>
        <Form form={form} layout="vertical" disabled={busy}>
          <Form.Item
            name="enabled"
            label={t("companion.modelServiceEnabled")}
            valuePropName="checked"
          >
            <Switch />
          </Form.Item>
          <Form.Item name="base_url" label={t("companion.modelServiceOrigin")}>
            <Input />
          </Form.Item>
          <Form.Item
            name="api_key"
            label={t("companion.modelServiceKey")}
            extra={t(
              state?.key_configured
                ? "companion.modelServiceKeyKeep"
                : "companion.modelServiceKeyNeeded",
            )}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item
            name="default_model"
            label={t("companion.modelServiceDefault")}
          >
            <Select
              options={state?.models
                .filter((m) => m.enabled !== false)
                .map((m) => ({ value: m.id, label: m.id }))}
            />
          </Form.Item>
          <Form.Item
            name="max_output_tokens"
            label={t("companion.modelServiceOutput")}
          >
            <InputNumber min={256} max={65536} />
          </Form.Item>
          <Form.Item
            name="requests_per_minute"
            label={t("companion.modelServiceRate")}
          >
            <InputNumber min={1} max={300} />
          </Form.Item>
          <Form.Item
            name="concurrent_per_user"
            label={t("companion.modelServiceParallel")}
          >
            <InputNumber min={1} max={8} />
          </Form.Item>
          <Space>
            <Button
              type="primary"
              disabled={!state || busy}
              onClick={() => void save()}
            >
              {t("companion.saveModelService")}
            </Button>
            <Button onClick={() => void load()} disabled={busy}>
              {t("common.refresh")}
            </Button>
          </Space>
        </Form>
      </Spin>
      <Typography.Text type="secondary">
        {t("companion.modelServicePrivacy")}
      </Typography.Text>
    </Space>
  );
}
