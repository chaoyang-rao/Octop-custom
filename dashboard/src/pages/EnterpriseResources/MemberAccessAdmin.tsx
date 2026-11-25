import { useEffect, useState } from "react";
import {
  Alert,
  Button,
  Checkbox,
  Collapse,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import { useTranslation } from "react-i18next";
import {
  memberAccessApi,
  type ManagedMcpId,
  type MemberAccessRow,
  type MemberAccessState,
} from "../../api/modules/memberAccess";
import { apiErrorMessage } from "../../utils/apiError";
import { message } from "../../utils/antdMessage";
import styles from "./MemberAccessAdmin.module.less";

const legacyIds: ManagedMcpId[] = [
  "aftersales-quality",
  "quota-workbench",
  "negative-profit",
];
export default function MemberAccessAdmin() {
  const { t } = useTranslation();
  const [state, setState] = useState<MemberAccessState>();
  const [members, setMembers] = useState<MemberAccessRow[]>([]);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [dirty, setDirty] = useState(false);
  const [service, setService] = useState<ManagedMcpId>();
  const [choices, setChoices] = useState<
    { account_id: string; label: string }[]
  >([]);
  const [account, setAccount] = useState<string>();
  const names: Record<ManagedMcpId, string> = {
    "aftersales-quality": t("memberAccess.aftersales"),
    "quota-workbench": t("memberAccess.workbench"),
    "negative-profit": t("memberAccess.negative"),
    ...Object.fromEntries(
      (state?.mcp_options || []).map((entry) => [
        entry.entry_id,
        entry.display_name,
      ]),
    ),
  };
  const ids = state?.mcp_options
    ? state.mcp_options.map((entry) => entry.entry_id)
    : legacyIds;
  function apply(next: MemberAccessState) {
    setState(next);
    setMembers(
      next.members.map((row) => ({ ...row, mcp_ids: [...row.mcp_ids] })),
    );
    setDirty(false);
    setError("");
  }
  async function load() {
    setBusy(true);
    try {
      apply(await memberAccessApi.read());
    } catch (e) {
      setError(apiErrorMessage(e, t("common.loadFailed"), t));
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    void load();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (busy || dirty) return;
    const timer = window.setInterval(() => void load(), 30_000);
    return () => window.clearInterval(timer);
  }, [busy, dirty]); // eslint-disable-line react-hooks/exhaustive-deps
  function change(user: number, id: ManagedMcpId | null, checked: boolean) {
    setMembers((rows) =>
      rows.map((row) =>
        row.user_id !== user
          ? row
          : id === null
          ? { ...row, companion: checked }
          : {
              ...row,
              mcp_ids: checked
                ? [...new Set([...row.mcp_ids, id])]
                : row.mcp_ids.filter((value) => value !== id),
            },
      ),
    );
    setDirty(true);
  }
  async function save() {
    if (!state) return;
    setBusy(true);
    try {
      apply(await memberAccessApi.save(members, state.etag));
      message.success(t("memberAccess.saved"));
    } catch (e) {
      setError(apiErrorMessage(e, t("common.saveFailed"), t));
    } finally {
      setBusy(false);
    }
  }
  async function configure(id: ManagedMcpId) {
    setService(id);
    setChoices([]);
    setAccount(undefined);
    setBusy(true);
    try {
      const result = await memberAccessApi.choices(id);
      setChoices(result.accounts);
      if (result.accounts.length === 1)
        setAccount(result.accounts[0].account_id);
    } catch (e) {
      setError(apiErrorMessage(e, t("common.loadFailed"), t));
    } finally {
      setBusy(false);
    }
  }
  async function connect() {
    if (!state || !service || !account) return;
    setBusy(true);
    try {
      apply(await memberAccessApi.connect(service, account, state.etag));
      setService(undefined);
      message.success(t("memberAccess.serviceSaved"));
    } catch (e) {
      setError(apiErrorMessage(e, t("common.saveFailed"), t));
    } finally {
      setBusy(false);
    }
  }
  const filtered = members.filter((row) =>
    `${row.display_name} ${row.username}`
      .toLocaleLowerCase()
      .includes(query.trim().toLocaleLowerCase()),
  );
  return (
    <section className={styles.panel} aria-labelledby="member-access-title">
      <div className={styles.intro}>
        <Typography.Title level={4} id="member-access-title">
          {t("memberAccess.title")}
        </Typography.Title>
        <Typography.Text type="secondary">
          {t("memberAccess.hint")}
        </Typography.Text>
      </div>
      {error && <Alert role="alert" type="error" message={error} />}
      <div className={styles.toolbar}>
        <Input.Search
          aria-label={t("memberAccess.search")}
          placeholder={t("memberAccess.search")}
          allowClear
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className={styles.search}
        />
        <Space wrap>
          <Button
            type="primary"
            disabled={!state || busy || !dirty}
            loading={busy}
            onClick={() => void save()}
          >
            {t("memberAccess.save")}
          </Button>
          <Button disabled={busy || dirty} onClick={() => void load()}>
            {t("memberAccess.refresh")}
          </Button>
          {dirty && state && (
            <Button disabled={busy} onClick={() => apply(state)}>
              {t("memberAccess.reset")}
            </Button>
          )}
        </Space>
      </div>
      <Table<MemberAccessRow>
        className={styles.table}
        rowKey="user_id"
        loading={busy}
        dataSource={filtered}
        size="middle"
        scroll={{ x: "max-content" }}
        pagination={{ pageSize: 20, hideOnSinglePage: true }}
        columns={[
          {
            title: t("memberAccess.member"),
            key: "member",
            fixed: "left",
            width: 190,
            render: (_, row) => (
              <Space direction="vertical" size={0}>
                <Typography.Text strong>{row.display_name}</Typography.Text>
                <Typography.Text type="secondary">
                  {row.username}
                </Typography.Text>
              </Space>
            ),
          },
          ...ids.map((id) => ({
            title: names[id],
            key: `mcp:${id}`,
            width: 150,
            align: "center" as const,
            render: (_: unknown, row: MemberAccessRow) => (
              <Checkbox
                aria-label={`${row.display_name} ${names[id]}`}
                disabled={busy || row.disabled || !row.verified}
                checked={row.mcp_ids.includes(id)}
                onChange={(event) =>
                  change(row.user_id, id, event.target.checked)
                }
              />
            ),
          })),
          {
            title: t("memberAccess.companion"),
            key: "companion",
            align: "center",
            render: (_, row) => (
              <Checkbox
                aria-label={`${row.display_name} ${t(
                  "memberAccess.companion",
                )}`}
                disabled={busy || row.disabled || !row.verified}
                checked={row.companion}
                onChange={(event) =>
                  change(row.user_id, null, event.target.checked)
                }
              />
            ),
          },
          {
            title: t("memberAccess.status"),
            key: "status",
            render: (_, row) => (
              <Tag
                color={
                  row.disabled ? "error" : row.verified ? "success" : "default"
                }
              >
                {t(
                  row.disabled
                    ? "memberAccess.disabled"
                    : row.verified
                    ? "memberAccess.verified"
                    : "memberAccess.notLinked",
                )}
              </Tag>
            ),
          },
        ]}
      />
      <Typography.Text type="secondary">
        {t("memberAccess.newMemberHint")}
      </Typography.Text>
      <Collapse
        items={[
          {
            key: "services",
            label: t("memberAccess.services"),
            children: (
              <Space direction="vertical" style={{ width: "100%" }}>
                <Alert type="info" message={t("memberAccess.serviceHint")} />
                {state?.services.map((connection) => (
                  <Space key={connection.entry_id} wrap>
                    <Typography.Text strong>
                      {names[connection.entry_id]}
                    </Typography.Text>
                    <Tag color={connection.configured ? "success" : "warning"}>
                      {t(
                        connection.configured
                          ? "memberAccess.configured"
                          : "memberAccess.notConfigured",
                      )}
                    </Tag>
                    {connection.owner_name && (
                      <Typography.Text type="secondary">
                        {connection.owner_name}
                      </Typography.Text>
                    )}
                    {connection.entry_id !== "negative-profit" && (
                      <Button
                        size="small"
                        disabled={busy || dirty}
                        onClick={() => void configure(connection.entry_id)}
                      >
                        {t("memberAccess.configureService")}
                      </Button>
                    )}
                  </Space>
                ))}
              </Space>
            ),
          },
        ]}
      />
      <Modal
        open={!!service}
        title={t("memberAccess.configureService")}
        onCancel={() => setService(undefined)}
        onOk={() => void connect()}
        confirmLoading={busy}
        okButtonProps={{ disabled: !account || busy }}
        destroyOnHidden
      >
        <Typography.Paragraph>
          {t("memberAccess.serviceHint")}
        </Typography.Paragraph>
        <Select
          aria-label={t("memberAccess.serviceAccount")}
          style={{ width: "100%" }}
          value={account}
          loading={busy}
          onChange={setAccount}
          options={choices.map((row) => ({
            value: row.account_id,
            label: row.label,
          }))}
        />
      </Modal>
    </section>
  );
}
