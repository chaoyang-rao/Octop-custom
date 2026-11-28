import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Form, Button, Card } from "antd";
import { message } from "@/utils/antdMessage";

import { useTranslation } from "react-i18next";
import { request } from "../../../api/request";
import { AgentAdvancedConfigFields } from "../../../components/AgentAdvancedConfigFields";
import { useAgent } from "../../../context/AgentContext";
import { useUnsavedChanges } from "../../../context/UnsavedChangesContext";
import {
  AGENT_RUNTIME_CONFIG_KEYS,
  buildAgentRuntimeRequest,
  readAgentRuntimeFormValues,
  type AgentRuntimeFormValues,
} from "../../../utils/agentRuntimeConfig";
import styles from "./index.module.less";

function AgentConfigPage() {
  const { t } = useTranslation();
  const { activeAgent, activeAgentId, refresh } = useAgent();
  const [form] = Form.useForm<AgentRuntimeFormValues>();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<AgentRuntimeFormValues | null>(null);
  const loadedAgentId = useRef<string | null>(null);
  const current = Form.useWatch([], { form, preserve: true });
  const dirty =
    saved !== null &&
    current !== undefined &&
    AGENT_RUNTIME_CONFIG_KEYS.some(
      (key) => (current[key] ?? undefined) !== saved[key],
    );
  const handleReset = () => {
    if (saved) form.setFieldsValue(saved);
  };
  useUnsavedChanges(dirty, handleReset);
  const dirtyRef = useRef(dirty);
  useLayoutEffect(() => {
    dirtyRef.current = dirty;
  }, [dirty]);

  useEffect(() => {
    if (loadedAgentId.current === activeAgentId && dirtyRef.current) return;
    loadedAgentId.current = activeAgentId;
    if (!activeAgentId) {
      setLoading(false);
      setSaved(null);
      return;
    }
    setLoading(true);
    const values = readAgentRuntimeFormValues(activeAgent ?? {});
    form.setFieldsValue(values);
    setSaved(values);
    setLoading(false);
  }, [activeAgent, activeAgentId, form]);

  const handleSave = async () => {
    if (!activeAgentId) return;
    try {
      const values = await form.validateFields();
      const submitted = readAgentRuntimeFormValues(values);
      setSaving(true);
      await request(`/agents/${activeAgentId}`, {
        method: "PATCH",
        body: JSON.stringify({
          ...buildAgentRuntimeRequest(values, { clearMissing: true }),
        }),
      });
      await refresh({ silent: true, force: true });
      if (loadedAgentId.current === activeAgentId) setSaved(submitted);
      message.success(t("agentConfig.saveSuccess"));
    } catch (err) {
      if (err instanceof Error && "errorFields" in err) {
        return;
      }
      const errMsg =
        err instanceof Error ? err.message : t("agentConfig.saveFailed");
      message.error(errMsg);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className={styles.page}>
      {loading && (
        <div className={styles.centerState}>
          <span className={styles.stateText}>{t("common.loading")}</span>
        </div>
      )}

      {!activeAgentId && !loading && (
        <div className={styles.centerState}>
          <span className={styles.stateTextError}>
            {t("agentConfig.noActiveAgent")}
          </span>
        </div>
      )}

      <div style={{ display: loading || !activeAgentId ? "none" : "block" }}>
        <div className={styles.header}>
          <p className={styles.description}>{t("agentConfig.description")}</p>
        </div>

        <Card className={styles.formCard}>
          <Form form={form} layout="vertical" className={styles.form}>
            <AgentAdvancedConfigFields requireLimits />

            <Form.Item className={styles.buttonGroup}>
              <Button
                onClick={handleReset}
                disabled={saving}
                style={{ marginRight: 8 }}
              >
                {t("common.reset")}
              </Button>
              <Button type="primary" onClick={handleSave} loading={saving}>
                {t("common.save")}
              </Button>
            </Form.Item>
          </Form>
        </Card>
      </div>
    </div>
  );
}

export default AgentConfigPage;
