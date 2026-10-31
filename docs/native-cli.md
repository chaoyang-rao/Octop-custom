# 原生 CLI 专家执行

专家可在 API 模型和本机已授权的 ACP CLI 之间选择执行方式。原生 CLI 是 Octop 的模型引擎：会话历史、LangGraph、团队主专家、Octop 工具权限和人工审批仍走原有流程，不是把整个会话转给 `acp_runner` 工具。

## 配置与日常使用

管理员在「原生 CLI」页面选择自己的私有专家，启用已配置的 runner，保存后使用。它沿用官方 CLI 自己的登录状态，不读取、复制或更改登录令牌，也不修改宿主 `HOME` / `CODEX_HOME`。由于主机 CLI 登录通常属于主机用户，普通 Octop 用户不能自行启用此方式，管理员也不能借此调用其他用户的私有专家。

「检测能力」只启动协议会话读取 CLI 实际公布的模型、模式与媒体能力，不发送模型 prompt，不注册 Octop 工具，不批准启动过程中的权限请求。模型/权限模式填写不受支持的值时，运行会明确失败。

聊天输入区的原生模型选择只影响当前会话。选择先保留在草稿中，发送下一条消息时校验并保存；新会话首次发送也支持。已运行或等待审批的回合持有自己的模型快照，不会因为用户为下一条消息选了另一个模型而切换。其他会话、runner、权限模式和专家默认配置保持独立。

每个原生会话按用户、实际执行专家、会话和项目目录隔离。团队使用主专家执行，并仍记录实际回答成员。CLI 支持官方 `loadSession` 时可恢复原生会话；否则有界地从该 Octop 会话历史重建。启动时发现上次执行停在工作/审批状态会要求显式重置，避免自动重放动作。重置关闭对应 CLI 和待处理请求，保留聊天历史与项目绑定。

## 工具和权限边界

CLI 使用 Octop 工具时，经过只绑定 `127.0.0.1`、随机单会话密钥的 MCP 桥。桥只排队工具调用，交给原来的 Graph ToolNode 和人工审批执行。ACP 的 `request_permission` 同样显示为人工审批，只会返回 `allow_once` 或拒绝，不自动授予永久权限，拒绝不会记为成功。

CLI 自身内置文件/命令工具仍受其供应商权限模式和已有操作系统沙箱约束。不能把提示词当成沙箱，也不宣称所有内置操作都被 Octop 工具审批拦截。Octop 的 `ask` / `plan` 回合要求 CLI 真实公布并接受 `read-only` 模式；不支持就失败，不会悄悄降低限制。

Native 执行主体与密码库登录者分别校验。服务端确认的通道 owner、计划任务 owner 可以执行其已授权的私有 CLI 专家；匿名 IM 和后台任务不能沿用历史 checkpoint 中的登录身份访问密码库。已登录用户的真实身份与执行 owner 不同也会拒绝。

## 图像、附件和统计

上传图片、音频和文件通过既有工作区媒体适配器读取，转换成标准 ACP `image`、`audio`、`resource` 内容。单件上限 12 MiB，编码后总量上限 24 MiB。未公布所需能力、文件不可读或超限会明确报错。不会为了原生 CLI 擅自下载外部图片 URL。

Octop 工具返回的图片保持 MCP image 内容，不转换为 base64 JSON 文本。模型标签显示 runner 和真实/配置模型；未知模型显示「CLI 默认模型」。CLI 未上报统计时保留 unknown，不伪造 API token 数、费用或上下文窗口。ACP 上报的上下文 used/size 只作为 CLI 上下文统计，不作为 API 每回合输入/输出用量。

## 受管安装范围

当前审核目录包含 Codex ACP、OpenCode、Pi、Claude Agent ACP、Cline、Grok、Gemini CLI 和 Cursor。各版本、官方来源、许可、Node/依赖处理及平台支持见 [受管发行源说明](managed-cli-sources.md)。未覆盖的平台在页面明确显示不支持。

管理员可显式安装、激活、更新或回退已审核版本。下载只进入 `OCTOP_HOME/managed-cli/<user>/…`，核对固定发行、依赖锁、SHA256/SHA512 SRI 和许可证哈希；拒绝路径穿越、外部链接、特殊文件和超限解压。不启动供应商 CLI 或包安装脚本；Grok 只用已校验的私有 Node 内置解码器转换压缩二进制。

激活只更新专用 `managed_*` runner，校验完整文件树，不覆盖已有全局 CLI、Node、登录或手工修改的 runner。正在运行或待审批的专家会阻止切换。Pi 当前社区适配器的 MCP 边界与 Muse 外部托管依赖不能标为已经完成集成，详见发行源说明。

## HTTP 契约

| 路径 | 行为 |
| --- | --- |
| `GET /api/agents/{id}/native-cli` | 查看自己专家的配置、能力缓存和原生会话 |
| `PUT /api/agents/{id}/native-cli` | 管理员切换执行引擎或全专家默认配置，忙碌时拒绝 |
| `POST /api/agents/{id}/native-cli/probe` | 管理员显式读取 runner 公布的能力，不发送模型 prompt |
| `GET /api/agents/{id}/native-cli/models?thread_id=…` | chat 权限读取当前会话可用模型；可省略 thread 用于首次发送 |
| `DELETE /api/agents/{id}/native-cli/sessions/{thread}` | 显式关闭对应原生会话 |
| `GET /api/native-cli/managed` | 受管目录与安装/激活状态 |
| `POST /api/native-cli/managed/{package}/install` | 校验并安装固定目录版本 |
| `POST /api/native-cli/managed/{package}/activate` | 激活已安装版本 |
| `POST /api/native-cli/managed/{package}/rollback` | 回退到上次已激活版本 |

聊天 WS/HTTP 的 `native_model_id` 是独立于 API `model/default_model` 的字段：未传或 `null` 沿用会话选择，空串使用 CLI 默认模型，非空必须是该 CLI 实际公布的模型 ID。服务端准备消息后产生本回合快照，客户端不能通过该字段更换 runner 或权限模式。

## 验证边界

`tests/unit/agents/native_cli/` 使用真实本机 fake ACP 子进程、loopback MCP、LangGraph、ToolNode 和 HITL 验证协议、审批、取消、加载恢复、模型快照和媒体；受管安装使用合成归档验证完整性、更新/回退和 busy/drift 边界。不发送付费模型请求，不安装真实 CLI，不改用户全局配置。因此这些测试不代表用户真实 CLI 账号已经登录，或各供应商版本已完成实机兼容验收。
