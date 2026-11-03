import type {
  TaskAttachment,
  TaskCreate,
  TaskCoordination,
  TaskDispatchView,
  TaskProject,
} from "../../api/modules/tasks";
import type { TFunction } from "i18next";
import { apiErrorMessage, parseApiError } from "../../utils/apiError";

export interface TaskDraft {
  agent_id: string;
  title: string;
  prompt: string;
  notify_policy?: "always" | "failure";
  task_kind?: "general" | "coding";
  project_path?: string;
  test_commands?: string;
  publish_pr?: boolean;
}

export function verificationCommands(value: string): string[] {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

export function taskCreateFromDraft(
  draft: TaskDraft,
  attachments: TaskAttachment[],
  originThreadId?: string,
): TaskCreate {
  return {
    agent_id: draft.agent_id,
    title: draft.title,
    prompt: draft.prompt,
    options: { quiet: draft.notify_policy === "failure" },
    ...(attachments.length ? { attachments } : {}),
    ...(originThreadId ? { origin_thread_id: originThreadId } : {}),
    ...(draft.task_kind === "coding"
      ? {
          coding: {
            project_path: draft.project_path!,
            test_commands: verificationCommands(draft.test_commands || ""),
            publish_pr: draft.publish_pr === true,
          },
        }
      : {}),
  };
}

export function uniqueProjects(groups: TaskProject[][]): TaskProject[] {
  return [
    ...new Map(
      groups.flat().map((project) => [project.project_path, project]),
    ).values(),
  ];
}

export function originReturned(
  dispatch: TaskDispatchView,
  attempt: number,
  state: string,
): boolean {
  if (
    typeof dispatch.current_event_id === "number" &&
    dispatch.current_event_id > 0 &&
    typeof dispatch.returned_event_id === "number"
  )
    return dispatch.returned_event_id >= dispatch.current_event_id;
  return (
    dispatch.returned_attempt >= attempt && dispatch.returned_state === state
  );
}

export function coordinationNeedsRefresh(
  scope: TaskCoordination | null | undefined,
): boolean {
  if (!scope) return false;
  return (
    ["pending", "running", "needs_user", "interrupted"].includes(scope.state) ||
    (scope.state === "idle" && scope.decision !== "ready")
  );
}

export function coordinationStatus(scope: TaskCoordination): {
  key: string;
  color?: string;
} {
  if (scope.state === "idle") {
    if (scope.decision === "ready")
      return { key: "taskQueue.coordinationReady", color: "success" };
    if (scope.decision === "continue")
      return { key: "taskQueue.coordinationContinuing", color: "blue" };
    return { key: "taskQueue.coordinationIdle" };
  }
  const states: Record<string, { key: string; color?: string }> = {
    pending: { key: "taskQueue.coordinationStates.pending", color: "blue" },
    running: {
      key: "taskQueue.coordinationStates.running",
      color: "processing",
    },
    needs_user: {
      key: "taskQueue.coordinationStates.needs_user",
      color: "warning",
    },
    interrupted: {
      key: "taskQueue.coordinationStates.interrupted",
      color: "warning",
    },
    stopped: { key: "taskQueue.coordinationStates.stopped" },
  };
  return states[scope.state] || { key: "taskQueue.coordinationUnknown" };
}

export function taskActionError(error: unknown, t: TFunction): string {
  const generic = t("taskQueue.failed");
  const apiMessage = apiErrorMessage(error, generic, t);
  const fallback = /^(?:tasks\.errors\.|taskQueue\.|apiErrors\.)/.test(
    apiMessage,
  )
    ? generic
    : apiMessage;
  const reason = parseApiError(error)?.details?.task_reason;
  if (typeof reason !== "string") return fallback;
  const key = `taskQueue.errors.${reason}`;
  const translated = t(key, fallback);
  return !translated ||
    translated === key ||
    translated.startsWith("tasks.errors.")
    ? fallback
    : translated;
}

export function pullRequestUrl(value: unknown): string | null {
  if (typeof value !== "string") return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" &&
      url.hostname === "github.com" &&
      !url.username &&
      !url.password &&
      /^\/[^/]+\/[^/]+\/pull\/\d+\/?$/.test(url.pathname)
      ? url.href
      : null;
  } catch {
    return null;
  }
}
