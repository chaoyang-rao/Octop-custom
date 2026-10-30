# Slack 通道

Octop 使用 Slack 官方 Socket Mode 和 Web API；无需配置公网入站地址，也不依赖其他产品的中转后台。代码位于 `infra/gateway/channels/slack.py`，注册后沿用 Octop 的通道归属、会话、历史和专家处理链。

## 创建与连接

1. 在 [Slack 应用管理](https://api.slack.com/apps) 创建自己的应用，开启 Socket Mode，生成含 `connections:write` 的 App Token（`xapp-`）。
2. 为 Bot 添加 `chat:write`、`app_mentions:read`、`im:history`。需要接收与发送附件时增加 `files:read`、`files:write`。订阅 `app_mention` 与 `message.im`，然后安装到自己的工作区。
3. 在专家的通道设置中选择 Slack，填写 Bot Token（`xoxb-`）和 App Token，填入允许的频道 ID、允许私信的用户 ID。把机器人加入需要使用的频道，保存并测试。

默认不接收任何私信；只有名单中的用户可以私信。默认只接受名单频道中的 @提及；“允许所有频道”仍只覆盖机器人已加入且被 @提及的频道。每个频道话题使用独立会话，同一话题的不同成员共用该话题上下文；与其他话题、私信、专家注册实例隔离。

## 消息及附件

事件收到后立即确认，过滤其他工作区、机器人消息和消息编辑事件，重复投递不会重复触发。回复发送到原话题，不自动展开链接、不触发文本中的 `@channel` 等通知。附件仅从 Slack HTTPS 域名下载，凭据不会随重定向发送到其他站点。单附件限制 25 MB；上传使用 Slack 当前的分步外部上传接口。

服务端状态会显示连接是否断开；网络中断后自动重连。网络错误采用固定诊断码，避免把带票据的 WebSocket URL 写入错误输出。

## 验证范围

本地测试覆盖接收确认、重复投递、工作区和名单过滤、话题隔离、回复路由、附件域名限制、凭据错误脱敏以及真实 ChannelManager 注册。真实 Slack 工作区的授权、消息和附件收发仍需上述应用令牌，未配置令牌时不记为端到端验收通过。

接口依据：[Socket Mode](https://docs.slack.dev/apis/events-api/using-socket-mode/)、[发送消息](https://docs.slack.dev/reference/methods/chat.postMessage/)、[申请上传地址](https://docs.slack.dev/reference/methods/files.getUploadURLExternal/)、[完成上传](https://docs.slack.dev/reference/methods/files.completeUploadExternal/)。
