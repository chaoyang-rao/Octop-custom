import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Popconfirm,
  Select,
  Space,
  Tag,
  Typography,
} from "antd";
import { useTranslation } from "react-i18next";
import {
  managedCliApi,
  type ManagedCliPackage,
} from "../../api/modules/nativeCli";
import { message } from "../../utils/antdMessage";
import { apiErrorMessage } from "../../utils/apiError";

export function ManagedCliPanel({
  onRunner,
}: {
  onRunner: (runner: string) => void;
}) {
  const { t } = useTranslation();
  const translateRef = useRef(t);
  translateRef.current = t;
  const [packages, setPackages] = useState<ManagedCliPackage[]>([]);
  const [versions, setVersions] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const fail = useCallback((error: unknown) => {
    const translate = translateRef.current;
    message.error(
      apiErrorMessage(error, translate("common.unknownError"), translate),
    );
  }, []);
  const refresh = useCallback(
    async () => setPackages(await managedCliApi.status()),
    [],
  );
  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const rows = await managedCliApi.status();
        if (active) setPackages(rows);
      } catch (error) {
        if (active) fail(error);
      }
    };
    void load();
    const timer = window.setInterval(() => {
      if (!document.hidden) void load();
    }, 3000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [fail]);
  async function act(operation: () => Promise<unknown>) {
    setBusy(true);
    try {
      await operation();
      await refresh();
    } catch (error) {
      fail(error);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Alert type="info" showIcon message={t("nativeCli.managedIntro")} />
      <Alert type="info" showIcon message={t("nativeCli.managedExternal")} />
      {packages.map((pkg) => {
        const version = versions[pkg.package] ?? pkg.latest_approved;
        const pin = pkg.approved.find((item) => item.version === version);
        const installing = ["queued", "downloading", "extracting"].includes(
          pkg.state.phase,
        );
        const notes = t(`nativeCli.managedNotes.${pkg.package}`, "");
        return (
          <Card
            size="small"
            key={pkg.package}
            title={
              <Space>
                {pkg.label}
                <Tag>{pkg.license}</Tag>
                <Tag>{pkg.platform}</Tag>
              </Space>
            }
          >
            <Space direction="vertical" style={{ width: "100%" }}>
              {notes && (
                <Alert
                  type={pkg.package === "pi" ? "warning" : "info"}
                  showIcon
                  message={notes}
                />
              )}
              <Space wrap>
                <Select
                  style={{ width: 150 }}
                  value={version}
                  onChange={(value) =>
                    setVersions({ ...versions, [pkg.package]: value })
                  }
                  options={pkg.versions.map((value) => ({
                    value,
                    label: value,
                  }))}
                />
                <Tag>
                  {t(
                    `nativeCli.installStates.${pkg.state.phase}`,
                    pkg.state.phase,
                  )}
                </Tag>
                {pkg.active_version && (
                  <Typography.Text>
                    {t("nativeCli.activeVersion")}: {pkg.active_version}
                  </Typography.Text>
                )}
              </Space>
              {pin && (
                <>
                  <Typography.Link
                    href={pin.release_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {t("nativeCli.officialRelease")}
                  </Typography.Link>
                  <Typography.Text
                    code
                    copyable
                    style={{ overflowWrap: "anywhere" }}
                  >
                    {pin.sha256 ? `SHA256 ${pin.sha256}` : pin.integrity}
                  </Typography.Text>
                </>
              )}
              {pkg.state.error_code && (
                <Alert
                  type="error"
                  message={t(
                    `nativeCli.errors.${pkg.state.error_code}`,
                    pkg.state.error_code,
                  )}
                />
              )}
              <Space wrap>
                <Button
                  disabled={
                    busy ||
                    installing ||
                    !pkg.supported ||
                    pkg.installed.includes(version)
                  }
                  onClick={() =>
                    void act(() => managedCliApi.install(pkg.package, version))
                  }
                >
                  {t("nativeCli.installSelected")}
                </Button>
                <Popconfirm
                  title={t("nativeCli.activateConfirm")}
                  onConfirm={() =>
                    act(async () => {
                      const next = await managedCliApi.activate(
                        pkg.package,
                        version,
                      );
                      onRunner(next.runner);
                      message.success(t("nativeCli.chooseManagedRunner"));
                    })
                  }
                >
                  <Button
                    disabled={
                      busy || installing || !pkg.installed.includes(version)
                    }
                  >
                    {t("nativeCli.activateSelected")}
                  </Button>
                </Popconfirm>
                <Popconfirm
                  title={t("nativeCli.rollbackConfirm")}
                  onConfirm={() =>
                    act(async () => {
                      const next = await managedCliApi.rollback(pkg.package);
                      onRunner(next.runner);
                    })
                  }
                >
                  <Button
                    disabled={busy || installing || !pkg.previous_version}
                  >
                    {t("nativeCli.rollback")}
                  </Button>
                </Popconfirm>
              </Space>
              {!pkg.supported && (
                <Alert
                  type="info"
                  message={t("nativeCli.unsupportedPlatform")}
                />
              )}
            </Space>
          </Card>
        );
      })}
    </Space>
  );
}
