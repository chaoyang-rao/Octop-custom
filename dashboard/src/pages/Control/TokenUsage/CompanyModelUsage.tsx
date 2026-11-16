import { Alert, Button, Select, Space, Table, Tag, Typography } from "antd";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { request } from "../../../api/request";
import { apiErrorMessage } from "../../../utils/apiError";
import { UsageStats } from "./UsageStats";

interface Row {
  user_id: number;
  member_name: string;
  model: string;
  requests: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  estimated_requests: number;
  last_used: number;
}
interface Summary {
  scope: "company" | "self";
  range_start: number;
  range_end: number;
  rows: Row[];
}

export default function CompanyModelUsage() {
  const { t } = useTranslation();
  const [days, setDays] = useState(30);
  const [data, setData] = useState<Summary>();
  const [member, setMember] = useState<number>();
  const [model, setModel] = useState<string>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const sequence = useRef(0);
  const refresh = useCallback(async () => {
    const id = ++sequence.current;
    setLoading(true);
    try {
      const next = await request<Summary>(
        `/enterprise/models/usage?days=${days}`,
      );
      if (sequence.current !== id) return;
      setData(next);
      setError("");
    } catch (e) {
      if (sequence.current === id) {
        setData(undefined);
        setError(apiErrorMessage(e, t("companyUsage.loadFailed"), t));
      }
    } finally {
      if (sequence.current === id) setLoading(false);
    }
  }, [days, t]);
  useEffect(() => {
    void refresh();
    const timer = setInterval(() => {
      if (document.visibilityState === "visible") void refresh();
    }, 30000);
    return () => {
      clearInterval(timer);
      sequence.current += 1;
    };
  }, [refresh]);
  const rows = useMemo(
    () =>
      (data?.rows ?? []).filter(
        (r) =>
          (member === undefined || member === r.user_id) &&
          (!model || model === r.model),
      ),
    [data, member, model],
  );
  const number = (n: number) => n.toLocaleString();
  const totals = [
    "requests",
    "input_tokens",
    "output_tokens",
    "total_tokens",
  ] as const;
  const members = [
    ...new Map(
      (data?.rows ?? []).map((r) => [r.user_id, r.member_name]),
    ).entries(),
  ];
  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Alert type="info" showIcon message={t("companyUsage.hint")} />
      {error && <Alert type="error" showIcon message={error} />}
      <Space wrap>
        <Select
          aria-label={t("companyUsage.range")}
          value={days}
          onChange={setDays}
          options={[1, 7, 30, 90, 366].map((value) => ({
            value,
            label: t("companyUsage.days", { count: value }),
          }))}
        />
        <Select
          aria-label={t("companyUsage.member")}
          style={{ minWidth: 160 }}
          allowClear
          showSearch
          optionFilterProp="label"
          placeholder={t("companyUsage.allMembers")}
          value={member}
          onChange={setMember}
          options={members.map(([value, label]) => ({ value, label }))}
        />
        <Select
          aria-label={t("companyUsage.model")}
          style={{ minWidth: 200 }}
          allowClear
          showSearch
          optionFilterProp="label"
          placeholder={t("companyUsage.allModels")}
          value={model}
          onChange={setModel}
          options={[...new Set((data?.rows ?? []).map((r) => r.model))].map(
            (value) => ({ value, label: value }),
          )}
        />
        <Button onClick={() => void refresh()} loading={loading}>
          {t("common.refresh")}
        </Button>
        <Tag>
          {t(
            data?.scope === "company"
              ? "companyUsage.company"
              : "companyUsage.self",
          )}
        </Tag>
      </Space>
      <UsageStats
        items={totals.map((key) => ({
          key,
          label: t(`companyUsage.${key}`),
          value: number(rows.reduce((n, r) => n + r[key], 0)),
        }))}
      />
      <Table<Row>
        size="small"
        rowKey={(r) => `${r.user_id}:${r.model}`}
        loading={loading}
        dataSource={rows}
        scroll={{ x: 800 }}
        pagination={{ pageSize: 20 }}
        columns={[
          { title: t("companyUsage.member"), dataIndex: "member_name" },
          { title: t("companyUsage.model"), dataIndex: "model" },
          ...totals.map((key) => ({
            title: t(`companyUsage.${key}`),
            dataIndex: key,
            render: number,
            sorter: (a: Row, b: Row) => a[key] - b[key],
          })),
          {
            title: t("companyUsage.accuracy"),
            dataIndex: "estimated_requests",
            render: (n: number) =>
              n ? (
                <Tag color="orange">
                  {t("companyUsage.estimated", { count: n })}
                </Tag>
              ) : (
                <Tag color="green">{t("companyUsage.actual")}</Tag>
              ),
          },
        ]}
      />
      {data && (
        <Typography.Text type="secondary">
          {new Date(data.range_start * 1000).toLocaleString()} –{" "}
          {new Date(data.range_end * 1000).toLocaleString()} ·{" "}
          {t("companyUsage.refreshHint")}
        </Typography.Text>
      )}
    </Space>
  );
}
