// Isolated browser protocol fixture; never accesses a real account or service.
async function runControlChecks(page) {
  const checks = [];
  const ensure = (value, name) => {
    if (!value) throw new Error(name);
    checks.push(name);
  };
  await page.addInitScript(() => {
    const uid = Number(localStorage.getItem("__controlUser") || 901);
    const f = (window.__control = {
      calls: [],
      turn: 0,
      active: false,
      holdThread: true,
      requests: [],
    });
    f.emit = (data) =>
      window.__companionEvent({
        type: "chat",
        board: f.board,
        contextKey: f.context,
        data: { thread_id: f.thread, ...data },
      });
    f.begin = () => {
      if (!f.active || f.begun === f.turn) return;
      f.begun = f.turn;
      f.emit({ type: "turn.started", turn_id: "turn-" + f.turn });
      f.emit({
        type: "tool_call_chunk",
        name: "fixture.read",
        display_name: "隔离查询",
      });
      if (!f.holdToken) f.emit({ type: "token", content: "部分回答" });
    };
    f.finish = () => {
      f.begin();
      f.active = false;
      f.emit({ type: "done" });
      f.emit({ type: "turn.ended", turn_id: "turn-" + f.turn });
    };
    f.pause = (request) => {
      f.begin();
      f.pending = request;
      f.active = false;
      f.emit({ type: "hitl_required", request });
      f.emit({
        type: "turn.ended",
        turn_id: "turn-" + f.turn,
        hitl_paused: true,
      });
    };
    window.webkit = {
      messageHandlers: {
        companion: {
          postMessage({ id, op, args }) {
            f.calls.push({ op, args });
            let result = true;
            const reply = (error) =>
              window.__companionReply({
                id,
                ...(error ? { error } : { result }),
              });
            if (op === "status")
              result = {
                authenticated: true,
                origin: "http://127.0.0.1:19999",
                storageScope: "control-fixture",
                companionAllowed: true,
                user: { id: uid, username: "fixture" },
              };
            if (op === "api")
              result = {
                status: 200,
                data:
                  args.path === "/api/companion/access"
                    ? { allowed: true }
                    : args.path === "/api/agents"
                    ? [
                        {
                          agent_id: "owned",
                          name: "售后质量专家",
                          user_id: uid,
                          is_running: true,
                        },
                      ]
                    : args.path === "/api/connector-instances"
                    ? [
                        {
                          mcp_server_name: "aftersales_quality",
                          display_name: "售后质量",
                          usable: true,
                        },
                      ]
                    : args.path.includes("history")
                    ? {
                        messages: [],
                        turn_active: f.active,
                        hitl_pending: f.pending,
                        awaiting_user: !!f.pending,
                      }
                    : [],
              };
            if (op === "upload")
              result = {
                path: "inbound/" + args.filename,
                filename: args.filename,
                media_type: args.mimeType,
              };
            if (op === "chatSend") {
              if (!args.contextKey) return reply("missing contextKey");
              const frame = args.frame;
              f.board = args.board;
              f.context = args.contextKey;
              f.thread = frame.thread_id || "thread-" + args.contextKey;
              if (frame.type === "user_turn") {
                if (frame.delivery === "steer") {
                  if (frame.expected_turn_id !== "turn-" + f.turn)
                    return reply("wrong turn");
                  setTimeout(
                    () =>
                      f.emit({
                        type: "steer.ack",
                        client_pending_id: frame.client_pending_id,
                        pending_id: "pending-steer",
                        turn_id: "turn-" + f.turn,
                        status: "queued",
                      }),
                    10,
                  );
                } else {
                  f.turn++;
                  f.active = true;
                  f.requests.push(frame);
                  if (!f.holdThread) setTimeout(f.begin, 10);
                }
              }
              if (frame.type === "cancel") setTimeout(f.finish, 10);
              if (frame.type === "steer_remove")
                setTimeout(
                  () =>
                    f.emit({
                      type: "steer.removed",
                      client_pending_id: frame.client_pending_id,
                      pending_id: frame.pending_id,
                    }),
                  10,
                );
            }
            if (op === "resumeApproval") {
              if (!args.contextKey || !args.pendingId)
                return reply("missing approval identity");
              if (f.rejectResume) return reply("fixture approval unavailable");
              if (f.delayResume)
                return setTimeout(() => {
                  f.delayedReply = true;
                  reply("fixture stopped during confirmation");
                }, 500);
              f.pending = null;
              setTimeout(() => {
                f.emit({ type: "turn.resumed", turn_id: "turn-" + f.turn });
                f.emit({ type: "token", content: "确认后继续" });
                f.finish();
              }, 20);
            }
            setTimeout(() => reply(), 1);
          },
        },
      },
    };
  });
  await page.evaluate(() => localStorage.clear());
  await page.reload();
  const input = page.getByRole("textbox", { name: "输入问题", exact: true });
  await input.waitFor();
  await input.fill("第一条问题");
  await page.getByRole("button", { name: "发送消息", exact: true }).click();
  await page.getByRole("button", { name: "停止回答", exact: true }).click();
  ensure(
    await page.evaluate(
      () =>
        !window.__control.calls.some(
          (c) => c.op === "chatSend" && c.args.frame.type === "cancel",
        ),
    ),
    "early_stop_waits_for_thread_identity",
  );
  await page.evaluate(() => window.__control.begin());
  await page.getByRole("button", { name: "发送消息", exact: true }).waitFor();
  ensure(
    await page.evaluate(() =>
      window.__control.calls.some(
        (c) =>
          c.op === "chatSend" &&
          c.args.frame.type === "cancel" &&
          c.args.contextKey,
      ),
    ),
    "stop_reaches_bridge_with_required_identity",
  );
  await page.evaluate(() => {
    window.__control.holdThread = false;
  });
  await page.evaluate(() => (window.__control.holdToken = true));
  await input.fill("继续第一轮");
  await page.getByRole("button", { name: "发送消息", exact: true }).click();
  await page.getByRole("status", { name: "正在回答", exact: true }).waitFor();
  ensure(
    (await page.locator(".thinking").textContent()) === "",
    "waiting_indicator_has_no_paintable_status_text",
  );
  await page.screenshot({
    path: "desktop-companion/output/playwright/waiting-indicator.png",
  });
  await page.evaluate(() => {
    window.__control.holdToken = false;
    window.__control.emit({ type: "token", content: "部分回答" });
  });
  await input.fill("只看本周");
  await page.getByRole("button", { name: "补充本轮", exact: true }).click();
  await page.getByText("等待本轮接收", { exact: false }).waitFor();
  ensure(
    await page.evaluate(() =>
      window.__control.calls.some(
        (c) =>
          c.op === "chatSend" &&
          c.args.frame.delivery === "steer" &&
          c.args.frame.expected_turn_id,
      ),
    ),
    "mid_turn_supplement_targets_active_turn",
  );
  await page.getByRole("button", { name: "撤回", exact: true }).click();
  await page.getByText("已撤回", { exact: true }).waitFor();
  checks.push("committed_supplement_can_be_withdrawn");
  await input.fill("第二条任务");
  await page.getByRole("button", { name: "排队发送", exact: true }).click();
  ensure(
    await page.evaluate(() => window.__control.requests.length === 2),
    "queued_message_waits_for_current_turn",
  );
  await page.evaluate(() => window.__control.finish());
  await page.waitForFunction(() => window.__control.requests.length === 3);
  checks.push("queued_message_runs_after_authoritative_end");
  await input.fill("保留的下一条");
  await page.getByRole("button", { name: "排队发送", exact: true }).click();
  await page.getByRole("button", { name: "停止回答", exact: true }).click();
  await page.getByRole("button", { name: "继续发送", exact: true }).waitFor();
  ensure(
    await page.evaluate(() => {
      const composer = document
          .querySelector(".composer")
          .getBoundingClientRect(),
        status = document.querySelector(".control-status"),
        queue = document
          .querySelector(".queued-inputs")
          .getBoundingClientRect();
      return (
        parseFloat(getComputedStyle(status).paddingLeft) >= 10 &&
        queue.left >= composer.left + 10 &&
        queue.right <= composer.right - 10
      );
    }),
    "stop_and_queue_status_stay_inside_glass_corners",
  );
  await page.screenshot({
    path: "desktop-companion/output/playwright/stopped-queue-status.png",
  });
  ensure(
    await page.evaluate(() => window.__control.requests.length === 3),
    "stop_preserves_queue_without_automatically_running_it",
  );
  await page.getByRole("button", { name: "继续发送", exact: true }).click();
  await page.waitForFunction(() => window.__control.requests.length === 4);
  await page.evaluate(() =>
    window.__control.pause({
      pending_id: "approval-1",
      action_requests: [
        {
          name: "report.create",
          description: "生成当前报告",
          args: { period: "本周" },
        },
      ],
    }),
  );
  await page.getByRole("button", { name: "确认这一次", exact: true }).waitFor();
  await page.evaluate(() => window.__companionEvent({type:"refreshResources"}));
  await page.getByRole("button", { name: "确认这一次", exact: true }).waitFor();
  checks.push("pending_approval_is_recovered_from_backend_history");
  await page.evaluate(() => (window.__control.rejectResume = true));
  await page.getByRole("button", { name: "确认这一次", exact: true }).click();
  await page
    .getByText("fixture approval unavailable", { exact: false })
    .waitFor();
  ensure(
    await page
      .getByRole("button", { name: "确认这一次", exact: true })
      .isEnabled(),
    "failed_approval_stays_recoverable",
  );
  await page.evaluate(() => (window.__control.rejectResume = false));
  await page.getByRole("button", { name: "确认这一次", exact: true }).click();
  await page.getByText("已确认", { exact: true }).waitFor();
  checks.push("approval_resumes_without_leaving_companion");
  await input.fill("需要追问的任务");
  await page.getByRole("button", { name: "发送消息", exact: true }).click();
  await page.evaluate(() =>
    window.__control.pause({
      pending_id: "question-1",
      action_requests: [
        {
          name: "ask_user_question",
          args: {
            questions: [
              {
                question: "分析哪个时间段？",
                options: [{ label: "本周" }, { label: "上周" }],
              },
            ],
          },
        },
      ],
    }),
  );
  await page.getByRole("button", { name: "本周", exact: true }).click();
  await page.getByRole("button", { name: "提交回答", exact: true }).click();
  await page.getByText("已提交回答", { exact: true }).waitFor();
  ensure(
    await page.evaluate(() =>
      window.__control.calls.some(
        (c) =>
          c.op === "resumeApproval" &&
          c.args.pendingId === "question-1" &&
          c.args.decisions[0].type === "respond" &&
          c.args.decisions[0].message.includes("本周") &&
          !c.args.hitl_policy,
      ),
    ),
    "question_answer_uses_existing_approval_policy",
  );
  await page.locator("input[type=file]").setInputFiles({
    name: "销售.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("sku,count\na,2"),
  });
  await page.getByText("销售.csv", { exact: true }).waitFor();
  await input.fill("分析这个文件");
  await page.getByRole("button", { name: "发送消息", exact: true }).click();
  ensure(
    await page.evaluate(() =>
      window.__control.requests
        .at(-1)
        .messages[0].content.some(
          (b) => b.type === "file" && b.workspace_path === "inbound/销售.csv",
        ),
    ),
    "csv_is_uploaded_and_sent_as_a_file",
  );
  await page.evaluate(() => window.__control.finish());
  const message = page
    .locator("article.message.user")
    .filter({ hasText: "分析这个文件" })
    .last();
  await message.locator("summary[aria-label=消息操作]").click();
  await message
    .getByRole("button", { name: "编辑后再发", exact: true })
    .click();
  ensure(
    (await input.inputValue()) === "分析这个文件",
    "edit_resend_keeps_original_message_and_restores_input",
  );
  await input.fill("");
  await page
    .getByRole("button", { name: "移除 销售.csv", exact: true })
    .click();
  const assistant = page.locator("article.message.assistant").last();
  await assistant.locator("summary[aria-label=消息操作]").click();
  await assistant
    .getByRole("button", { name: "重新回答", exact: true })
    .click();
  await page.waitForFunction(() => window.__control.requests.length === 7);
  checks.push("regenerate_resends_previous_question_with_its_attachment");
  await page.setViewportSize({ width: 350, height: 510 });
  ensure(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth <= innerWidth &&
        document.documentElement.scrollHeight <= innerHeight,
    ),
    "small_window_has_no_control_overflow",
  );
  await page.screenshot({
    path: "desktop-companion/output/playwright/chat-controls.png",
  });
  await input.fill("重开后需要保留的待发消息");
  await page.getByRole("button", { name: "排队发送", exact: true }).click();
  await page.reload();
  await page.getByRole("button", { name: "继续发送", exact: true }).waitFor();
  ensure(
    await page.evaluate(() => window.__control.requests.length === 0),
    "reopening_preserves_queue_but_requires_explicit_resume",
  );
  await page.evaluate(() => localStorage.setItem("__controlUser", "902"));
  await page.reload();
  await page.getByRole("button", { name: "发送消息", exact: true }).waitFor();
  ensure(
    (await page
      .getByText("重开后需要保留的待发消息", { exact: true })
      .count()) === 0,
    "another_account_cannot_inherit_queued_work",
  );
  await input.fill("取消进行中的确认");
  await page.getByRole("button", { name: "发送消息", exact: true }).click();
  await page.evaluate(() => {
    window.__control.pause({
      pending_id: "delayed-approval",
      action_requests: [{ name: "fixture.read" }],
    });
    window.__control.delayResume = true;
  });
  await page.getByRole("button", { name: "确认这一次", exact: true }).click();
  await page.getByRole("button", { name: "停止回答", exact: true }).click();
  await page.waitForFunction(() => window.__control.delayedReply);
  ensure(
    (await page.getByText("已确认", { exact: true }).count()) === 0,
    "stopping_inflight_confirmation_never_shows_false_approval",
  );
  return { fixture_only: true, passed: checks.length, checks };
}
