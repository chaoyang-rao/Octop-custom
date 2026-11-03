import { Button, Space, Tag, Typography } from "antd";
import { useTranslation } from "react-i18next";
import type {
  CoordinationContinue,
  TaskDispatchView,
} from "../../api/modules/tasks";
import { originReturned, pullRequestUrl } from "./dispatchPresentation";
import TaskCoordinationDetails from "./TaskCoordinationDetails";

interface Props {
  dispatch: TaskDispatchView;
  taskAttempt: number;
  taskState: string;
  visibleAgentIds: ReadonlySet<string>;
  openConversation: (agentId: string, threadId: string) => void;
  onContinue?: (body: CoordinationContinue) => Promise<void>;
  onStop?: () => Promise<void>;
}

export default function TaskDispatchDetails({
  dispatch,
  taskAttempt,
  taskState,
  visibleAgentIds,
  openConversation,
  onContinue,
  onStop,
}: Props) {
  const { t } = useTranslation();
  const run = dispatch.coding_run;
  const url = pullRequestUrl(run.pr_url);
  const phaseColor = run.phase?.endsWith("failed")
    ? "error"
    : run.phase === "published" || run.phase === "ready"
    ? "success"
    : ["prepared", "executing", "verifying"].includes(run.phase || "")
    ? "processing"
    : undefined;
  return (
    <Space direction="vertical" style={{ width: "100%" }}>
      {dispatch.origin_thread_id &&
        (dispatch.origin_agent_id &&
        visibleAgentIds.has(dispatch.origin_agent_id) ? (
          <Space wrap>
            <Button
              onClick={() =>
                openConversation(
                  dispatch.origin_agent_id!,
                  dispatch.origin_thread_id!,
                )
              }
            >
              {t("taskQueue.openOriginConversation")}
            </Button>
            <Typography.Text
              type={
                originReturned(dispatch, taskAttempt, taskState)
                  ? "success"
                  : "secondary"
              }
            >
              {t(
                originReturned(dispatch, taskAttempt, taskState)
                  ? "taskQueue.originReturned"
                  : "taskQueue.originReturnPending",
              )}
            </Typography.Text>
          </Space>
        ) : (
          <Typography.Text type="secondary">
            {t("taskQueue.originUnavailable")}
          </Typography.Text>
        ))}
      {dispatch.coordination && (
        <TaskCoordinationDetails
          key={dispatch.coordination.scope_id}
          scope={dispatch.coordination}
          isCoding={
            dispatch.coordination.has_coding_tasks === true ||
            !!dispatch.coding_spec
          }
          onContinue={onContinue}
          onStop={onStop}
        />
      )}
      {dispatch.coding_spec && (
        <>
          <Typography.Title level={5}>
            {t("taskQueue.codingDelivery")}
          </Typography.Title>
          {run.phase && (
            <Tag color={phaseColor}>
              {t(`taskQueue.codingPhases.${run.phase}`, run.phase)}
            </Tag>
          )}
          <Typography.Text style={{ overflowWrap: "anywhere" }}>
            {dispatch.coding_spec.project_path}
          </Typography.Text>
          {run.branch && (
            <Typography.Text>
              {t("taskQueue.codingBranch")}: {run.branch}
            </Typography.Text>
          )}
          {run.worktree && (
            <Typography.Text
              type="secondary"
              style={{ overflowWrap: "anywhere" }}
            >
              {t("taskQueue.codingWorkspace")}: {run.worktree}
            </Typography.Text>
          )}
          {run.verification?.map((check, index) => (
            <Space key={index} align="start" style={{ maxWidth: "100%" }}>
              <Tag color={check.passed ? "success" : "error"}>
                {t(
                  check.timed_out
                    ? "taskQueue.verificationTimedOut"
                    : check.passed
                    ? "taskQueue.verificationPassed"
                    : "taskQueue.verificationFailed",
                )}
              </Tag>
              <Typography.Text style={{ overflowWrap: "anywhere" }}>
                {dispatch.coding_spec?.test_commands[check.command_index] ||
                  t("taskQueue.verificationCommand", {
                    number: check.command_index + 1,
                  })}
              </Typography.Text>
            </Space>
          ))}
          {url && (
            <Typography.Link
              href={url}
              target="_blank"
              rel="noopener noreferrer"
            >
              {t("taskQueue.openPullRequest")}
            </Typography.Link>
          )}
        </>
      )}
    </Space>
  );
}
