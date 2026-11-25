import { MessageSquareText } from "lucide-react";
import { useTranslation } from "react-i18next";
import TabLabel from "../../components/TabLabel";

export default function FeedbackTabTitle() {
  const { t } = useTranslation();
  return (
    <TabLabel icon={MessageSquareText}>{t("feedback.adminTitle")}</TabLabel>
  );
}
