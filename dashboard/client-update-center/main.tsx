import React, { Suspense } from "react";
import { createRoot } from "react-dom/client";
import { ConfigProvider, Spin, theme } from "antd";
import zhCN from "antd/locale/zh_CN";
import enUS from "antd/locale/en_US";
import { useTranslation } from "react-i18next";
import "antd/dist/reset.css";
import { initI18n } from "../src/i18n";
import { readStoredAppearance } from "../src/styles/appearanceStorage";
import { brandTokensFor } from "../src/styles/themePalettes";
import ClientUpdateAdmin from "../src/pages/EnterpriseResources/ClientUpdateAdmin";

document.body.style.cssText =
  "margin:0;background:transparent;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif";
const parentTheme = window.parent.document.documentElement.dataset.theme;
const appearance = readStoredAppearance();
document.documentElement.dataset.theme = parentTheme || "light";
function App() {
  const { i18n } = useTranslation();
  return (
    <ConfigProvider
      locale={i18n.language.startsWith("zh") ? zhCN : enUS}
      theme={{
        token: brandTokensFor(
          appearance.palette,
          parentTheme === "dark",
          appearance.customColor,
        ),
        algorithm:
          parentTheme === "dark" ? theme.darkAlgorithm : theme.defaultAlgorithm,
      }}
    >
      <ClientUpdateAdmin />
    </ConfigProvider>
  );
}
void initI18n().then(() =>
  createRoot(document.getElementById("root")!).render(
    <Suspense fallback={<Spin />}>
      <App />
    </Suspense>,
  ),
);
new ResizeObserver(() =>
  window.parent.postMessage(
    {
      type: "octop:client-update-center-size",
      height: Math.ceil(
        document.getElementById("root")!.getBoundingClientRect().height,
      ),
    },
    window.location.origin,
  ),
).observe(document.getElementById("root")!);
