import { Tag } from "antd";
import { useTranslation } from "react-i18next";
import type { FeedbackStatus } from "../../api/modules/feedback";

export default function FeedbackStatusTag({
  status,
}: {
  status: FeedbackStatus;
}) {
  const { t } = useTranslation();
  return (
    <Tag
      color={
        status === "resolved"
          ? "success"
          : status === "in_progress"
          ? "processing"
          : "warning"
      }
    >
      {t(`feedback.status.${status}`)}
    </Tag>
  );
}
