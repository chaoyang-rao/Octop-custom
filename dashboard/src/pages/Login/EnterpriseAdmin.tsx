import { Alert, Button, Spin, Tabs } from "antd";
import { lazy, Suspense } from "react";
import { useTranslation } from "react-i18next";
import { useCurrentUser } from "../../hooks/useCurrentUser";
const UsersPage = lazy(() => import("../Admin/Users"));
const EnterpriseMcpAdmin = lazy(
  () => import("../EnterpriseMcp/EnterpriseMcpAdmin"),
);

export default function EnterpriseAdmin() {
  const { t } = useTranslation();
  const user = useCurrentUser();
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
      <Tabs
        items={[
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
                  key: "mcp",
                  label: t("enterpriseMcp.adminTitle"),
                  children: (
                    <Suspense fallback={<Spin />}>
                      <EnterpriseMcpAdmin />
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
