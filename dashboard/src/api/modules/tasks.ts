import { request, requestBlob } from "../request";

export type TaskState =
  | "queued"
  | "paused"
  | "running"
  | "waiting"
  | "completed"
  | "failed"
  | "cancelled"
  | "interrupted";
export interface TaskAttachment {
  workspace_path: string;
  filename: string;
  mime_type: string;
  size?: number;
  sha256?: string;
  upload_receipt?: string;
}
export interface TaskOptions {
  model?: string;
  mcp_servers?: string[];
  skills?: string[];
  knowledge_base_ids?: string[];
  conversation_mode?: "ask" | "plan" | "craft";
  quiet?: boolean;
  attachments?: TaskAttachment[];
}
export interface QueuedTask {
  id: string;
  task_id: string;
  user_id: number;
  agent_id: string;
  thread_id: string | null;
  title: string;
  state: TaskState;
  run_id: string | null;
  step_key: string | null;
  dependencies: string[];
  archived: boolean;
  attempt: number;
  error_code: string | null;
  created_at: number;
  updated_at: number;
  started_at: number | null;
  finished_at: number | null;
}
export interface TaskDetail extends QueuedTask {
  prompt: string;
  result: string;
  options: TaskOptions;
  events: {
    action: string;
    state: TaskState;
    actor_user_id: number | null;
    created_at: number;
  }[];
}
export interface TaskCreate {
  agent_id: string;
  title: string;
  prompt: string;
  thread_id?: string;
  options?: TaskOptions;
  attachments?: TaskAttachment[];
}
export type TaskAction =
  | "pause"
  | "resume"
  | "retry"
  | "cancel"
  | "archive"
  | "restore"
  | "reassign";
export interface WorkflowStep {
  key: string;
  title: string;
  agent_id: string;
  prompt: string;
  depends_on: string[];
  options?: TaskOptions;
}
export interface WorkflowDefinition {
  steps: WorkflowStep[];
  schedule?: string | null;
  failure_policy?: "pause" | "continue";
  quiet?: boolean;
}
export interface TaskWorkflow {
  id: string;
  name: string;
  user_id: number;
  definition: WorkflowDefinition;
  enabled: boolean;
  webhook_enabled: boolean;
  next_run_at?: number | null;
  last_run_at?: number | null;
  schedule_paused?: boolean;
  created_at: number;
  updated_at: number;
}
export interface WorkflowRun {
  run_id: string;
  workflow_id: string | null;
  name: string;
  source: string;
  state: string;
  created_at: number;
  tasks: QueuedTask[];
}
export const taskQueueApi = {
  list: (archived = false, agentId?: string) =>
    request<QueuedTask[]>(
      `/tasks?archived=${archived}${
        agentId ? `&agent_id=${encodeURIComponent(agentId)}` : ""
      }`,
    ),
  detail: (id: string) =>
    request<TaskDetail>(`/tasks/${encodeURIComponent(id)}`),
  create: (body: TaskCreate) =>
    request<QueuedTask>("/tasks", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  action: (
    id: string,
    action: TaskAction,
    agentId?: string,
    expectedAttempt?: number,
  ) =>
    request<QueuedTask>(`/tasks/${encodeURIComponent(id)}/actions`, {
      method: "POST",
      body: JSON.stringify({
        action,
        agent_id: agentId,
        expected_attempt: expectedAttempt,
      }),
    }),
  controls: () => request<Record<string, boolean>>("/tasks/queue-controls"),
  pauseQueue: (agentId: string, paused: boolean) =>
    request<{ paused: boolean }>(
      `/tasks/queue-controls/${encodeURIComponent(agentId)}`,
      { method: "PUT", body: JSON.stringify({ paused }) },
    ),
  workflows: () => request<TaskWorkflow[]>("/task-workflows"),
  saveWorkflow: (
    body: { name: string; definition: WorkflowDefinition; enabled: boolean },
    id?: string,
  ) =>
    request<TaskWorkflow>(
      id ? `/task-workflows/${encodeURIComponent(id)}` : "/task-workflows",
      { method: id ? "PUT" : "POST", body: JSON.stringify(body) },
    ),
  runWorkflow: (id: string) =>
    request<{ run_id: string }>(
      `/task-workflows/${encodeURIComponent(id)}/runs`,
      { method: "POST", body: JSON.stringify({}) },
    ),
  runs: () => request<WorkflowRun[]>("/task-runs"),
  deleteWorkflow: (id: string) =>
    request<void>(`/task-workflows/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
  pauseSchedule: (id: string, paused: boolean) =>
    request<{ paused: boolean }>(
      `/task-workflows/${encodeURIComponent(id)}/schedule`,
      { method: "PUT", body: JSON.stringify({ paused }) },
    ),
  calendarBlob: () => requestBlob("/tasks-calendar"),
  calendarToken: (enabled: boolean) =>
    request<{ path: string | null }>("/tasks-calendar/token", {
      method: "PUT",
      body: JSON.stringify({ enabled }),
    }),
  webhook: (id: string, enabled: boolean) =>
    request<{ token: string | null; path: string }>(
      `/task-workflows/${encodeURIComponent(id)}/webhook`,
      { method: "PUT", body: JSON.stringify({ enabled }) },
    ),
};
