import { Alert, Button, Spin, Tabs } from "antd";
import { lazy, Suspense } from "react";
import { useTranslation } from "react-i18next";
import { useCurrentUser } from "../../hooks/useCurrentUser";
const UsersPage = lazy(() => import("../Admin/Users"));

const EnterpriseResourceAdmin = lazy(
  () => import("../EnterpriseResources/Admin"),
);
const MemberAccessAdmin = lazy(
  () => import("../EnterpriseResources/MemberAccessAdmin"),
);

const InferenceAdmin = lazy(
  () => import("../EnterpriseResources/InferenceAdmin"),
);
const CompanyModelUsage = lazy(
  () => import("../Control/TokenUsage/CompanyModelUsage"),
);
const ClientUpdateAdmin = lazy(
  () => import("../EnterpriseResources/ClientUpdateAdmin"),
);

export default function EnterpriseAdmin() {
  const { t } = useTranslation();
  const user = useCurrentUser();
  return (
    <main
      style={{
        height: "100%",
        minHeight: 0,
        overflowY: "auto",
        boxSizing: "border-box",
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
      <Tabs
        defaultActiveKey={
          user?.role === "admin"
            ? new URLSearchParams(window.location.search).get("tab") ===
              "client-updates"
              ? "client-updates"
              : "member-access"
            : "users"
        }
        items={[
          {
            key: "company-usage",
            label: t("companyUsage.title"),
            children: (
              <Suspense fallback={<Spin />}>
                <CompanyModelUsage />
              </Suspense>
            ),
          },
          {
            key: "users",
            label: t("enterprise.manage"),
            children: (
              <Suspense fallback={<Spin />}>
                <UsersPage identityOnly />
              </Suspense>
            ),
          },
          ...(user?.role === "admin"
            ? [
                {
                  key: "inference",
                  label: t("companion.modelServiceTitle"),
                  children: (
                    <Suspense fallback={<Spin />}>
                      <InferenceAdmin />
                    </Suspense>
                  ),
                },
                {
                  key: "member-access",
                  label: t("memberAccess.title"),
                  children: (
                    <Suspense fallback={<Spin />}>
                      <MemberAccessAdmin />
                    </Suspense>
                  ),
                },
                {
                  key: "resources",
                  label: t("enterpriseResources.title"),
                  children: (
                    <Suspense fallback={<Spin />}>
                      <EnterpriseResourceAdmin />
                    </Suspense>
                  ),
                },
                {
                  key: "client-updates",
                  label: t("clientUpdates.title"),
                  children: (
                    <Suspense fallback={<Spin />}>
                      <ClientUpdateAdmin />
                    </Suspense>
                  ),
                },
              ]
            : []),
        ]}
      />
    </main>
  );
}
