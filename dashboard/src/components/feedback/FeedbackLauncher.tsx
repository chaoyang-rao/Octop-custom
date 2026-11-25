import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import {
  Alert,
  Button,
  Drawer,
  Empty,
  Form,
  Input,
  Select,
  Spin,
  Tabs,
  Tooltip,
  Typography,
} from "antd";
import { useTranslation } from "react-i18next";
import { MessageSquareText } from "../arcIcons";
import {
  feedbackApi,
  sectionForPath,
  type FeedbackDraft,
  type FeedbackOptions,
  type FeedbackRecord,
} from "../../api/modules/feedback";
import { useCurrentUser } from "../../hooks/useCurrentUser";
import { useServerTimezone } from "../../hooks/useServerTimezone";
import { formatServerDateTime } from "../../utils/formatMessageTime";
import { readStoredUpdateStatus } from "../../utils/updateStatusCache";
import { isDesktopShell } from "../../utils/desktopChrome";
import { apiErrorMessage } from "../../utils/apiError";
import FeedbackStatusTag from "./FeedbackStatusTag";
import styles from "./FeedbackLauncher.module.less";

function newSubmissionKey() {
  return crypto.randomUUID().replaceAll("-", "");
}

export default function FeedbackLauncher({
  compact = false,
  currentSection,
}: {
  compact?: boolean;
  currentSection?: string;
}) {
  const { t } = useTranslation();
  const location = useLocation();
  const user = useCurrentUser();
  const timezone = useServerTimezone();
  const [form] =
    Form.useForm<
      Pick<FeedbackDraft, "section" | "kind" | "title" | "content">
    >();
  const [open, setOpen] = useState(false);
  const [options, setOptions] = useState<FeedbackOptions | null>(null);
  const [history, setHistory] = useState<FeedbackRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [historyError, setHistoryError] = useState("");
  const [success, setSuccess] = useState("");
  const submissionKey = useRef<string | null>(null);
  const identity = useRef(user?.id);
  identity.current = user?.id;
  const loadGeneration = useRef(0);

  useEffect(() => {
    loadGeneration.current += 1;
    setLoading(false);
    setSending(false);
    setHistoryError("");
    form.resetFields();
    setOptions(null);
    setHistory([]);
    setError("");
    setSuccess("");
    submissionKey.current = null;
  }, [user?.id, form]);

  async function refresh(selectCurrentSection = false) {
    const owner = user?.id;
    const generation = ++loadGeneration.current;
    setLoading(true);
    setError("");
    setHistoryError("");
    const results = await Promise.allSettled([
      feedbackApi.options(),
      feedbackApi.mine(),
    ]);
    if (identity.current !== owner || generation !== loadGeneration.current)
      return;
    if (results[0].status === "fulfilled") {
      const next = results[0].value;
      setOptions(next);
      const emptyDraft =
        !form.getFieldValue("title")?.trim() &&
        !form.getFieldValue("content")?.trim();
      if (
        !form.getFieldValue("section") ||
        (selectCurrentSection && emptyDraft)
      )
        form.setFieldsValue({
          section: next.sections.some(
            (section) => section.key === currentSection,
          )
            ? currentSection
            : sectionForPath(next.sections, location.pathname),
          kind: form.getFieldValue("kind") ?? "problem",
        });
    } else
      setError(apiErrorMessage(results[0].reason, t("feedback.loadFailed"), t));
    if (results[1].status === "fulfilled") setHistory(results[1].value.items);
    else
      setHistoryError(
        apiErrorMessage(results[1].reason, t("feedback.loadFailed"), t),
      );
    setLoading(false);
  }

  async function submit(
    values: Pick<FeedbackDraft, "section" | "kind" | "title" | "content">,
  ) {
    const owner = user?.id;
    setSending(true);
    setError("");
    setSuccess("");
    submissionKey.current ??= newSubmissionKey();
    const version = readStoredUpdateStatus();
    const clientVersion =
      version?.custom_version ?? version?.current_version ?? "";
    try {
      const created = await feedbackApi.submit({
        ...values,
        submission_key: submissionKey.current,
        client_version: /^[a-zA-Z0-9.+_-]{0,80}$/.test(clientVersion)
          ? clientVersion
          : "",
        client_platform: isDesktopShell() ? "" : "web",
      });
      if (identity.current !== owner) return;
      setHistory((previous) => [
        created,
        ...previous.filter((item) => item.feedback_id !== created.feedback_id),
      ]);
      setSuccess(t("feedback.submitted", { id: created.feedback_id }));
      form.setFieldsValue({ title: "", content: "" });
      submissionKey.current = null;
    } catch (failure) {
      if (identity.current === owner)
        setError(apiErrorMessage(failure, t("feedback.submitFailed"), t));
    } finally {
      if (identity.current === owner) setSending(false);
    }
  }

  if (!user) return null;
  const label = t("feedback.title");
  return (
    <>
      <div className={`${styles.launcher} ${compact ? styles.compact : ""}`}>
        <Tooltip title={compact ? label : undefined} placement="right">
          <Button
            type="text"
            aria-label={label}
            icon={<MessageSquareText size={17} aria-hidden />}
            onClick={() => {
              setOpen(true);
              void refresh(true);
            }}
          >
            {!compact && label}
          </Button>
        </Tooltip>
      </div>
      <Drawer
        title={label}
        open={open}
        onClose={() => !sending && setOpen(false)}
        width="min(520px, 100vw)"
        maskClosable={!sending}
        closable={!sending}
      >
        <div className={styles.body}>
          <Typography.Paragraph type="secondary">
            {t("feedback.intro")}
          </Typography.Paragraph>
          {error && (
            <Alert
              role="alert"
              type="error"
              message={error}
              action={
                <Button
                  size="small"
                  onClick={() => void refresh()}
                  disabled={sending}
                >
                  {t("common.retry")}
                </Button>
              }
            />
          )}
          {success && <Alert role="status" type="success" message={success} />}
          <Tabs
            items={[
              {
                key: "new",
                label: t("feedback.new"),
                children: (
                  <Spin spinning={loading}>
                    <Form
                      form={form}
                      layout="vertical"
                      disabled={sending}
                      className={styles.form}
                      onFinish={(values) => void submit(values)}
                      onValuesChange={() => {
                        submissionKey.current = newSubmissionKey();
                        setSuccess("");
                      }}
                    >
                      <Form.Item
                        name="section"
                        label={t("feedback.section")}
                        rules={[
                          {
                            required: true,
                            message: t("feedback.sectionRequired"),
                          },
                        ]}
                      >
                        <Select
                          showSearch
                          optionFilterProp="label"
                          options={options?.sections.map((section) => ({
                            value: section.key,
                            label: t(section.label_key),
                          }))}
                        />
                      </Form.Item>
                      <Form.Item
                        name="kind"
                        label={t("feedback.kind")}
                        rules={[{ required: true }]}
                      >
                        <Select
                          options={["problem", "suggestion", "other"].map(
                            (value) => ({
                              value,
                              label: t(`feedback.kinds.${value}`),
                            }),
                          )}
                        />
                      </Form.Item>
                      <Form.Item
                        name="title"
                        label={t("feedback.subject")}
                        rules={[
                          {
                            required: true,
                            whitespace: true,
                            message: t("feedback.subjectRequired"),
                          },
                        ]}
                      >
                        <Input maxLength={160} showCount />
                      </Form.Item>
                      <Form.Item
                        name="content"
                        label={t("feedback.content")}
                        rules={[
                          {
                            required: true,
                            whitespace: true,
                            message: t("feedback.contentRequired"),
                          },
                        ]}
                      >
                        <Input.TextArea
                          rows={6}
                          maxLength={6000}
                          showCount
                          placeholder={t("feedback.contentHint")}
                        />
                      </Form.Item>
                      <div className={styles.submit}>
                        {options?.local_admin && (
                          <Link
                            to="/admin/feedback"
                            onClick={() => setOpen(false)}
                          >
                            {t("feedback.adminTitle")}
                          </Link>
                        )}
                        <Button
                          type="primary"
                          htmlType="submit"
                          loading={sending}
                          disabled={!options || loading}
                        >
                          {t("feedback.submit")}
                        </Button>
                      </div>
                    </Form>
                  </Spin>
                ),
              },
              {
                key: "mine",
                label: t("feedback.mine"),
                children: (
                  <>
                    {historyError && (
                      <Alert
                        role="alert"
                        type="error"
                        message={historyError}
                        action={
                          <Button size="small" onClick={() => void refresh()}>
                            {t("common.retry")}
                          </Button>
                        }
                      />
                    )}
                    <Button
                      size="small"
                      onClick={() => void refresh()}
                      loading={loading}
                    >
                      {t("common.refresh")}
                    </Button>
                    {!history.length && !loading && (
                      <Empty description={t("feedback.emptyMine")} />
                    )}
                    {history.map((item) => (
                      <article
                        className={styles.historyItem}
                        key={item.feedback_id}
                      >
                        <div className={styles.historyHead}>
                          <Typography.Text strong>{item.title}</Typography.Text>
                          <FeedbackStatusTag status={item.status} />
                        </div>
                        <div className={styles.meta}>
                          {t(
                            options?.sections.find(
                              (section) => section.key === item.section,
                            )?.label_key ?? "feedback.general",
                          )}{" "}
                          · {formatServerDateTime(item.created_at, timezone)}
                        </div>
                        <Typography.Paragraph className={styles.paragraph}>
                          {item.content}
                        </Typography.Paragraph>
                        {item.reply && (
                          <div className={styles.reply}>
                            <Typography.Text strong>
                              {t("feedback.reply")}
                            </Typography.Text>
                            <Typography.Paragraph className={styles.paragraph}>
                              {item.reply}
                            </Typography.Paragraph>
                          </div>
                        )}
                      </article>
                    ))}
                  </>
                ),
              },
            ]}
          />
        </div>
      </Drawer>
    </>
  );
}
