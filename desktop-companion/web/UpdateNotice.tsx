import { useEffect, useState } from "react";
import { native, type NativeEvent } from "./bridge";

type Job = {
  id: string;
  phase: string;
  downloaded_bytes: number;
  total_bytes: number;
  error_code: string | null;
};
type Status = {
  supported: boolean;
  available: boolean;
  current_version: string;
  version: string | null;
  notes: string;
  busy: boolean;
  job: Job | null;
};
const labels: Record<string, string> = {
  applying: "正在准备更新",
  backing_up: "正在备份账号和聊天数据",
  ready_to_swap: "即将重启哆啦",
  installing: "正在安装新版",
  starting: "正在验证新版启动",
  rolling_back: "正在恢复上一版本",
  failed: "更新未完成，可重新检查",
  rolled_back: "已恢复上一版本",
};
export function UpdateNotice({
  authenticated,
  settings,
}: {
  authenticated: boolean;
  settings: boolean;
}) {
  const [status, setStatus] = useState<Status | null>(null);
  const [busy, setBusy] = useState(false);
  const [installing, setInstalling] = useState("");
  const [error, setError] = useState("");
  async function action(op: string, jobId?: string) {
    setBusy(true);
    setError("");
    try {
      const result = await native<Status>(op, jobId ? { jobId } : {});
      if (op === "updateInstall") setInstalling("applying");
      else setStatus(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "更新暂不可用，请重试。");
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    let active = true;
    if (!authenticated) {
      setStatus(null);
      setError("");
      return;
    }
    if (installing) return;
    const refresh = () =>
      void native<Status>("updateStatus")
        .then((next) => {
          if (active) setStatus(next);
        })
        .catch(() => {});
    refresh();
    const timer = setInterval(refresh, 15000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [authenticated, installing]);
  useEffect(() => {
    const listener = (event: Event) => {
      const value = (event as CustomEvent<NativeEvent>).detail;
      if (value.type === "updateProgress" && typeof value.data === "string")
        setInstalling(
          ["failed", "rolled_back", "cancelled"].includes(value.data)
            ? ""
            : value.data,
        );
    };
    window.addEventListener("companion", listener);
    return () => window.removeEventListener("companion", listener);
  }, []);
  if (!authenticated || !status?.supported) return null;
  const phase = status.job?.phase;
  const downloading = phase === "downloading";
  const downloaded = phase === "downloaded" || phase === "waiting_idle";
  if (
    !settings &&
    !status.available &&
    !installing &&
    !downloading &&
    !downloaded
  )
    return null;
  const percent = status.job?.total_bytes
    ? Math.min(
        100,
        Math.round(
          (status.job.downloaded_bytes / status.job.total_bytes) * 100,
        ),
      )
    : 0;
  return (
    <aside className="companion-update" aria-label="哆啦版本更新">
      <div role="status" aria-live="polite">
        <strong>
          {installing
            ? labels[installing] || "正在更新哆啦"
            : status.available
            ? `哆啦 ${status.version} 可更新`
            : `哆啦 ${status.current_version}`}
        </strong>
        {downloading && (
          <>
            <span>正在下载 {percent}%</span>
            <progress max={100} value={percent} aria-label="更新下载进度" />
          </>
        )}
        {downloaded && (
          <span>
            {status.busy
              ? "请先完成专家任务和待处理审批，再安装更新。"
              : "更新已下载，重启安装会保留账号和聊天数据。"}
          </span>
        )}
        {!installing && phase && labels[phase] && <span>{labels[phase]}</span>}
        {error && <span role="alert">{error}</span>}
      </div>
      {!installing && (
        <div className="companion-update-actions">
          {status.available && !downloading && !downloaded && (
            <button
              disabled={busy}
              onClick={() => void action("updateDownload")}
            >
              下载更新
            </button>
          )}
          {downloaded && (
            <button
              disabled={busy || status.busy}
              onClick={() => void action("updateInstall", status.job!.id)}
            >
              重启并更新
            </button>
          )}
          {(downloading || downloaded) && (
            <button
              disabled={busy}
              onClick={() => void action("updateCancel", status.job!.id)}
            >
              取消更新
            </button>
          )}
          {settings && !downloading && !downloaded && (
            <button disabled={busy} onClick={() => void action("updateCheck")}>
              {busy ? "正在检查…" : "检查企业更新"}
            </button>
          )}
        </div>
      )}
      {status.available && status.notes && (
        <details>
          <summary>查看更新说明</summary>
          <p>{status.notes}</p>
        </details>
      )}
    </aside>
  );
}
