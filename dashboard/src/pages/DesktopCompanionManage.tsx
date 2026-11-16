import { lazy, Suspense } from "react";
import { Alert, Spin, Tabs, Typography } from "antd";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";
import { useCurrentUser } from "../hooks/useCurrentUser";
import { PERM, userCanAny } from "../utils/permissions";

const Experts = lazy(() => import("./Experts"));
const Connectors = lazy(() => import("./Agent/Connectors"));
const Knowledge = lazy(() => import("./KnowledgeBases"));
const Skills = lazy(() => import("./SkillPackages"));
const Updates = lazy(() => import("./EnterpriseResources"));
const Models = lazy(() => import("./Settings/Models"));

export default function DesktopCompanionManage() {
  const { t } = useTranslation();
  const user = useCurrentUser();
  const [search, setSearch] = useSearchParams();
  const items = [
    {
      key: "experts",
      label: t("companion.experts"),
      permissions: PERM.experts,
      children: <Experts />,
    },
    {
      key: "connectors",
      label: t("companion.connectors"),
      permissions: PERM.connectors,
      children: <Connectors />,
    },
    {
      key: "knowledge",
      label: t("companion.knowledge"),
      permissions: PERM.knowledgeBasesPage,
      children: <Knowledge />,
    },
    {
      key: "skills",
      label: t("companion.skills"),
      permissions: PERM.skills,
      children: <Skills />,
    },
    {
      key: "updates",
      label: t("companion.updates"),
      permissions: ["experts", "skills"],
      children: <Updates />,
    },
    {
      key: "models",
      label: t("companion.models"),
      permissions: PERM.modelsPage,
      children: <Models />,
    },
  ].filter((item) => user && userCanAny(user, item.permissions));
  const requested = search.get("section");
  const active = items.some((i) => i.key === requested)
    ? requested!
    : items[0]?.key;
  return (
    <main
      style={{
        height: "100dvh",
        overflowY: "auto",
        padding: 20,
        background: "var(--fn-bg-layout)",
      }}
    >
      <Typography.Title level={3}>
        {t("companion.manageTitle")}
      </Typography.Title>
      <Alert
        type="info"
        showIcon
        message={t("companion.manageHint")}
        style={{ marginBottom: 16 }}
      />
      <Suspense fallback={<Spin />}>
        <Tabs
          activeKey={active}
          onChange={(key) => setSearch({ section: key })}
          items={items}
          destroyOnHidden
        />
      </Suspense>
    </main>
  );
}
