import { Button, Space } from "antd";
import { Bot, SlidersHorizontal } from "lucide-react";
import { useTranslation } from "react-i18next";
import { publicUrl } from "../utils/publicUrl";
import { isCompanionSupported } from "../utils/desktopCompanion";
import styles from "./AvatarDropdown.module.less";

export default function DesktopCompanionSettings() {
  const { t } = useTranslation();
  const supported = isCompanionSupported();
  return (
    <section className={styles.settingsSection}>
      <div className={styles.settingsSectionHead}>
        <h3 className={styles.settingsSectionTitle}>{t("companion.title")}</h3>
        <p className={styles.settingsSectionDesc}>
          {t(supported ? "companion.description" : "companion.macOnly")}
        </p>
      </div>
      <Space wrap>
        <Button
          icon={<Bot size={15} />}
          href={
            supported
              ? publicUrl("desktop-companion/launch?action=open")
              : undefined
          }
          target="_blank"
          rel="noopener noreferrer"
          disabled={!supported}
        >
          {t("companion.open")}
        </Button>
        <Button
          icon={<SlidersHorizontal size={15} />}
          href={
            supported
              ? publicUrl("desktop-companion/launch?action=size")
              : undefined
          }
          target="_blank"
          rel="noopener noreferrer"
          disabled={!supported}
        >
          {t("companion.size")}
        </Button>
      </Space>
    </section>
  );
}
