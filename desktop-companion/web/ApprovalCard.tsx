import React, { useState } from "react";
import {
  extractAskQuestions,
  parseActionArgs,
} from "../../dashboard/src/api/types/hitl.ts";
import type { Approval } from "./controls";

export default function ApprovalCard({
  approval,
  onDecision,
  onRefresh,
  blocked,
}: {
  approval: Approval;
  onDecision: (decisions: { type: string; message?: string }[]) => void;
  onRefresh: () => void;
  blocked: boolean;
}) {
  const questions = extractAskQuestions(approval.action_requests);
  const [picked, setPicked] = useState<string[][]>(questions.map(() => []));
  const [written, setWritten] = useState<string[]>(questions.map(() => ""));
  const active = approval.status === "pending" && !blocked;
  const actions = approval.action_requests;
  const hasOperations = actions.some((a) => a.name !== "ask_user_question");
  const allowed = actions.every(
    (a) =>
      a.name === "ask_user_question" ||
      !approval.review_configs?.some(
        (r) =>
          r.action_name === a.name && !r.allowed_decisions.includes("approve"),
      ),
  );
  const answers = questions.map(
    (q, i) =>
      `${q.question}\n${[...(picked[i] || []), written[i]?.trim()]
        .filter(Boolean)
        .join("；")}`,
  );
  const ready =
    questions.every((_, i) => picked[i]?.length || written[i]?.trim()) &&
    answers.join("\n").length <= 8000;
  const decide = (reject = false) =>
    onDecision(
      actions.map((a) =>
        reject
          ? { type: "reject", message: "用户拒绝了这次请求。" }
          : a.name === "ask_user_question"
          ? { type: "respond", message: answers.join("\n\n") }
          : { type: "approve" },
      ),
    );
  return (
    <section
      className="approval-card"
      aria-label={questions.length ? "专家追问" : "操作确认"}
    >
      <strong>{questions.length ? "专家需要你补充" : "确认本次操作"}</strong>
      {["approved", "rejected"].includes(approval.status) ? (
        <p>
          {approval.status === "rejected"
            ? "已拒绝"
            : questions.length
            ? "已提交回答"
            : "已确认"}
        </p>
      ) : (
        <>
          {actions
            .filter((a) => a.name !== "ask_user_question")
            .map((action, i) => (
              <details key={i} open={actions.length === 1}>
                <summary>{action.description || action.name}</summary>
                <pre>
                  {JSON.stringify(parseActionArgs(action.args), null, 2)}
                </pre>
              </details>
            ))}
          {questions.map((q, i) => (
            <fieldset key={i} disabled={!active}>
              <legend>{q.question}</legend>
              <div className="answer-options">
                {q.options?.map((option) => (
                  <button
                    key={option.label}
                    type="button"
                    aria-pressed={picked[i]?.includes(option.label) || false}
                    onClick={() =>
                      setPicked((old) =>
                        old.map((v, j) =>
                          j !== i
                            ? v
                            : q.multi_select
                            ? v.includes(option.label)
                              ? v.filter((x) => x !== option.label)
                              : [...v, option.label]
                            : [option.label],
                        ),
                      )
                    }
                  >
                    {option.label}
                    {option.description && <small>{option.description}</small>}
                  </button>
                ))}
              </div>
              <textarea
                aria-label={`回答：${q.question}`}
                placeholder={
                  q.options?.length ? "补充或其他答案…" : "输入回答…"
                }
                value={written[i] || ""}
                maxLength={8000}
                onChange={(e) =>
                  setWritten((old) =>
                    old.map((v, j) => (j === i ? e.target.value : v)),
                  )
                }
              />
            </fieldset>
          ))}
          {approval.error && (
            <p role="alert">
              {approval.error}
              <button onClick={onRefresh}>刷新确认状态</button>
            </p>
          )}
          {!approval.pending_id ? (
            <button onClick={onRefresh}>刷新确认状态</button>
          ) : (
            <div className="approval-actions">
              <button
                disabled={!active || !ready || !allowed}
                onClick={() => decide()}
              >
                {approval.status === "submitting"
                  ? "正在提交…"
                  : questions.length
                  ? hasOperations
                    ? "提交回答并确认操作"
                    : "提交回答"
                  : "确认这一次"}
              </button>
              <button disabled={!active} onClick={() => decide(true)}>
                拒绝
              </button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
