import { useTranslation } from "react-i18next";
import {
  deriveExpertWorkStatus,
  type ExpertWorkInput,
  type ExpertWorkKind,
} from "../utils/expertWorkStatus";
import "./ExpertWorkStatus.css";

const MESSAGES: Record<
  "zh" | "en",
  Record<ExpertWorkKind, readonly [string, string]>
> = {
  zh: {
    working: ["工作中", "正在运行的会话"],
    waiting: ["待确认", "等待确认或回复的会话"],
    idle: ["空闲", "当前账号没有正在运行或等待确认的会话"],
    stopped: ["未启动", "专家尚未启用"],
    failed: ["异常", "专家未正常运行，请查看专家设置"],
    starting: ["启动中", "专家正在启动"],
    stopping: ["停止中", "专家正在停止"],
    online: ["在线", "专家已启用，后端尚未提供工作状态"],
    remote_online: ["远端在线", "云端连接正常，远端尚未提供工作状态"],
    disconnected: ["连接断开", "云端连接已断开，无法确认远端工作状态"],
    unknown: ["状态待同步", "工作状态尚未同步，请稍候"],
  },
  en: {
    working: ["Working", "Running conversations"],
    waiting: ["Waiting", "Conversations waiting for approval or a reply"],
    idle: [
      "Idle",
      "No running or waiting conversations are visible to this account",
    ],
    stopped: ["Not started", "The expert is not enabled"],
    failed: ["Error", "The expert is not running normally; check its settings"],
    starting: ["Starting", "The expert is starting"],
    stopping: ["Stopping", "The expert is stopping"],
    online: [
      "Online",
      "The expert is enabled; the backend has not supplied work status",
    ],
    remote_online: [
      "Remote online",
      "The remote link is connected; work status has not been supplied",
    ],
    disconnected: [
      "Disconnected",
      "The remote link is disconnected; remote work status is unavailable",
    ],
    unknown: ["Sync pending", "Work status is not synchronized yet"],
  },
};

export default function ExpertWorkStatus({
  agent,
}: {
  agent: ExpertWorkInput & { name?: string };
}) {
  const { t, i18n } = useTranslation();
  const messages =
    MESSAGES[i18n.language.toLowerCase().startsWith("zh") ? "zh" : "en"];
  return (
    <span className="octop-expert-work-status" data-testid="expert-work-status">
      {deriveExpertWorkStatus(agent).map(({ kind, count }) => {
        const [fallback, detail] = messages[kind];
        const label = t(`chat.expertWorkStatus.${kind}`, {
          defaultValue: fallback,
        });
        const text = count === null ? label : `${label} ${count}`;
        const translatedDetail = t(`chat.expertWorkDetail.${kind}`, {
          defaultValue: detail,
        });
        return (
          <span
            key={kind}
            className="octop-expert-work-badge"
            data-work-status={kind}
            title={
              count === null
                ? translatedDetail
                : `${translatedDetail}: ${count}`
            }
            aria-label={`${agent.name || ""}: ${text}`}
          >
            <span className="octop-expert-work-indicator" aria-hidden />
            {text}
          </span>
        );
      })}
    </span>
  );
}
