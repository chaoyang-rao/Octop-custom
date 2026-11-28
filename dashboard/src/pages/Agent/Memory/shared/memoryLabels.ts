import type { TFunction } from "i18next";

export function memoryKindLabel(kind: string, t: TFunction): string {
  switch (kind) {
    case "Fact":
      return t("memory.kind.fact", "事实");
    case "Decision":
      return t("memory.kind.decision", "决定");
    case "Task":
      return t("memory.kind.task", "任务");
    case "Preference":
      return t("memory.kind.preference", "偏好");
    case "ConflictCandidate":
      return t("memory.kind.conflict", "可能矛盾");
    default:
      return kind;
  }
}

export function formatMemoryRelativeTime(iso: string, t: TFunction): string {
  const timestamp = Date.parse(iso);
  if (!Number.isFinite(timestamp)) return iso;
  const minutes = Math.max(0, Math.floor((Date.now() - timestamp) / 60_000));
  if (minutes === 0) return t("memory.time.justNow", "刚刚");
  if (minutes < 60) {
    return t("memory.time.minutesAgo", "{{count}} 分钟前", { count: minutes });
  }
  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    return t("memory.time.hoursAgo", "{{count}} 小时前", { count: hours });
  }
  const days = Math.floor(hours / 24);
  if (days < 30) {
    return t("memory.time.relativeDaysAgo", "{{count}} 天前", { count: days });
  }
  const months = Math.floor(days / 30);
  if (months < 12) {
    return t("memory.time.monthsAgo", "{{count}} 个月前", { count: months });
  }
  return t("memory.time.yearsAgo", "{{count}} 年前", {
    count: Math.floor(months / 12),
  });
}
