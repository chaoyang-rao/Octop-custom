import { useEffect, useState } from "react";
import { Alert } from "antd";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { resourcesApi } from "../../api/modules/enterpriseResources";
import { useCurrentUser } from "../../hooks/useCurrentUser";
import { userCanAny } from "../../utils/permissions";

export default function EnterpriseResourceNotice() {
  const { t } = useTranslation();
  const user = useCurrentUser();
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    let alive = true;
    if (!user || !userCanAny(user, ["experts", "skills"])) {
      setVisible(false);
      return;
    }
    const check = () =>
      resourcesApi
        .status()
        .then((s) => {
          if (alive)
            setVisible(
              s.enabled &&
                s.resources.some(
                  (r) => r.enabled && !r.paused && r.status === "conflict",
                ),
            );
        })
        .catch(() => {});
    void check();
    const timer = window.setInterval(() => void check(), 15000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [user]);
  if (!visible) return null;
  return (
    <Alert
      style={{ flexShrink: 0 }}
      type="warning"
      showIcon
      message={t("enterpriseResources.conflictNotice")}
      action={
        <Link to="/enterprise-resources">{t("enterpriseResources.view")}</Link>
      }
    />
  );
}
