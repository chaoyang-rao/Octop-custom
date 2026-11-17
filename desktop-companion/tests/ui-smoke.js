// Run with playwright-cli run-code --filename. This isolated browser fixture
// tests UI behavior only; it never connects to a real Octop or model service.
async function runUISmoke(page) {
  const checks = [];
  async function selectBoard(name) {
    await page.getByRole("button", { name: "功能与设置", exact: true }).click();
    await page.getByRole("button", { name, exact: true }).click();
    await page.getByRole("button", { name: "关闭设置", exact: true }).click();
  }
  const ensure = (value, name) => {
    if (!value) throw new Error(name);
    checks.push(name);
  };
  async function checkCompactTitlebar(name) {
    ensure(await page.evaluate(() => {
      const top = document.querySelector(".topbar").getBoundingClientRect();
      const mark = document.querySelector(".app-mark").getBoundingClientRect();
      const settings = document.querySelector(".settings-trigger").getBoundingClientRect();
      return top.y === 0 && top.height <= 40 && mark.x >= 80 &&
        mark.right + 6 <= settings.left && settings.right <= window.innerWidth &&
        settings.top >= top.top && settings.bottom <= top.bottom;
    }), name);
  }
  await page.addInitScript(() => {
    const pixel =
      "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a9WQAAAAASUVORK5CYII=";
    window.__fixture = { calls: [], hideConnections: false };
    const uid = Number(localStorage.getItem("__fixtureUser") || 999);
    window.webkit = {
      messageHandlers: {
        companion: {
          postMessage({ id, op, args }) {
            window.__fixture.calls.push({ op, args });
            let result = true;
            if (op === "status")
              result = {
                authenticated: true,
                origin: "http://127.0.0.1:18588",
                standalone: true,
                storageScope: "companion-local-v1",
                user: {
                  id: uid,
                  username: "fixture",
                  display_name: "界面测试账号",
                },
              };
            if (op === "api")
              result = {
                status: 200,
                data:
                  args.path === "/api/agents"
                    ? [
                        { agent_id: "main", name: "小通", user_id: uid },
                        {
                          agent_id: "foreign",
                          name: "其他成员专家",
                          user_id: uid + 1,
                        },
                      ]
                    : args.path === "/api/connector-instances"
                    ? window.__fixture.hideConnections
                      ? []
                      : [
                          {
                            mcp_server_name: "aftersales_quality",
                            display_name: "售后质量",
                            usable: true,
                          },
                          {
                            mcp_server_name: "aiq_workbench_readonly",
                            display_name: "词元管理",
                            usable: true,
                          },
                        ]
                    : args.path === "/api/knowledge-bases"
                    ? [{ id: "kb-test", name: "测试知识库" }]
                    : { messages: [] },
              };
            if (op === "image") result = { url: pixel };
            if (op === "upload")
              result = {
                path: "inbound/fixture-image.png",
                filename: args.filename,
                media_type: args.mimeType,
              };
            setTimeout(() => window.__companionReply({ id, result }), 5);
            if (op === "chatSend" && args.frame.type === "user_turn") {
              const emit = (data) =>
                window.__companionEvent({
                  type: "chat",
                  board: args.board,
                  contextKey: args.contextKey,
                  data: { thread_id: "fixture-" + args.board, ...data },
                });
              setTimeout(
                () =>
                  emit({
                    type: "tool_call_chunk",
                    name: "fixture_query",
                    display_name: "界面测试工具",
                  }),
                15,
              );
              setTimeout(
                () =>
                  emit({
                    type: "reasoning",
                    content: "只有展开后才显示的界面测试过程",
                  }),
                25,
              );
              setTimeout(
                () =>
                  emit({
                    type: "token",
                    agent_id: "main",
                    content:
                      "界面测试回答。\n\n|项目|结果|\n|---|---|\n|状态|通过|",
                  }),
                40,
              );
              setTimeout(
                () =>
                  emit({
                    type: "attachment",
                    kind: "image",
                    mime_type: "image/png",
                    url: "/api/agents/main/media/preview?source=outbound/fixture.png",
                  }),
                50,
              );
              setTimeout(() => emit({ type: "done", agent_id: "main" }), 70);
            }
            if (op === "startListening")
              setTimeout(() => {
                window.__companionEvent({ type: "voice", data: "started" });
                window.__companionEvent({
                  type: "voice",
                  text: "语音输入界面测试",
                });
              }, 10);
            if (op === "stopListening")
              setTimeout(
                () =>
                  window.__companionEvent({ type: "voice", data: "stopped" }),
                10,
              );
          },
        },
      },
    };
  });
  await page.evaluate(() => localStorage.clear());
  await page.reload();
  await page.setViewportSize({ width: 456, height: 684 });
  await page
    .locator('textarea[aria-label="输入问题"]:not([disabled])')
    .waitFor();
  const input = page.getByRole("textbox", { name: "输入问题", exact: true });
  await checkCompactTitlebar("compact_titlebar_gives_chat_more_height");
  ensure(
    (await page.locator(".topbar button").count()) === 1,
    "one_top_level_settings_entry",
  );
  for (const text of [
    "从这里问起",
    "本机运行",
    "会话保存在本机",
    "选择专家与连接器",
  ])
    ensure(
      (await page.getByText(text, { exact: false }).count()) === 0,
      "no_permanent_explainer_" + text,
    );
  await page.getByRole("button", { name: "功能与设置", exact: true }).click();
  await page.getByRole("button", { name: "负利润", exact: true }).waitFor();
  ensure(!(await input.isVisible()), "settings_do_not_overlap_composer");
  await page.keyboard.press("Escape");
  ensure(
    !(await page
      .getByRole("region", { name: "功能与设置", exact: true })
      .isVisible()),
    "settings_escape_closes_dialog",
  );

  await input.fill("售后草稿");
  await selectBoard("词元");
  ensure(
    (await input.inputValue()) === "",
    "boards_start_with_separate_drafts",
  );
  await input.fill("词元草稿");
  await selectBoard("售后");
  ensure(
    (await input.inputValue()) === "售后草稿",
    "switching_board_keeps_draft",
  );
  await page.getByRole("button", { name: "发送消息", exact: true }).click();
  await page.getByText("界面测试回答。", { exact: true }).waitFor();
  await page.getByRole("button", { name: "复制回答", exact: true }).waitFor();
  ensure(
    (await page.locator("details.process").getAttribute("open")) === null,
    "process_is_collapsed_by_default",
  );
  ensure(
    (await page.getByText("只有展开后才显示的界面测试过程").isVisible()) ===
      false,
    "collapsed_process_is_hidden",
  );
  await page.locator("details.process summary").click();
  ensure(
    await page.getByText("只有展开后才显示的界面测试过程").isVisible(),
    "user_can_expand_process",
  );
  ensure(
    (await page.getByRole("table").count()) === 1,
    "markdown_tables_render",
  );
  await page.locator(".answer-image img").waitFor();
  ensure(
    await page
      .locator(".answer-image img")
      .evaluate((image) => image.complete && image.naturalWidth > 0),
    "authenticated_image_preview_renders",
  );
  await selectBoard("词元");
  ensure(
    (await page.getByText("界面测试回答。", { exact: true }).count()) === 0,
    "answers_do_not_cross_boards",
  );
  ensure(
    (await input.inputValue()) === "词元草稿",
    "second_board_keeps_its_own_draft",
  );
  await page.getByRole("button", { name: "发送消息", exact: true }).click();
  await page.getByRole("button", { name: "复制回答", exact: true }).waitFor();
  const sent = await page.evaluate(() =>
    window.__fixture.calls.filter(
      (call) => call.op === "chatSend" && call.args.frame.type === "user_turn",
    ),
  );
  ensure(
    sent.length === 2 &&
      sent[0].args.frame.mcp_servers[0] === "aftersales_quality" &&
      sent[1].args.frame.mcp_servers[0] === "aiq_workbench_readonly",
    "each_board_sends_its_selected_connector",
  );
  ensure(
    sent[0].args.frame.session_key !== sent[1].args.frame.session_key &&
      !Object.hasOwn(sent[0].args.frame, "hitl_policy"),
    "unique_sessions_and_no_approval_bypass",
  );
  await selectBoard("知识库");
  await input.fill("这是本轮提供的测试文字，无需检索知识库。请回复收到。");
  await page.getByRole("button", { name: "发送消息", exact: true }).click();
  await page.getByRole("button", { name: "复制回答", exact: true }).waitFor();
  const unboundKnowledge = await page.evaluate(
    () =>
      window.__fixture.calls
        .filter(
          (call) =>
            call.op === "chatSend" && call.args.frame.type === "user_turn",
        )
        .at(-1).args.frame,
  );
  ensure(
    unboundKnowledge.knowledge_base_ids.length === 0 &&
      unboundKnowledge.mcp_servers.length === 0,
    "unbound_knowledge_accepts_current_material_without_attaching_private_resources",
  );
  await page.getByRole("button", { name: "功能与设置", exact: true }).click();
  ensure(
    (await page.getByRole("option", { name: "其他成员专家" }).count()) === 0,
    "foreign_owned_experts_are_not_offered",
  );
  await page.getByRole("checkbox", { name: "测试知识库", exact: true }).check();
  await page.getByRole("button", { name: "关闭设置", exact: true }).click();
  await input.fill("知识库测试");
  await page.getByRole("button", { name: "发送消息", exact: true }).click();
  await page.getByRole("button", { name: "复制回答", exact: true }).waitFor();
  const kb = await page.evaluate(
    () =>
      window.__fixture.calls
        .filter(
          (call) =>
            call.op === "chatSend" && call.args.frame.type === "user_turn",
        )
        .at(-1).args.frame,
  );
  ensure(
    kb.knowledge_base_ids[0] === "kb-test" && kb.mcp_servers.length === 0,
    "knowledge_request_contains_only_selected_KB",
  );
  await page.getByRole("button", { name: "开始语音输入", exact: true }).click();
  await page
    .getByRole("button", { name: "结束语音输入", exact: true })
    .waitFor();
  await page.waitForFunction(() =>
    document.querySelector("textarea").value.includes("语音输入界面测试"),
  );
  ensure(
    (await input.inputValue()).includes("语音输入界面测试"),
    "speech_events_update_draft",
  );
  await page.getByRole("button", { name: "结束语音输入", exact: true }).click();
  await page
    .getByRole("button", { name: "开始语音输入", exact: true })
    .waitFor();
  await page.locator('input[type="file"]').setInputFiles({
    name: "fixture.png",
    mimeType: "image/png",
    buffer: Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a9WQAAAAASUVORK5CYII=",
      "base64",
    ),
  });
  await page.locator(".attachment-strip img").waitFor();
  ensure(
    (await page.locator(".attachment-strip img").count()) === 1,
    "image_upload_is_shown_before_send",
  );
  await selectBoard("售后");
  const oldContext = sent[0].args.contextKey;
  await page.getByRole("button", { name: "功能与设置", exact: true }).click();
  await page.getByRole("button", { name: "新对话", exact: true }).click();
  await page.evaluate(
    (contextKey) =>
      window.__companionEvent({
        type: "chat",
        board: "aftersales",
        contextKey,
        data: { type: "token", content: "STALE_SHOULD_NOT_APPEAR" },
      }),
    oldContext,
  );
  ensure(
    (await page.getByText("STALE_SHOULD_NOT_APPEAR").count()) === 0,
    "late_stream_is_dropped_after_new_chat",
  );
  await input.fill("重开后保留的草稿");
  await page.reload();
  await page
    .locator('textarea[aria-label="输入问题"]:not([disabled])')
    .waitFor();
  ensure(
    (await input.inputValue()) === "重开后保留的草稿",
    "reopening_keeps_unsent_draft",
  );
  await page.evaluate(() => localStorage.setItem("__fixtureUser", "1000"));
  await page.reload();
  await page
    .locator('textarea[aria-label="输入问题"]:not([disabled])')
    .waitFor();
  ensure(
    (await input.inputValue()) === "",
    "another_account_cannot_see_previous_draft",
  );
  await page.emulateMedia({ colorScheme: "light", reducedMotion: "reduce" });
  await page.setViewportSize({ width: 350, height: 510 });
  await checkCompactTitlebar("narrow_titlebar_preserves_traffic_lights_and_settings");
  await page.getByRole("button", { name: "功能与设置", exact: true }).click();
  ensure(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth <= window.innerWidth &&
        document.documentElement.scrollHeight <= window.innerHeight,
    ),
    "minimum_window_has_no_clipped_composer_or_horizontal_overflow",
  );
  await page.screenshot({
    path: "desktop-companion/output/playwright/ui-smoke-light.png",
  });
  await page.emulateMedia({ colorScheme: "dark" });
  await page.setViewportSize({ width: 456, height: 684 });
  await page.screenshot({
    path: "desktop-companion/output/playwright/ui-smoke-dark.png",
  });
  await page.getByRole("button", {name:"关闭设置",exact:true}).click();
  await input.fill("玻璃界面验收");
  await page.getByRole("button", {name:"发送消息",exact:true}).click();
  await page.getByText("界面测试回答。",{exact:true}).waitFor();
  ensure(await page.evaluate(() => getComputedStyle(document.documentElement).backgroundColor === "rgba(0, 0, 0, 0)"),"transparent_web_surface_for_native_glass");
  await page.screenshot({path:"desktop-companion/output/playwright/glass-chat-dark.png"});
  await page.emulateMedia({colorScheme:"light"});
  await page.screenshot({path:"desktop-companion/output/playwright/glass-chat-light.png"});
  await page.evaluate(() => window.__companionEvent({ type: "authExpired" }));
  await page
    .getByRole("button", { name: "使用企业飞书登录", exact: true })
    .waitFor();
  ensure(
    (await input.isDisabled()) && (await input.inputValue()) === "",
    "expired_login_clears_visible_private_state",
  );
  return {
    fixture_only: true,
    real_backend_used: false,
    passed: checks.length,
    checks,
  };
}
