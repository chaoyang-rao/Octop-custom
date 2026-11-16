import { Button, Card, Space, Typography } from "antd";
import { Bot } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useLocation } from "react-router-dom";
import {
  companionLaunchURL,
  isCompanionSupported,
} from "../utils/desktopCompanion";

export default function DesktopCompanionLaunch() {
  const { t } = useTranslation();
  const location = useLocation();
  const supported = isCompanionSupported();
  const url = companionLaunchURL(location.search);
  return (
    <main
      style={{
        minHeight: "100dvh",
        display: "grid",
        placeItems: "center",
        padding: 24,
        background: "var(--fn-bg-base)",
      }}
    >
      <Card style={{ width: "100%", maxWidth: 440 }}>
        <Space direction="vertical" size="large" style={{ width: "100%" }}>
          <Bot size={28} aria-hidden />
          <Typography.Title level={3} style={{ margin: 0 }}>
            {t("companion.title")}
          </Typography.Title>
          <Typography.Paragraph style={{ margin: 0 }}>
            {t(supported ? "companion.launchHint" : "companion.macOnly")}
          </Typography.Paragraph>
          <Button
            type="primary"
            size="large"
            href={supported ? url : undefined}
            disabled={!supported}
          >
            {t(url.endsWith("size") ? "companion.size" : "companion.open")}
          </Button>
          <Typography.Text type="secondary">
            {t("companion.installHint")}
          </Typography.Text>
        </Space>
      </Card>
    </main>
  );
}
