import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Drawer,
  Empty,
  Form,
  Input,
  Select,
  Space,
  Table,
  Typography,
} from "antd";
import { useTranslation } from "react-i18next";
import {
  feedbackApi,
  type FeedbackOptions,
  type FeedbackRecord,
  type FeedbackStatus,
} from "../../api/modules/feedback";
import FeedbackStatusTag from "../../components/feedback/FeedbackStatusTag";
import { useServerTimezone } from "../../hooks/useServerTimezone";
import { formatServerDateTime } from "../../utils/formatMessageTime";
import { apiErrorMessage } from "../../utils/apiError";
import styles from "./FeedbackAdmin.module.less";

export default function FeedbackAdmin({
  company = false,
}: {
  company?: boolean;
}) {
  const { t } = useTranslation();
  const timezone = useServerTimezone();
  const loadGeneration = useRef(0);
  const [options, setOptions] = useState<FeedbackOptions | null>(null);
  const [items, setItems] = useState<FeedbackRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [section, setSection] = useState<string>();
  const [status, setStatus] = useState<FeedbackStatus>();
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<FeedbackRecord | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [form] = Form.useForm<{ status: FeedbackStatus; reply: string }>();

  const load = useCallback(async () => {
    const generation = ++loadGeneration.current;
    setLoading(true);
    setError("");
    try {
      const [records, catalogue] = await Promise.all([
        feedbackApi.list(
          {
            section,
            status,
            q: query,
            limit: pageSize,
            offset: (page - 1) * pageSize,
          },
          company,
        ),
        feedbackApi.options(company),
      ]);
      if (generation !== loadGeneration.current) return;
      setItems(records.items);
      setTotal(records.total);
      setOptions(catalogue);
    } catch (failure) {
      if (generation === loadGeneration.current)
        setError(apiErrorMessage(failure, t("feedback.loadFailed"), t));
    } finally {
      if (generation === loadGeneration.current) setLoading(false);
    }
  }, [company, section, status, query, page, pageSize, t]);
  useEffect(() => {
    void load();
  }, [load]);

  async function save(values: { status: FeedbackStatus; reply: string }) {
    if (!selected) return;
    setSaving(true);
    setError("");
    setSaved(false);
    try {
      const next = await feedbackApi.update(
        selected,
        values.status,
        values.reply,
        company,
      );
      setSelected(next);
      setItems((previous) =>
        previous.map((item) =>
          item.feedback_id === next.feedback_id ? next : item,
        ),
      );
      setSaved(true);
    } catch (failure) {
      setError(apiErrorMessage(failure, t("feedback.saveFailed"), t));
    } finally {
      setSaving(false);
    }
  }
  const sectionLabel = (key: string) =>
    t(
      options?.sections.find((item) => item.key === key)?.label_key ??
        "feedback.general",
    );
  return (
    <section className={styles.page} aria-label={t("feedback.adminTitle")}>
      <Card
        title={t("feedback.adminTitle")}
        extra={
          <Button onClick={() => void load()} loading={loading}>
            {t("common.refresh")}
          </Button>
        }
      >
        <Typography.Paragraph type="secondary">
          {t("feedback.adminIntro")}
        </Typography.Paragraph>
        {error && !selected && (
          <Alert role="alert" type="error" message={error} />
        )}
        <div className={styles.filters}>
          <Select
            className={styles.section}
            allowClear
            showSearch
            optionFilterProp="label"
            aria-label={t("feedback.section")}
            placeholder={t("feedback.allSections")}
            value={section}
            options={options?.sections.map((item) => ({
              value: item.key,
              label: t(item.label_key),
            }))}
            onChange={(value) => {
              setSection(value);
              setPage(1);
            }}
          />
          <Select
            className={styles.status}
            allowClear
            aria-label={t("feedback.processingStatus")}
            placeholder={t("feedback.allStatuses")}
            value={status}
            options={["new", "in_progress", "resolved"].map((value) => ({
              value,
              label: t(`feedback.status.${value}`),
            }))}
            onChange={(value) => {
              setStatus(value);
              setPage(1);
            }}
          />
          <Input.Search
            className={styles.search}
            allowClear
            placeholder={t("feedback.search")}
            aria-label={t("feedback.search")}
            onSearch={(value) => {
              setQuery(value.trim());
              setPage(1);
            }}
          />
        </div>
        <Table
          rowKey="feedback_id"
          loading={loading}
          dataSource={items}
          scroll={{ x: 860 }}
          locale={{
            emptyText: <Empty description={t("feedback.emptyAdmin")} />,
          }}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            showTotal: (count) => t("feedback.total", { count }),
            onChange: (next, size) => {
              setPage(size === pageSize ? next : 1);
              setPageSize(size);
            },
          }}
          columns={[
            {
              title: t("feedback.subject"),
              dataIndex: "title",
              width: 300,
              render: (_, row) => (
                <Button
                  type="link"
                  className={styles.subject}
                  onClick={() => {
                    setSelected(row);
                    setError("");
                    setSaved(false);
                    form.setFieldsValue({
                      status: row.status,
                      reply: row.reply,
                    });
                  }}
                >
                  {row.title}
                </Button>
              ),
            },
            {
              title: t("feedback.section"),
              dataIndex: "section",
              render: sectionLabel,
            },
            { title: t("feedback.author"), dataIndex: "author_name" },
            {
              title: t("feedback.kind"),
              dataIndex: "kind",
              render: (value) => t(`feedback.kinds.${value}`),
            },
            {
              title: t("feedback.processingStatus"),
              dataIndex: "status",
              render: (value) => <FeedbackStatusTag status={value} />,
            },
            {
              title: t("feedback.createdAt"),
              dataIndex: "created_at",
              render: (value) => formatServerDateTime(value, timezone),
            },
          ]}
        />
      </Card>
      <Drawer
        title={t("feedback.details")}
        open={!!selected}
        width="min(600px, 100vw)"
        closable={!saving}
        maskClosable={!saving}
        onClose={() => !saving && setSelected(null)}
      >
        {selected && (
          <div className={styles.detail}>
            <Typography.Title level={5}>{selected.title}</Typography.Title>
            <div className={styles.meta}>
              {sectionLabel(selected.section)} · {selected.author_name} ·{" "}
              {formatServerDateTime(selected.created_at, timezone)}
            </div>
            <Typography.Paragraph className={styles.text}>
              {selected.content}
            </Typography.Paragraph>
            <div className={styles.meta}>
              {selected.feedback_id} · {selected.client_version || "—"} ·{" "}
              {selected.client_platform || "—"}
            </div>
            {error && <Alert role="alert" type="error" message={error} />}
            {saved && (
              <Alert
                role="status"
                type="success"
                message={t("feedback.saved")}
              />
            )}
            <Form
              form={form}
              layout="vertical"
              disabled={saving}
              className={styles.editor}
              onFinish={(values) => void save(values)}
            >
              <Form.Item
                name="status"
                label={t("feedback.processingStatus")}
                rules={[{ required: true }]}
              >
                <Select
                  options={["new", "in_progress", "resolved"].map((value) => ({
                    value,
                    label: t(`feedback.status.${value}`),
                  }))}
                />
              </Form.Item>
              <Form.Item name="reply" label={t("feedback.reply")}>
                <Input.TextArea rows={4} maxLength={4000} showCount />
              </Form.Item>
              <Space>
                <Button type="primary" htmlType="submit" loading={saving}>
                  {t("common.save")}
                </Button>
              </Space>
            </Form>
          </div>
        )}
      </Drawer>
    </section>
  );
}
