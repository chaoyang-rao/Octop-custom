// Isolated team API/protocol fixture; no model, account or MCP service is contacted.
async function teamUI(page) {
  const checks = [];
  const ensure = (v, n) => {
    if (!v) throw new Error(n);
    checks.push(n);
  };
  await page.addInitScript(() => {
    const uid = Number(localStorage.getItem("__teamUser") || 771);
    const f = (window.__team = { calls: [], teams: [], turn: 0 });
    const experts = [
      { agent_id: "host", name: "小通", user_id: uid },
      { agent_id: "quality", name: "售后质量专家", user_id: uid },
      { agent_id: "quota", name: "词元管理专家", user_id: uid },
      { agent_id: "foreign", name: "其他同事专家", user_id: uid + 1 },
    ];
    f.emit = (data) =>
      window.__companionEvent({
        type: "chat",
        board: "team",
        contextKey: f.context,
        data: { thread_id: f.thread, ...data },
      });
    f.finish = () => {
      f.emit({ type: "done", agent_id: "quota" });
      f.emit({
        type: "token",
        agent_id: f.agent,
        speaker_agent_id: "host",
        turn_owner_agent_id: f.agent,
        team_wrapup: true,
        content: "小通汇总完成",
      });
      f.emit({
        type: "done",
        agent_id: f.agent,
        speaker_agent_id: "host",
        turn_owner_agent_id: f.agent,
        team_wrapup: true,
      });
    };
    window.webkit = {
      messageHandlers: {
        companion: {
          postMessage({ id, op, args }) {
            f.calls.push({ op, args });
            let result = true,
              error;
            if (op === "status")
              result = {
                authenticated: true,
                companionAllowed: true,
                storageScope: "team-fixture",
                origin: "http://127.0.0.1:19777",
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
                        ...experts,
                        ...f.teams.map((t) => ({
                          agent_id: t.agent_id,
                          name: t.name,
                          user_id: uid,
                        })),
                      ]
                    : args.path === "/api/teams"
                    ? f.teams
                    : args.path === "/api/connector-instances"
                    ? [
                        {
                          mcp_server_name: "aftersales_quality",
                          display_name: "售后质量",
                          usable: true,
                        },
                      ]
                    : args.path.includes("history")
                    ? { messages: [], turn_active: false }
                    : [],
              };
            if (op === "saveTeam") {
              if (f.failSave) error = "fixture roster busy";
              else {
                const team = {
                  agent_id: args.teamId || "team-" + (f.teams.length + 1),
                  team_id: args.teamId || "team-" + (f.teams.length + 1),
                  name: args.name,
                  kind: "team",
                  primary_agent_id: "host",
                  primary_agent_name: "小通",
                  member_ids: ["host", ...args.memberIds],
                  members: [
                    experts[0],
                    ...experts.filter((a) =>
                      args.memberIds.includes(a.agent_id),
                    ),
                  ],
                };
                f.teams = [
                  ...f.teams.filter((t) => t.agent_id !== team.agent_id),
                  team,
                ];
                result = team;
              }
            }
            if (op === "chatSend" && args.frame.type === "user_turn") {
              if (!args.contextKey) error = "missing context";
              else if (args.board === "team") {
                f.context = args.contextKey;
                f.agent = args.agentId;
                f.thread = "thread-" + args.agentId;
                f.turn++;
                setTimeout(() => {
                  f.emit({
                    type: "turn.started",
                    agent_id: f.agent,
                    turn_id: "turn-" + f.turn,
                  });
                  f.emit({
                    type: "token",
                    agent_id: f.agent,
                    speaker_agent_id: "host",
                    content: "小通安排分工",
                  });
                  f.emit({
                    type: "token",
                    agent_id: "quality",
                    content: "售后第一段",
                  });
                  f.emit({
                    type: "token",
                    agent_id: "quota",
                    content: "词元第一段",
                  });
                  f.emit({
                    type: "token",
                    agent_id: "quality",
                    content: "售后第二段",
                  });
                  f.emit({ type: "done", agent_id: "quality" });
                  f.emit({
                    type: "done",
                    agent_id: f.agent,
                    speaker_agent_id: "host",
                  });
                  f.emit({ type: "turn.ended", turn_id: "turn-" + f.turn });
                }, 10);
              }
            }
            setTimeout(
              () =>
                window.__companionReply({
                  id,
                  ...(error ? { error } : { result }),
                }),
              2,
            );
          },
        },
      },
    };
  });
  await page.evaluate(() => localStorage.clear());
  await page.reload();
  await page.getByRole("button", { name: "功能与设置", exact: true }).click();
  await page.getByRole("button", { name: "团队", exact: true }).click();
  ensure(
    await page.getByText("主持人 · 固定", { exact: true }).isVisible(),
    "xiaotong_is_a_fixed_host",
  );
  ensure(
    (await page
      .getByRole("checkbox", { name: "小通", exact: true })
      .count()) === 0,
    "host_cannot_be_removed_or_replaced",
  );
  ensure(
    (await page
      .getByRole("checkbox", { name: "其他同事专家", exact: true })
      .count()) === 0,
    "foreign_experts_cannot_be_added",
  );
  await page
    .getByRole("textbox", { name: "团队名称", exact: true })
    .fill("业务团队");
  await page
    .getByRole("checkbox", { name: "售后质量专家", exact: true })
    .check();
  await page
    .getByRole("checkbox", { name: "词元管理专家", exact: true })
    .check();
  await page.getByRole("button", { name: "创建团队", exact: true }).click();
  await page.waitForFunction(() => window.__team.teams.length === 1);
  ensure(
    await page.evaluate(
      () =>
        window.__team.calls.find((c) => c.op === "saveTeam").args.hostId ===
        "host",
    ),
    "team_is_created_with_the_real_host_id",
  );
  await page.getByRole("button", { name: "关闭设置", exact: true }).click();
  const input = page.getByRole("textbox", { name: "输入问题", exact: true });
  await input.fill("团队协作问题");
  await page.getByRole("button", { name: "发送消息", exact: true }).click();
  await page.getByText("售后第一段售后第二段", { exact: true }).waitFor();
  ensure(
    (await page.getByText("词元第一段", { exact: true }).count()) === 1,
    "member_streams_do_not_merge",
  );
  ensure(
    (await page.getByText("小通 · 主持人", { exact: true }).count()) === 1,
    "host_speech_uses_xiaotong_identity",
  );
  ensure(
    await page.evaluate(() => {
      const call = window.__team.calls.find(
        (c) =>
          c.op === "chatSend" &&
          c.args.board === "team" &&
          c.args.frame.type === "user_turn",
      );
      return (
        call.args.agentId === "team-1" &&
        call.args.frame.mcp_servers.length === 0 &&
        !call.args.frame.target_agent_ids
      );
    }),
    "chat_uses_the_real_team_room_and_member_resource_policies",
  );
  await input.fill("下一轮问题");
  await page.getByRole("button", { name: "排队发送", exact: true }).click();
  ensure(
    await page.evaluate(
      () =>
        window.__team.calls.filter(
          (c) => c.op === "chatSend" && c.args.frame.type === "user_turn",
        ).length === 1,
    ),
    "member_replies_hold_the_next_round",
  );
  await page.evaluate(() => window.__team.finish());
  await page.getByText("小通汇总完成", { exact: true }).waitFor();
  ensure(
    await page.evaluate(
      () =>
        window.__team.calls.filter(
          (c) => c.op === "chatSend" && c.args.frame.type === "user_turn",
        ).length === 1,
    ),
    "team_queue_requires_explicit_next_round",
  );
  await page
    .getByRole("button", { name: "撤回待发消息 1", exact: true })
    .click();
  await page.getByRole("button", { name: "功能与设置", exact: true }).click();
  await page
    .getByRole("checkbox", { name: "词元管理专家", exact: true })
    .uncheck();
  await page.evaluate(() => (window.__team.failSave = true));
  await page.getByRole("button", { name: "保存成员", exact: true }).click();
  await page.getByText("fixture roster busy", { exact: true }).waitFor();
  ensure(
    !(await page
      .getByRole("checkbox", { name: "词元管理专家", exact: true })
      .isChecked()),
    "failed_save_preserves_unsaved_roster",
  );
  await page.evaluate(() => (window.__team.failSave = false));
  await page.getByRole("button", { name: "保存成员", exact: true }).click();
  await page.waitForFunction(
    () => window.__team.teams[0].member_ids.length === 2,
  );
  checks.push("roster_update_preserves_the_fixed_host");
  await page.getByRole("button", { name: "关闭设置", exact: true }).click();
  await input.fill("团队一草稿");
  await page.getByRole("button", { name: "功能与设置", exact: true }).click();
  await page
    .getByRole("combobox", { name: "选择团队", exact: true })
    .selectOption("");
  await page
    .getByRole("textbox", { name: "团队名称", exact: true })
    .fill("第二团队");
  await page
    .getByRole("checkbox", { name: "词元管理专家", exact: true })
    .check();
  await page.getByRole("button", { name: "创建团队", exact: true }).click();
  await page.waitForFunction(() => window.__team.teams.length === 2);
  await page
    .getByRole("combobox", { name: "选择团队", exact: true })
    .selectOption("team-1");
  await page.getByRole("button", { name: "关闭设置", exact: true }).click();
  ensure(
    (await input.inputValue()) === "团队一草稿",
    "switching_teams_preserves_each_draft",
  );
  await page.getByRole("button", { name: "功能与设置", exact: true }).click();
  await page.getByRole("button", { name: "售后", exact: true }).click();
  ensure(
    (await page
      .getByRole("combobox", { name: "回答专家", exact: true })
      .locator("option")
      .filter({ hasText: "业务团队" })
      .count()) === 0,
    "teams_do_not_replace_solo_expert_choices",
  );
  await page.getByRole("button", { name: "团队", exact: true }).click();
  await page.setViewportSize({ width: 350, height: 510 });
  ensure(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
    "team_editor_fits_minimum_window",
  );
  await page.screenshot({
    path: "desktop-companion/output/playwright/teams-settings.png",
  });
  return { fixture_only: true, passed: checks.length, checks };
}
