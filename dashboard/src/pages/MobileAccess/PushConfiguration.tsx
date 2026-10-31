import { useEffect, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  Modal,
  Space,
  Switch,
  Tag,
  message,
} from "antd";
import { useTranslation } from "react-i18next";
import {
  mobilePushApi,
  type PushProviderConfig,
} from "../../api/modules/mobileAccess";

export default function PushConfiguration() {
  const { t } = useTranslation();
  const [configured, setConfigured] = useState({ apns: false, fcm: false });
  const [provider, setProvider] = useState<"apns" | "fcm" | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<PushProviderConfig>();
  useEffect(() => {
    void mobilePushApi
      .status()
      .then(setConfigured)
      .catch(() => undefined);
  }, []);
  const close = () => {
    if (saving) return;
    form.resetFields();
    setProvider(null);
  };
  const save = async () => {
    if (!provider) return;
    let values: PushProviderConfig;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    setSaving(true);
    try {
      setConfigured(
        await mobilePushApi.configure(provider, { ...values, enabled: true }),
      );
      form.resetFields();
      setProvider(null);
      message.success(t("mobileAccess.pushConfigSaved"));
    } catch {
      message.error(t("mobileAccess.pushConfigFailed"));
    } finally {
      setSaving(false);
    }
  };
  const disable = async (selected: "apns" | "fcm") => {
    try {
      setConfigured(
        await mobilePushApi.configure(selected, { enabled: false }),
      );
    } catch {
      message.error(t("mobileAccess.pushConfigFailed"));
    }
  };
  return (
    <Card title={t("mobileAccess.pushTitle")}>
      <Alert
        type="info"
        message={t("mobileAccess.pushHint")}
        style={{ marginBottom: 12 }}
      />
      <Space wrap>
        {(["apns", "fcm"] as const).map((key) => (
          <Space key={key}>
            <strong>{key.toUpperCase()}</strong>
            <Tag color={configured[key] ? "green" : "default"}>
              {t(
                configured[key]
                  ? "mobileAccess.pushReady"
                  : "mobileAccess.pushNotReady",
              )}
            </Tag>
            <Button
              size="small"
              onClick={() => {
                form.resetFields();
                setProvider(key);
              }}
            >
              {t("mobileAccess.configure")}
            </Button>
            {configured[key] && (
              <Button size="small" danger onClick={() => void disable(key)}>
                {t("mobileAccess.disablePush")}
              </Button>
            )}
          </Space>
        ))}
      </Space>
      <Modal
        open={provider != null}
        title={`${provider?.toUpperCase() ?? ""} · ${t(
          "mobileAccess.configure",
        )}`}
        onCancel={close}
        onOk={() => void save()}
        confirmLoading={saving}
        destroyOnHidden
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{ sandbox: true }}
          preserve={false}
        >
          {provider === "apns" ? (
            <>
              <Form.Item
                label="Team ID"
                name="team_id"
                rules={[{ required: true, pattern: /^[A-Z0-9]{10}$/ }]}
              >
                <Input autoComplete="off" />
              </Form.Item>
              <Form.Item
                label="Key ID"
                name="key_id"
                rules={[{ required: true, pattern: /^[A-Z0-9]{10}$/ }]}
              >
                <Input autoComplete="off" />
              </Form.Item>
              <Form.Item
                label={t("mobileAccess.bundleId")}
                name="topic"
                rules={[{ required: true }]}
              >
                <Input autoComplete="off" />
              </Form.Item>
              <Form.Item
                label={t("mobileAccess.sandbox")}
                name="sandbox"
                valuePropName="checked"
              >
                <Switch />
              </Form.Item>
            </>
          ) : (
            <>
              <Form.Item
                label={t("mobileAccess.projectId")}
                name="project_id"
                rules={[{ required: true }]}
              >
                <Input autoComplete="off" />
              </Form.Item>
              <Form.Item
                label={t("mobileAccess.serviceEmail")}
                name="client_email"
                rules={[{ required: true, type: "email" }]}
              >
                <Input autoComplete="off" />
              </Form.Item>
            </>
          )}
          <Form.Item
            name="private_key"
            label={t("mobileAccess.privateKey")}
            rules={[{ required: true }]}
          >
            <Input.TextArea rows={6} autoComplete="off" />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
