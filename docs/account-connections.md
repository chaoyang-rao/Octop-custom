# 账号连接、密码库与自有 OAuth 应用

账号连接设置提供 1Password、Bitwarden 和自有 OAuth 应用。配置仅属于当前登录账号；专家工具还会逐次验证服务端注入的真实调用者、账号状态和连接器权限。共享专家、管理员代看会话、群聊或外部 IM 的会话归属不能自动获得库主人的权限。

## 密码库

1Password 使用官方 `op` CLI 和用户自行创建的服务账号。配置令牌加密存储，CLI 缓存和桌面生物识别自动解锁被关闭，每个连接使用独立配置目录。请在服务商侧仅向服务账号开放必要的库。

Bitwarden 使用官方 `bw` CLI，每个账号、每个连接使用独立的 `BITWARDENCLI_APPDATA_DIR`，不会读取系统默认个人 CLI profile。创建连接后，界面显示该隔离目录；用户需在自己的终端以此目录登录、解锁，并将产生的 `BW_SESSION` 填入解锁会话输入框。该值只在服务端内存保留一小时，进程重启、主动忘记或断开后失效；不保存主密码，不替用户登录或解锁。独立 profile 中服务商自己的加密数据不随断开而删除。

“凭据已配置”表示服务账号或解锁会话存在，不代表服务商已验证。点击条目读取可检验权限；界面和专家工具只接收条目 ID、标题和库 ID，不返回字段值、笔记或密码。Bitwarden CLI 列表原始结果仅在服务端内存中投影为上述元数据。

创建引用只保存连接、条目、库和字段定位，不读取密钥。1Password 需要条目与库的 ID 和字段名；Bitwarden 允许 `password`、`username`、`totp` 字段。引用格式为不可猜测的 `vaultref_…`，访问仍须通过账号验证。

## 逐次批准使用

连接的投递主机名单默认为空，禁止投递。用户可填写确切公共主机名；不接受通配符。专家或用户可申请将引用注入一个精确 HTTPS 请求的 `Authorization`、`X-API-Key` 或 `Api-Key` 请求头，填写方法、完整 URL、非敏感请求体和用途。

审批界面显示完整操作，需用户手动点击“批准本次请求”。申请有效期十分钟，审批令牌不进入专家工具输出。服务端在读取密钥或发网络请求之前持久标记已消费；失败、重试、并发审批和进程重启不能自动重复请求。拒绝、过期、其他账号和被撤销的连接均不能使用。

目标在申请和执行时都必须匹配连接的主机名单，使用公共 HTTPS、固定 443 端口，并经过 DNS 地址验证和连接 IP 固定。不会跟随重定向。只有 HTTP 状态返回给界面和工具；响应正文、Location、响应头和原始异常均不会读取或返回，避免回显服务泄漏密码。当前投递能力用于指定 HTTPS 请求，不开放任意 shell 命令或将密码值交给模型。

## 自有 OAuth 应用

Slack 账号 MCP 等服务不提供动态注册。用户可按服务商文档创建自己的应用，在账号连接中登记 Client ID、Client Secret、权限范围，并将界面所示 Octop OAuth 回调地址配置到服务商。Secret 和待回调 OAuth 上下文加密保存，读取只返回“是否已配置”。同账号修改 Client ID 时，未重新填写的 Secret 不会从旧应用继承。

授权仍走资源端发现、PKCE、状态验证、令牌交换和刷新。没有自有应用时，不会冒用其他产品的客户端。Slack 需内部应用或市场应用并满足工作区批准；Canva、Vercel 等服务也可能要求应用注册或批准。登记配置不能替代服务商授权或真实工具发现。

## 实现与验收边界

领域逻辑位于 `src/octop/infra/connectors/accounts/`；人工接口位于 `src/octop/api/routers/account_connections.py`；前端在 `dashboard/src/pages/AccountConnections/`。`accounts.tools.build_account_tools` 只暴露元数据、引用创建、使用申请与状态，没有读取密钥或批准申请工具。真实 ingress 通过 `accounts.actor.actor_stream` 注入身份；显式未认证身份优先于检查点中的旧字段。

隔离和单次消费使用临时仓库、模拟 CLI/HTTPS 和真实 LangChain 工具调用验证。没有读取或解锁本机密码库，也没有配置真实服务账号或对外投递密钥。真实账号授权、桌面 CLI 安装和服务商权限由用户配置后验收。

接口依据：[1Password 服务账号](https://www.1password.dev/service-accounts/use-with-1password-cli)、[CLI 环境变量](https://www.1password.dev/cli/environment-variables)、[Bitwarden CLI](https://bitwarden.com/help/cli/)、[Slack MCP](https://docs.slack.dev/ai/slack-mcp-server/)。
