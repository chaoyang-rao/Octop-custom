# Octop 板块反馈通道

成员从侧边栏底部的“问题反馈”打开表单，选择反馈板块、类型并填写标题和详细内容。板块默认对应当前页面，也可手动切换；提交前不会自动发送反馈。

企业版沿用当前成员的企业登录授权，将反馈汇总到企业授权中心。超级管理员打开 `/enterprise/admin?tab=feedback` 的“反馈管理”，按板块、处理状态或标题、正文、提交人姓名检索，打开记录后填写回复并设置“待处理”“处理中”或“已解决”。成员在“我的反馈”中刷新后可查看自己的处理状态和管理员回复。

未连接企业授权中心的独立部署将反馈保存到本机数据库，管理员从反馈窗口进入 `/admin/feedback` 管理。企业客户端不会在中心不可用时悄悄改存到本机；界面会保留填写内容并显示重试提示。

## 数据与权限

反馈只包含主动填写的板块、类型、标题和内容，以及客户端版本、平台类型；提交人由服务端根据登录身份记录。不会自动采集聊天内容、项目路径、截图、日志或个人密钥。反馈内容应避免填写密码和令牌。

成员只可查看自己的记录；管理接口仅允许授权中心的管理员访问。客户端即使登录的是管理员，设备身份凭据也不能获取整个企业的反馈或修改处理状态。网络重试使用同一个提交标识，避免重复记录；管理员并发编辑使用修订号，冲突时保留输入并提示刷新。

数据库新增 `030_feedback.sql` 与对应 PostgreSQL 迁移，仅增加反馈表和索引，既有账号、会话及连接器配置保留。反馈记录按创建时间倒序分页读取。

## 接入与验证

前端源码位于 `dashboard/src/components/feedback/` 与 `dashboard/src/pages/Feedback/`。HTTP 适配器位于 `src/octop/api/routers/feedback.py`，业务逻辑和 SQL 分别归属 `infra/feedback/` 与 `infra/db/repos/feedback.py`。

提交、个人查询和管理分别使用 `/api/feedback`、`/api/feedback/mine`、`/api/feedback/admin`；企业中心使用对应的 `/api/enterprise/feedback` 前缀。启用 API 文档的部署可在 `/api/docs` 查看请求和响应模型；当前企业服务继续保留关闭 API 文档的原设置。

专项验证命令：

```bash
uv run pytest tests/unit/feedback tests/unit/db/test_db_pool.py tests/unit/i18n -q --no-testmon
cd dashboard
npx tsc -b
npx vitest run src/components/feedback/FeedbackLauncher.test.tsx src/pages/Feedback/FeedbackAdmin.test.tsx src/pages/Login/EnterpriseAdmin.test.tsx src/layouts/Sidebar.chatRailToggle.test.tsx
```

侧边栏入口属于客户端界面更新。已安装旧界面的同事需要更新到包含本功能的客户端；企业 MCP、专家和技能目录同步不会替换程序界面。
