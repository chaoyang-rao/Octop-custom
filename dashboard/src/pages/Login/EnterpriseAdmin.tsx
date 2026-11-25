import { Spin, Tabs } from "antd";
import {
  BarChart3,
  Bot,
  Layers3,
  Cpu,
  PackageCheck,
  ShieldCheck,
  UsersRound,
  UserRoundCheck,
} from "lucide-react";
import { lazy, Suspense } from "react";
import { useTranslation } from "react-i18next";
import TabLabel from "../../components/TabLabel";
import { useCurrentUser } from "../../hooks/useCurrentUser";
import styles from "./EnterpriseAdmin.module.less";

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
    <main className={styles.page} aria-labelledby="enterprise-center-title">
      <div className={styles.frame}>
        <header className={styles.header}>
          <div className={styles.intro}>
            <span className={styles.mark} aria-hidden="true">
              <ShieldCheck size={23} />
            </span>
            <div>
              <h1 id="enterprise-center-title">
                {t("enterprise.centerTitle")}
              </h1>
              <p>{t("enterprise.manageHint")}</p>
            </div>
          </div>
        </header>
        <Tabs
          className={styles.tabs}
          more={{ trigger: "click" }}
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
              key: "users",
              label: (
                <TabLabel icon={UsersRound}>{t("enterprise.manage")}</TabLabel>
              ),
              children: (
                <Suspense fallback={<Spin />}>
                  <UsersPage identityOnly />
                </Suspense>
              ),
            },
            ...(user?.role === "admin"
              ? [
                  {
                    key: "member-access",
                    label: (
                      <TabLabel icon={UserRoundCheck}>
                        {t("memberAccess.title")}
                      </TabLabel>
                    ),
                    children: (
                      <Suspense fallback={<Spin />}>
                        <MemberAccessAdmin />
                      </Suspense>
                    ),
                  },
                  {
                    key: "experts",
                    label: (
                      <TabLabel icon={Bot}>
                        {t("enterpriseResources.expertsTitle")}
                      </TabLabel>
                    ),
                    destroyOnHidden: true,
                    children: (
                      <Suspense fallback={<Spin />}>
                        <EnterpriseResourceAdmin resourceKind="expert" />
                      </Suspense>
                    ),
                  },
                  {
                    key: "skills",
                    label: (
                      <TabLabel icon={Layers3}>
                        {t("enterpriseResources.skillsTitle")}
                      </TabLabel>
                    ),
                    destroyOnHidden: true,
                    children: (
                      <Suspense fallback={<Spin />}>
                        <EnterpriseResourceAdmin resourceKind="skill" />
                      </Suspense>
                    ),
                  },
                  {
                    key: "inference",
                    label: (
                      <TabLabel icon={Cpu}>
                        {t("companion.modelServiceTitle")}
                      </TabLabel>
                    ),
                    children: (
                      <Suspense fallback={<Spin />}>
                        <InferenceAdmin />
                      </Suspense>
                    ),
                  },
                  {
                    key: "client-updates",
                    label: (
                      <TabLabel icon={PackageCheck}>
                        {t("clientUpdates.title")}
                      </TabLabel>
                    ),
                    children: (
                      <Suspense fallback={<Spin />}>
                        <ClientUpdateAdmin />
                      </Suspense>
                    ),
                  },
                ]
              : []),
            {
              key: "company-usage",
              label: (
                <TabLabel icon={BarChart3}>{t("companyUsage.title")}</TabLabel>
              ),
              children: (
                <Suspense fallback={<Spin />}>
                  <CompanyModelUsage />
                </Suspense>
              ),
            },
          ]}
        />
      </div>
    </main>
  );
}
