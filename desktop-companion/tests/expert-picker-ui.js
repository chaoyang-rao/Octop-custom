// Isolated UI/native-bridge fixture; no real account, model or business service.
async function expertPickerUI(page) {
  const checks = [];
  const ensure = (ok, name) => {
    if (!ok) throw new Error(name);
    checks.push(name);
  };
  await page.addInitScript(() => {
    const uid = Number(localStorage.getItem("__pickerUser") || 71);
    const experts = [
      { agent_id: "quality", name: "售后质量专家", user_id: uid },
      { agent_id: "supplier", name: "供应商绩效专家", user_id: uid },
      { agent_id: "demand", name: "需求管理专家", user_id: uid },
      { agent_id: "host", name: "小通", user_id: uid },
      { agent_id: "foreign", name: "其他同事专家", user_id: uid + 1 },
    ];
    const team = {
      agent_id: "team-1",
      team_id: "team-1",
      kind: "team",
      name: "协作团队",
      primary_agent_id: "host",
      primary_agent_name: "小通",
      member_ids: ["host", "quality"],
      members: experts.filter((a) => ["host", "quality"].includes(a.agent_id)),
    };
    const f = (window.__picker = { calls: [], histories: {}, hold: false });
    f.emit = (frame) =>
      window.__companionEvent({
        type: "chat",
        board: f.current.board,
        contextKey: f.current.contextKey,
        data: { thread_id: f.current.thread, ...frame },
      });
    f.finish = () => {
      f.emit({ type: "token", content: "隔离回复：" + f.current.agentId });
      f.emit({ type: "done" });
      f.emit({ type: "turn.ended", turn_id: "turn-" + f.current.agentId });
      f.histories[f.current.thread] = [
        { role: "user", content: f.current.text },
        { role: "assistant", content: "隔离回复：" + f.current.agentId },
      ];
    };
    window.webkit = {
      messageHandlers: {
        companion: {
          postMessage({ id, op, args }) {
            f.calls.push({ op, args });
            let result = true;
            if (op === "status")
              result = {
                authenticated: true,
                companionAllowed: true,
                standalone: true,
                origin: "http://127.0.0.1:19778",
                storageScope: "picker-fixture",
                user: { id: uid, username: "fixture" },
              };
            if (op === "api")
              result = {
                status: 200,
                data:
                  args.path === "/api/agents"
                    ? [
                        ...experts,
                        {
                          agent_id: team.agent_id,
                          name: team.name,
                          user_id: uid,
                        },
                      ]
                    : args.path === "/api/teams"
                    ? [team]
                    : args.path === "/api/companion/access"
                    ? { allowed: true }
                    : args.path.includes("/history")
                    ? {
                        messages:
                          f.histories[
                            args.path.match(/threads\/([^/]+)/)?.[1]
                          ] || [],
                        turn_active: false,
                      }
                    : [],
              };
            if (op === "chatSend" && args.frame.type === "user_turn") {
              f.current = {
                ...args,
                thread:
                  args.frame.thread_id ||
                  "thread-" +
                    args.agentId +
                    "-" +
                    (f.counter = (f.counter || 0) + 1),
                text: args.frame.messages[0].content[0].text,
              };
              f.started = false;
              setTimeout(() => {
                f.started = true;
                f.emit({
                  type: "turn.started",
                  turn_id: "turn-" + args.agentId,
                });
                if (!f.hold) f.finish();
              }, 15);
            }
            setTimeout(() => window.__companionReply({ id, result }), 2);
          },
        },
      },
    };
    if (!localStorage.getItem("__pickerSeeded")) {
      localStorage.setItem("__pickerSeeded", "true");
      localStorage.setItem(
        "octop-companion:v1:picker-fixture:" + uid,
        JSON.stringify({
          voice: false,
          active: "aftersales",
          rooms: {
            aftersales: {
              binding: {
                agentId: "quality",
                connectors: ["legacy-wrong-mcp"],
                knowledgeBases: [],
              },
              conversationId: "legacy-context",
            },
          },
        }),
      );
    }
  });
  await page.evaluate(() => localStorage.clear());
  await page.reload();
  const picker = page.getByRole("combobox", {
    name: "快捷选择专家",
    exact: true,
  });
  const input = page.getByRole("textbox", { name: "输入问题", exact: true });
  await picker.waitFor();
  ensure(
    (await picker.inputValue()) === "expert:quality",
    "expert_switcher_is_next_to_dora_without_opening_settings",
  );
  ensure(
    (await picker
      .getByRole("option", { name: "其他同事专家", exact: true })
      .count()) === 0,
    "foreign_experts_are_not_offered",
  );
  await input.fill("使用已绑定售后 MCP");
  await page.getByRole("button", { name: "发送消息", exact: true }).click();
  await page.getByText("隔离回复：quality", { exact: true }).waitFor();
  ensure(
    await page.evaluate(
      () =>
        !Object.hasOwn(
          window.__picker.calls.find(
            (c) => c.op === "chatSend" && c.args.frame.type === "user_turn",
          ).args.frame,
          "mcp_servers",
        ),
    ),
    "legacy_board_checkboxes_cannot_override_the_expert_binding",
  );
  await picker.selectOption("expert:supplier");
  ensure((await input.inputValue()) === "", "new_expert_starts_its_own_draft");
  await input.fill("供应商问题");
  await page.getByRole("button", { name: "发送消息", exact: true }).click();
  await page.getByText("隔离回复：supplier", { exact: true }).waitFor();
  ensure(
    await page.evaluate(
      () =>
        window.__picker.calls
          .filter(
            (c) => c.op === "chatSend" && c.args.frame.type === "user_turn",
          )
          .at(-1).args.agentId === "supplier",
    ),
    "quick_selection_sends_to_the_selected_expert",
  );
  await input.fill("供应商草稿");
  await picker.selectOption("expert:demand");
  await input.fill("需求草稿");
  await picker.selectOption("expert:supplier");
  ensure(
    (await input.inputValue()) === "供应商草稿",
    "switching_back_restores_each_experts_draft",
  );
  await page.getByText("隔离回复：supplier", { exact: true }).waitFor();
  ensure(
    (await page.getByText("隔离回复：quality", { exact: true }).count()) === 0,
    "expert_conversations_remain_separate",
  );
  await picker.selectOption("expert:demand");
  ensure(
    (await input.inputValue()) === "需求草稿",
    "another_experts_draft_is_preserved",
  );
  await page.waitForFunction(
    () =>
      JSON.parse(localStorage.getItem("octop-companion:v1:picker-fixture:71"))
        .expertSessions["aftersales:supplier"].draft === "供应商草稿",
  );
  await page.reload();
  await picker.selectOption("expert:supplier");
  ensure(
    (await input.inputValue()) === "供应商草稿",
    "expert_drafts_survive_reopening_the_companion",
  );
  await page.evaluate(() => (window.__picker.hold = true));
  await input.fill("等待回复");
  await page.getByRole("button", { name: "发送消息", exact: true }).click();
  await page.getByRole("button", { name: "停止回答", exact: true }).waitFor();
  await page.waitForFunction(() => window.__picker.started);
  ensure(
    await picker.isDisabled(),
    "active_turns_cannot_be_rebound_to_another_expert",
  );
  ensure(
    await page
      .getByRole("button", { name: "新对话", exact: true })
      .isDisabled(),
    "new_chat_does_not_discard_an_active_turn",
  );
  await page.evaluate(() => window.__picker.finish());
  await page.waitForFunction(
    () => !document.querySelector('[aria-label="快捷选择专家"]').disabled,
  );
  await input.fill("新对话保留的草稿");
  const prior = await page.evaluate(
    () =>
      window.__picker.calls
        .filter((c) => c.op === "chatSend" && c.args.frame.type === "user_turn")
        .at(-1).args.frame.session_key,
  );
  await page.getByRole("button", { name: "新对话", exact: true }).click();
  ensure(
    (await input.inputValue()) === "新对话保留的草稿",
    "new_chat_is_available_in_the_chat_header_and_keeps_the_composition",
  );
  await page.evaluate(() => (window.__picker.hold = false));
  await page.getByRole("button", { name: "发送消息", exact: true }).click();
  await page.getByText("隔离回复：supplier", { exact: true }).waitFor();
  ensure(
    await page.evaluate((previous) => {
      const f = window.__picker.calls
        .filter((c) => c.op === "chatSend" && c.args.frame.type === "user_turn")
        .at(-1).args.frame;
      return !f.thread_id && f.session_key !== previous;
    }, prior),
    "new_chat_clears_the_previous_thread_identity",
  );
  await page.getByRole("button", { name: "新对话", exact: true }).focus();
  await page
    .getByRole("button", { name: "新对话", exact: true })
    .press("Shift+Tab");
  await picker.hover();
  ensure(
    await picker.evaluate(
      (el) =>
        el.matches(":focus-visible") &&
        getComputedStyle(el).outlineStyle === "none" &&
        getComputedStyle(el).opacity === "0" &&
        getComputedStyle(
          el.parentElement.querySelector(".expert-picker-label"),
        ).textDecorationLine.includes("underline") &&
        getComputedStyle(el).backgroundColor.replace(/\s/g, "").endsWith(",0)"),
    ),
    "expert_selection_has_no_outer_black_focus_frame",
  );
  await page.getByRole("button", { name: "功能与设置", exact: true }).click();
  ensure(
    (await page
      .getByRole("group", { name: "连接器（MCP）", exact: true })
      .count()) === 0,
    "companion_has_no_manual_mcp_checkbox_step",
  );
  const panel = page.getByRole("region", { name: "功能与设置", exact: true });
  ensure(
    JSON.stringify(await panel.getByRole("button").allTextContents()) ===
      JSON.stringify(["知识库", "团队", "管理知识库"]),
    "settings_keep_only_knowledge_and_team_configuration",
  );
  ensure(
    (await panel
      .getByRole("button", { name: "新对话", exact: true })
      .count()) === 0,
    "new_chat_is_not_buried_in_settings",
  );
  await page.getByRole("button", { name: "关闭设置", exact: true }).click();
  await picker.selectOption("team:team-1");
  await page.getByRole("button", { name: "功能与设置", exact: true }).click();
  ensure(
    await page.getByText("主持人 · 固定", { exact: true }).isVisible(),
    "teams_keep_xiaotong_as_fixed_host",
  );
  await page.getByRole("button", { name: "关闭设置", exact: true }).click();
  await page.setViewportSize({ width: 350, height: 510 });
  ensure(
    await page.evaluate(() => {
      const r = document
          .querySelector(".expert-picker")
          .getBoundingClientRect(),
        s = document.querySelector(".settings-trigger").getBoundingClientRect();
      const n = document
        .querySelector(".new-chat-trigger")
        .getBoundingClientRect();
      return (
        r.left === 166 &&
        r.right + 6 <= n.left &&
        n.right + 2 <= s.left &&
        r.height <= 28 &&
        document.documentElement.scrollWidth <= innerWidth
      );
    }),
    "selector_fits_the_small_window_without_hiding_settings",
  );
  await page.screenshot({
    path: "desktop-companion/output/playwright/expert-picker.png",
  });
  await page.emulateMedia({ colorScheme: "dark" });
  await page.getByRole("button", { name: "新对话", exact: true }).focus();
  await page
    .getByRole("button", { name: "新对话", exact: true })
    .press("Shift+Tab");
  ensure(
    await picker.evaluate(
      (el) =>
        getComputedStyle(el).outlineStyle === "none" &&
        getComputedStyle(el).opacity === "0" &&
        getComputedStyle(
          el.parentElement.querySelector(".expert-picker-label"),
        ).textDecorationLine.includes("underline"),
    ),
    "dark_theme_keeps_keyboard_focus_without_an_outer_frame",
  );
  await page.evaluate(() => localStorage.setItem("__pickerUser", "72"));
  await page.reload();
  ensure(
    (await input.inputValue()) === "",
    "another_account_cannot_inherit_expert_drafts",
  );
  return { fixture_only: true, passed: checks.length, checks };
}
