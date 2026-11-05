import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { Tooltip } from "antd";
import cx from "classnames";
import { useUpdateStatus } from "../../hooks/useUpdateStatus";
import { useCurrentUser } from "../../hooks/useCurrentUser";
import { userCan } from "../../utils/permissions";
import styles from "./index.module.less";

interface CurrentVersionBadgeProps {
  isMobile?: boolean;
}

export default function CurrentVersionBadge({
  isMobile,
}: CurrentVersionBadgeProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const user = useCurrentUser();
  const { status } = useUpdateStatus();

  const version = status?.current_version;
  if (!version) return null;

  const canUpdate = userCan(user, "update");
  const tooltip = status?.custom_build
    ? t("customUpdate.headerTooltip", {
        version: status.custom_version || version,
      })
    : canUpdate
    ? t("header.currentVersionAdmin", { version })
    : t("header.currentVersion", { version });
  const label = `v${version}${
    status?.custom_build ? ` · ${t("customUpdate.badge")}` : ""
  }`;
  const tooltipContent = (
    <span>
      {tooltip}
      <br />
      <a
        href="/third-party-notices/solar-icons.html"
        target="_blank"
        rel="noreferrer"
      >
        {t("header.iconCredits")}
      </a>
    </span>
  );

  if (canUpdate) {
    return (
      <Tooltip title={tooltipContent} mouseEnterDelay={0.35}>
        <button
          type="button"
          className={cx(
            styles.versionBadge,
            isMobile && styles.versionBadgeMobile,
            styles.versionBadgeClickable,
          )}
          onClick={() => navigate("/admin/advanced?tab=updates")}
          aria-label={tooltip}
        >
          {label}
        </button>
      </Tooltip>
    );
  }

  return (
    <Tooltip title={tooltipContent} mouseEnterDelay={0.35}>
      <span
        className={cx(
          styles.versionBadge,
          isMobile && styles.versionBadgeMobile,
        )}
        aria-label={tooltip}
      >
        {label}
      </span>
    </Tooltip>
  );
}
