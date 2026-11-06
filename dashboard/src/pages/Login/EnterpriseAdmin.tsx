import { Alert, Button, Spin } from "antd";
import { lazy, Suspense } from "react";
import { useTranslation } from "react-i18next";
const UsersPage = lazy(() => import("../Admin/Users"));

export default function EnterpriseAdmin() {
  const { t } = useTranslation();
  return (
    <main
      style={{
        minHeight: "100dvh",
        padding: 16,
        background: "var(--fn-bg-layout)",
      }}
    >
      <Button href="/enterprise/approve">{t("enterprise.approveTitle")}</Button>
      <Alert
        style={{ marginTop: 16 }}
        type="info"
        message={t("enterprise.manageHint")}
      />
      <Suspense fallback={<Spin />}>
        <UsersPage identityOnly />
      </Suspense>
    </main>
  );
}
