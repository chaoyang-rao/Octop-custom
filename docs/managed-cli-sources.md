# 受管 CLI 发行源与验证边界

核验日期：2026-10-31。版本与完整性值固定在 `native_cli/managed_catalog.json`，依赖闭包固定在 `managed_locks/`。页面显示的是最新**已审核**版本，不把目录版本冒充供应商实时最新版。

| CLI | 已审核版本 | 官方来源和许可 | 平台 |
| --- | --- | --- | --- |
| Codex ACP | 0.15.0 / 0.16.0 | [Zed Codex ACP releases](https://github.com/zed-industries/codex-acp/releases)，Apache-2.0 | macOS ARM64/x64、Windows ARM64/x64、Linux GNU/musl ARM64/x64 |
| OpenCode | 1.19.4 / 1.19.5 | [官方 releases](https://github.com/anomalyco/opencode/releases)，MIT | 同上；x64 选 baseline 包，避免假定 CPU 支持 AVX2 |
| Pi | 1.3.0 / 1.4.0 | [Pi 官方 releases](https://github.com/earendil-works/pi/releases)，MIT | macOS/Windows/Linux ARM64/x64；当前不提供受管 musl 包 |
| Claude Agent ACP | 0.99.0 / 0.99.1 | [ACP 维护方发行](https://github.com/agentclientprotocol/claude-agent-acp/releases)，Apache-2.0 适配器；官方 Claude Agent SDK 0.3.312 适用 Anthropic 商业条款 | macOS/Windows/Linux ARM64/x64 |
| Cline | 3.0.73 / 3.0.74 | [官方 Cline npm](https://www.npmjs.com/package/cline) 对应 `@cline/cli-*` 平台包，Apache-2.0 | macOS/Windows/Linux ARM64/x64 |
| Grok | 1.0.69 / 1.0.70 | [xAI 官方 npm](https://www.npmjs.com/package/@xai-official/grok) 对应 `@xai-official/grok-*` 平台包，Apache-2.0 | macOS/Windows/Linux ARM64/x64 |
| Gemini CLI | 0.65.0 / 0.66.0 | [Google 官方 npm](https://www.npmjs.com/package/@google/gemini-cli)，Apache-2.0 | macOS/Windows/Linux ARM64/x64 |
| Cursor | 2026.10.22-27dcf5f | [Cursor 官方安装说明](https://cursor.com/docs/cli/overview) 的固定 `downloads.cursor.com/lab/…` 发行，适用 [Cursor 条款](https://cursor.com/terms-of-service) | macOS/Windows/Linux ARM64/x64 |

这些安装目录、状态和专用 runner 均按 Octop 用户隔离。用户原来的全局 CLI、Node、npm、PATH、配置和登录文件不被覆盖。普通用户不能借受管页面获得主机 CLI 的管理权限。

## 校验与安装方式

- GitHub 发行包使用官方 Release API 的 SHA256 digest 和精确字节数。npm 包使用官方 registry 的 SHA512 SRI、固定 tarball URL 和精确字节数；完整依赖闭包不在用户安装时重新求解。npm 来源的许可证文件和第三方声明随包保留。
- Cursor 的六个平台包曾从固定官方 URL 下载到临时审查目录计算 SHA256，并检查包内入口与文件布局；压缩包随后删除，未提取或执行其中的 CLI。这里的 SHA256 是本项目的审查值，不能称为厂商公布的签名或校验清单。HEAD 返回 403，但正常 GET 可读，因此不能把 HEAD 结果误报为没有可用发行源。
- 私有 [Node.js 24.22.2](https://nodejs.org/dist/v24.22.2/SHASUMS256.txt) 使用官方 SHA256 清单、固定平台 URL、精确长度和许可证哈希。依赖闭包只通过 Python 安全解压到私有目录，不调用 npm、不执行 install/postinstall、也不读取用户 npm 配置。Node 归档中的内部 npm 链接只在目标确认位于归档内部时跳过；不创建链接，外部链接仍拒绝。
- Grok 平台包包含 Brotli 压缩的原生程序。安装时只用已校验的私有 Node 执行 Octop 自己的固定内置流式解码代码，限制输出 512 MiB、耗时 120 秒，清除 NODE_OPTIONS 等用户注入路径。不启动 Grok 或供应商安装脚本。解码后直接运行原生程序，并使用 [官方 `--no-auto-update` 选项](https://docs.x.ai/build/cli/headless-scripting)。
- Cursor 发行自带 Node。Windows 直接使用该 `node.exe` 和固定 JS 入口，避免 cmd/PowerShell 包装层。使用 [官方 `CURSOR_CONFIG_DIR`](https://cursor.com/docs/cli/reference/configuration) 指向本账号独立 profile，固定 `channel: static`；不复制宿主 profile/令牌。独立 profile 可能需要用户按官方流程另行登录。
- 激活、升级或回退前校验完整文件树，包括解释器、入口、依赖和解码产物。忙碌或待审批时拒绝切换；检测到用户改了 runner、环境或受管文件时拒绝覆盖。目录升级不恢复旧的聊天数据库、项目文件或登录状态。

## 外部依赖与已知限制

Pi 官方目前提供 RPC/SDK；已有 `pi-acp` 社区适配器的 [公开说明](https://github.com/svkozak/pi-acp) 明确表示其未把 MCP server 接入 Pi。该限制不能被一个成功安装状态掩盖；Octop 的独立 Pi 工具桥需要单独验证 Graph/审批链路后才能标为完整工具集成。

Muse 是 OpenBot 自有托管服务。没有可直接分发的独立 CLI 发行源；本目录不使用 OpenBot 的私有下载源、锁文件、账号或后台。接入需要其服务方提供公开或正式授权的接口和服务账号，不能用一个虚构的安装条目代替。

供应商登录、套餐、地域、Git Bash/系统库等运行前提仍由各官方 CLI 决定。包下载、版本校验和 fake 协议测试不等于这些真实账号已登录或每个供应商版本都经过实机付费调用验收。本轮未安装真实 CLI、读取登录令牌或发送付费模型请求。

## 以后审核新版本

先读取供应商官方发行与许可，再固定新 URL、字节数和 SHA256/SRI。Node 和依赖变化必须一同审查，保留旧版 pin 以支持回退。不能把 `latest`、动态 npx、curl 安装脚本或每次安装时的未锁定依赖解析放进受管目录。

依赖锁生成只允许 `npm --package-lock-only --ignore-scripts`，使用临时空 npm user/global 配置和临时缓存；不会生成 `node_modules`。确认锁中的每项均为固定 registry URL、强完整性值及许可后再纳入代码。发布前运行受管组件测试和对应平台 CI；不自动推送或覆盖用户自己的安装。
