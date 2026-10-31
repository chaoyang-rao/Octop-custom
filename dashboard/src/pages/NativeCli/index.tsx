import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Button,
  Form,
  Input,
  List,
  Popconfirm,
  Select,
  Space,
  Switch,
  Tag,
  Typography,
} from "antd";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";
import { useAgent } from "../../context/AgentContext";
import {
  nativeCliApi,
  type NativeCliInspection,
  type NativeCliView,
  type NativeCliConfig,
  type NativeCliCapabilities,
} from "../../api/modules/nativeCli";
import { ManagedCliPanel } from "./ManagedCliPanel";
import PageShell from "../../layouts/PageShell";
import { message } from "../../utils/antdMessage";
import { apiErrorMessage } from "../../utils/apiError";

export function NativeCliPanel({
  agentId: fixedAgentId,
}: { agentId?: string } = {}) {
  const { t } = useTranslation();
  const translateRef = useRef(t);
  translateRef.current = t;
  const { agents, activeAgentId, refresh: refreshAgents } = useAgent();
  const owned = useMemo(
    () =>
      agents.filter(
        (agent) =>
          agent.is_owner &&
          !agent.bridge &&
          agent.kind !== "team" &&
          !agent.is_shared,
      ),
    [agents],
  );
  const [selected, setSelected] = useState<string | undefined>(
    fixedAgentId ?? activeAgentId ?? undefined,
  );
  const [view, setView] = useState<NativeCliView | null>(null);
  const [busy, setBusy] = useState(false);
  const [inspection, setInspection] = useState<NativeCliInspection | null>(
    null,
  );
  const [capabilities, setCapabilities] =
    useState<NativeCliCapabilities | null>(null);
  const [form] = Form.useForm<NativeCliConfig>();
  const enabled = Form.useWatch("enabled", form);
  const runner = Form.useWatch("runner", form);
  const canManage = view?.can_manage !== false;
  const agentId =
    fixedAgentId ??
    (owned.some((agent) => agent.agent_id === selected)
      ? selected
      : owned[0]?.agent_id);
  const fail = useCallback((error: unknown) => {
    const translate = translateRef.current;
    message.error(
      apiErrorMessage(error, translate("common.unknownError"), translate),
    );
  }, []);
  const refresh = useCallback(async () => {
    if (!agentId) return;
    const next = await nativeCliApi.get(agentId);
    setView(next);
    form.setFieldsValue(next);
  }, [agentId, form]);
  useEffect(() => {
    if (!agentId) return;
    let active = true;
    setView(null);
    setInspection(null);
    setCapabilities(null);
    void nativeCliApi
      .get(agentId)
      .then((next) => {
        if (active) {
          setView(next);
          setCapabilities(next.capabilities ?? null);
          form.setFieldsValue(next);
        }
      })
      .catch((error) => {
        if (active) fail(error);
      });
    return () => {
      active = false;
    };
  }, [agentId, fail, form]);
  async function act(operation: () => Promise<unknown>) {
    setBusy(true);
    try {
      await operation();
    } catch (error) {
      fail(error);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Alert type="info" showIcon message={t("nativeCli.intro")} />
      {!fixedAgentId && (
        <Select
          style={{ width: "min(380px, 100%)" }}
          value={agentId}
          onChange={setSelected}
          placeholder={t("nativeCli.chooseExpert")}
          options={owned.map((agent) => ({
            value: agent.agent_id,
            label: agent.name,
          }))}
        />
      )}
      {agentId && view && (
        <>
          <Form
            form={form}
            layout="vertical"
            onFinish={(value) =>
              void act(async () => {
                setView(await nativeCliApi.save(agentId, value));
                await refreshAgents();
                message.success(t("nativeCli.saved"));
              })
            }
          >
            <Form.Item
              name="enabled"
              label={t("nativeCli.execution")}
              valuePropName="checked"
            >
              <Switch
                disabled={!canManage || busy}
                checkedChildren={t("nativeCli.native")}
                unCheckedChildren={t("nativeCli.api")}
              />
            </Form.Item>
            <Form.Item
              name="runner"
              label={t("nativeCli.runner")}
              rules={enabled ? [{ required: true }] : []}
            >
              <Select
                disabled={!enabled || busy || !canManage}
                options={view.runners.map((item) => ({
                  value: item.runner,
                  label: `${item.runner}${
                    item.enabled ? "" : ` · ${t("nativeCli.disabled")}`
                  }`,
                  disabled: !item.enabled,
                }))}
              />
            </Form.Item>
            <Form.Item
              name="model_id"
              label={t("nativeCli.model")}
              extra={t("nativeCli.modelHelp")}
            >
              {capabilities &&
              capabilities.runner === runner &&
              capabilities.models.length ? (
                <Select
                  disabled={!enabled || busy || !canManage}
                  allowClear
                  options={capabilities.models.map((choice) => ({
                    value: choice.value,
                    label: choice.name,
                  }))}
                />
              ) : (
                <Input
                  disabled={!enabled || busy || !canManage}
                  maxLength={200}
                />
              )}
            </Form.Item>
            <Form.Item
              name="mode_id"
              label={t("nativeCli.mode")}
              extra={t("nativeCli.modeHelp")}
            >
              {capabilities &&
              capabilities.runner === runner &&
              capabilities.modes.length ? (
                <Select
                  disabled={!enabled || busy || !canManage}
                  allowClear
                  options={capabilities.modes.map((choice) => ({
                    value: choice.value,
                    label: choice.name,
                  }))}
                />
              ) : (
                <Input
                  disabled={!enabled || busy || !canManage}
                  maxLength={100}
                />
              )}
            </Form.Item>
            {enabled && (
              <Alert
                type="info"
                message={t("nativeCli.permissionBoundary")}
                style={{ marginBottom: 16 }}
              />
            )}
            <Space wrap>
              <Button
                type="primary"
                htmlType="submit"
                loading={busy}
                disabled={!canManage}
              >
                {t("common.save")}
              </Button>
              <Button
                disabled={busy || !runner || !canManage || !view.enabled}
                onClick={() =>
                  runner &&
                  void act(async () =>
                    setCapabilities(await nativeCliApi.probe(agentId, runner)),
                  )
                }
              >
                {t("nativeCli.readCapabilities")}
              </Button>
              <Button
                disabled={busy || !runner || !canManage}
                onClick={() =>
                  runner &&
                  void act(async () =>
                    setInspection(await nativeCliApi.inspect(runner)),
                  )
                }
              >
                {t("nativeCli.inspect")}
              </Button>
              <Button disabled={busy} onClick={() => void act(refresh)}>
                {t("common.refresh")}
              </Button>
            </Space>
          </Form>
          {capabilities && capabilities.runner === runner && (
            <Alert
              type="info"
              message={t("nativeCli.capabilitiesRead")}
              description={
                <Space direction="vertical">
                  <span>{t("nativeCli.capabilitiesHelp")}</span>
                  <span>
                    {t("nativeCli.mediaCaps")}:{" "}
                    {capabilities.image ? t("nativeCli.image") : "—"} /{" "}
                    {capabilities.audio ? t("nativeCli.audio") : "—"} /{" "}
                    {capabilities.embedded_context
                      ? t("nativeCli.resources")
                      : "—"}
                  </span>
                  <Typography.Text code>
                    {capabilities.origin_cwd}
                  </Typography.Text>
                  {capabilities.config_options.map((option) => (
                    <Typography.Text key={option.id}>
                      {option.name}: {String(option.current_value)}
                    </Typography.Text>
                  ))}
                </Space>
              }
            />
          )}
          {inspection && (
            <Alert
              type="info"
              message={`${inspection.runner} · ${
                inspection.version ?? t("nativeCli.unknownVersion")
              }`}
              description={t(
                inspection.version_kind === "launcher"
                  ? "nativeCli.launcherVersion"
                  : "nativeCli.inspectionHelp",
              )}
            />
          )}
          {canManage ? (
            <ManagedCliPanel
              onRunner={(value) => {
                void refresh().then(() => form.setFieldValue("runner", value));
              }}
            />
          ) : (
            <Alert type="info" message={t("nativeCli.adminOnly")} />
          )}
          <List
            size="small"
            header={t("nativeCli.launchers")}
            dataSource={view.runners}
            renderItem={(item) => (
              <List.Item>
                <Space wrap>
                  <Typography.Text>{item.runner}</Typography.Text>
                  <Tag color={item.launcher_available ? "green" : "default"}>
                    {t(
                      item.launcher_available
                        ? "nativeCli.launcherPresent"
                        : "nativeCli.launcherMissing",
                    )}
                  </Tag>
                  <Typography.Text type="secondary" code>
                    {item.command}
                  </Typography.Text>
                  {item.uses_package_launcher && (
                    <Typography.Text type="secondary">
                      {t("nativeCli.packageNotProven")}
                    </Typography.Text>
                  )}
                </Space>
              </List.Item>
            )}
          />
          <List
            header={t("nativeCli.sessions")}
            dataSource={view.sessions}
            locale={{ emptyText: t("nativeCli.noSessions") }}
            renderItem={(session) => (
              <List.Item
                actions={[
                  <Popconfirm
                    key="close"
                    title={t("nativeCli.closeConfirm")}
                    onConfirm={() =>
                      act(async () => {
                        await nativeCliApi.close(agentId, session.thread_id);
                        await refresh();
                      })
                    }
                  >
                    <Button
                      danger
                      disabled={
                        busy ||
                        session.state === "working" ||
                        session.state === "waiting"
                      }
                    >
                      {t("nativeCli.close")}
                    </Button>
                  </Popconfirm>,
                ]}
              >
                <List.Item.Meta
                  title={
                    <Space>
                      {session.title}
                      <Tag
                        color={
                          session.state === "interrupted" ? "orange" : "default"
                        }
                      >
                        {t(`nativeCli.states.${session.state}`, session.state)}
                      </Tag>
                    </Space>
                  }
                  description={
                    <Typography.Text code>{session.cwd}</Typography.Text>
                  }
                />
              </List.Item>
            )}
          />
        </>
      )}
    </Space>
  );
}
export default function NativeCliPage() {
  const { t } = useTranslation();
  const [params] = useSearchParams();
  return (
    <PageShell title={t("nativeCli.title")}>
      <NativeCliPanel agentId={params.get("agent") || undefined} />
    </PageShell>
  );
}
