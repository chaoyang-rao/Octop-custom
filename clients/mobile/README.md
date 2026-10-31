# Octop 移动客户端与远程访问

这是独立编写的 iOS / Android 客户端与设备授权层，连接自己的 Octop。客户端复用当前 Octop 的真实响应式工作区，因此专家、团队、项目会话、头像、消息、审批、附件和已授权的任务/控制界面沿用同一套服务及权限；没有伪造登录、聊天或工具结果。这里没有引入 OpenBot 的实现代码、图标或技能内容，也不连接其账号、中转、收费托管后台。

## 先连接自己的服务器

桌面打开「移动与远程访问」。可配置公开 HTTPS 地址并检查连接，检查只有在 DNS、可信证书、移动接口与**本机身份指纹**均通过时显示就绪。返回其他 Octop 或错误反向代理目标时会明确显示身份不匹配。该检查是在当前服务器上执行，手机侧仍需实际确认其网络可达；它不能证明手机蜂窝网络或 VPN 已配置。

### 当前 Mac / 自建服务器，不迁移数据

如果继续使用当前已安装的 Octop，保留它的数据库与文件位置，仅在同一机器运行 HTTPS 反向代理：

1. 准备自己的域名和可达该机器的网络。公开访问需要 DNS 指向可访问地址，以及路由器/防火墙转发 TCP 80、443；没有入站网络时可使用下面的私有 Tailscale 方案。
2. 安装 [Caddy](https://caddyserver.com/docs/install)，复制 [本机 Caddy 示例](deploy/Caddyfile.local.example)，把 `octop.example.com` 改成真实域名，确认反向代理目标是当前 Octop 的端口。
3. 在配置文件所在目录执行 `caddy validate --config Caddyfile`，再执行 `caddy run --config Caddyfile`。示例转发到 `127.0.0.1:8088`，不会改变 Octop 的数据库、专家、会话、工作区或监听地址。Caddy 与 Octop 在同一主机时，Octop 的默认 loopback 代理信任可识别 HTTPS 转发头。
4. 在「移动与远程访问」保存 `https://你的域名`，点击「检查连接」。也可复用现有「高级设置 → HTTPS」的证书及端口诊断入口；已有生产 HTTPS 不需要再安装代理。
5. 用手机打开该 HTTPS 地址，确认浏览器没有证书提示，再按下面的配对流程操作。

不使用 `verify=False` 或忽略证书错误来制造通过。局域网自签证书需要设备按自己的管理方式建立信任；默认客户端仅信任系统证书。HTTP 只允许同机 loopback 开发，不作为跨设备远程连接方案。

### 私有 Tailscale 网络

本机和手机都需安装并登录自己的 Tailscale 网络，网络管理员需允许 HTTPS / Serve，以及手机到该设备的访问。

在页面点击「检查本机登录状态」；已登录后可点击「启用 Octop 私有 HTTPS」。后端使用官方 `tailscale serve --bg --https=443 http://127.0.0.1:<Octop端口>`，保存返回的 `*.ts.net` 地址，再点击连接检查。它**不启用公网 Funnel**。

已有其他 Serve 配置时会拒绝覆盖。停用时只有在完整配置仍是 Octop 自己建立且没有其他路径/端口时才移除；外部工具改动后需要人工核对。这里只操作已安装并登录的客户端，不自动安装、不代替登录或授予 VPN 权限。私有链接只对该网络及 ACL 允许的设备可用。

官方说明：[Serve 命令](https://tailscale.com/docs/reference/tailscale-cli/serve)、[HTTPS](https://tailscale.com/kb/1153/enabling-https)。

### 全新 Docker 自建服务

[部署目录](deploy/) 提供独立构建、Compose 和 Caddy 配置。它构建**当前仓库锁定依赖与完整定制快照**，不会拉取官方 Octop latest 覆盖定制。它创建独立新数据卷，不会挂载或迁移本机 `~/.octop`；现有专家/工作区不能简单把 Mac 的绝对路径数据库复制进 Linux。

在仓库根目录：

```sh
cp clients/mobile/deploy/.env.example clients/mobile/deploy/.env
# 在 .env 把 OCTOP_DOMAIN 改成你的真实域名，再执行：
docker compose --env-file clients/mobile/deploy/.env -f clients/mobile/deploy/compose.yml config
docker compose --env-file clients/mobile/deploy/.env -f clients/mobile/deploy/compose.yml up -d --build
```

Caddy 独占公开端口，Octop 的 8088 仅在两个容器的专用网络中暴露。示例 `FORWARDED_ALLOW_IPS=*` 只适用于这个未直接开放 API 的独立网络；若自行开放 8088 或加入其他代理，应改成明确的可信代理地址。

第一次访问 HTTPS 页面完成 Octop 的既有设置向导；如需向导口令，在自己的终端读取：

```sh
docker compose --env-file clients/mobile/deploy/.env -f clients/mobile/deploy/compose.yml exec octop cat /data/octop/octop-login.txt
```

不要把口令或数据卷上传到 Git。`down` 保留数据；不要用 `down -v` 移除已有数据卷。此环境尚未替你部署，域名、网络入口、证书签发和真实手机连通性需要在自己的环境验证。

## 设备配对与撤销

1. 在手机原生客户端输入实际 HTTPS 地址并点击生成配对码。
2. 在已登录的电脑端输入手机显示的短码，核对设备名称、系统和服务器指纹。
3. 勾选能力并批准。默认是专家/团队聊天、文件、通知和有权限的任务；浏览器、桌面、终端、远程手机控制和专家管理分别授权。模型、连接器和全局配置不会默认下放。
4. 手机会获得独立设备凭据。服务器只持久存 SHA256；配对结果临时加密保存以支持网络重试，过期和撤销后不能复活。客户端凭据保存在 iOS Keychain 或 Android Keystore 加密存储中，不放入网页导航链接。
5. 电脑设备列表可单独撤销；之后的授权请求立即拒绝，空闲 WebSocket 至多十秒关闭，正在输出的连接会更快检查。撤销不删除聊天，不中断已经由服务端接受的专家任务。

服务端作用域检查同时覆盖 HTTP、URL 凭据的 WebSocket，以及在首帧才提交凭据的控制流。设备不会继承管理员身份；账号权限被收回时设备也不能保留该权限。重新连接读取权威会话状态，不自动重发聊天消息。

## iOS 构建

在 macOS 安装完整 Xcode，打开 [OctopMobile.xcodeproj](ios/OctopMobile.xcodeproj)。工程包含四个 target：SwiftUI App、WidgetKit Live Activity、通知解密 NSE 和系统分享 Share Extension，不需要外部 iOS 代码库。

无签名编译（不启动模拟器、不安装）：

```sh
xcodebuild -project clients/mobile/ios/OctopMobile.xcodeproj -scheme OctopMobile \
  -configuration Debug -sdk iphonesimulator -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath /tmp/octop-mobile-derived -jobs 1 \
  CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO build
```

当前代码已完成四个 target 的无签名 Simulator SDK 编译。真机、TestFlight 或 App Store 分发需要自己的 Apple Developer Team、App 与扩展 Bundle ID、描述文件与签名；尚未发布或安装到真机。

客户端使用同源非持久 WKWebView，会话令牌注入当前来源的 sessionStorage，原生消息桥只接受可信主框架消息；每个服务器独立保存当前进程内的网页状态。网页附件保留真实系统文件选择和分享流程。通知、录音、拍照均由用户自己的操作及系统权限决定，本次实现过程没有启动设备权限。

## Android 构建

工程使用 JDK 17、Gradle 8.13、Android SDK 36。安装环境后在 [android](android/) 目录运行：

```sh
gradle --no-daemon --max-workers=1 :app:assembleDebug :app:testDebugUnitTest
```

产物为 `android/app/build/outputs/apk/debug/app-debug.apk`。本机没有 Gradle / Android SDK，Android 编译交由独立 CI 验证；未安装或签名发布 APK。App 支持 Android 8+，需要支持文档起始脚本、来源限定消息桥和 MULTI_PROFILE 的较新 Android System WebView。服务器/账号使用独立 WebView profile，撤销时只移除对应 profile。

Android 的原生桥限定已配对来源和主框架，不使用向所有 iframe 开放的 `JavascriptInterface`。附件选择使用系统文件选择器，另存使用系统文档选择器；移动下载上限 10 MB。Keystore 密文和设备元数据不允许系统备份。语音权限仅在用户主动发起录音时询问。

## 后台通知与实时活动

前台状态沿用现有 WebSocket；iOS 的通知连接支持 Authorization 请求头，避免把长期设备凭据写入该连接的 URL。

后台通知需要自己的资源，在电脑端本页面配置：

- **APNS**：Apple Team ID、Key ID、App Bundle ID 与 p8 签名私钥，选择开发/生产环境；App 必须有对应的推送签名能力。
- **FCM**：Firebase 项目 ID、服务账号邮箱、服务账号签名私钥；Android 构建时在 `app/google-services.json` 放入自己的应用配置。该文件和私钥都已从 Git 排除。
- **Live Activity**：用户开启实时活动，手机前台启动对应工作状态后登记独立加密推送 token；服务端可以在后台更新或结束该活动。该路径由手机前台创建活动，再由服务器在后台维护。

服务端使用 APNS HTTP/2 / FCM HTTP v1 官方接口。默认只显示通用活动提示；每台设备可以选择全部、仅需要我、关闭，按专家静音、定时或永久静音，以及声音。前台和其他设备最近 30 秒活动会抑制通知；开始/恢复事件仅更新 Live Activity，不弹普通横幅。所有已配对且有通知能力的服务器分别登记手机 token，供应商确认失效的旧 token 会移除，更新后的 token 不受旧失败响应影响。

预览默认关闭，只有明确选择后才生成简短的脱敏摘要，不含工具参数和思考内容；检测到凭据、代码或链接时保留通用提示。供应商只接收通用提示、路由身份/时间元数据及 AES-GCM 密文，iOS NSE 或 Android 客户端本地解密内容和会话定位。消息密钥由设备凭据经 SHA256 + 独立 HKDF 用途派生，不能作为登录凭据；AAD 绑定服务器、设备、会话、专家、版本、消息 ID 和有效期。过期、跨设备、篡改、重放时不显示摘要。详细协议和跨语言黄金向量见 [protocol](protocol/)。

Apple 签名需要自己的 Team、四个 Bundle ID、推送能力与描述文件。App/NSE 仅共享通知消息密钥 Keychain group；App/Share 使用另一独立 Keychain group 共享受限分享凭据，另需自有 App Group（工程变量 `OCTOP_SHARE_GROUP`）。NSE 和 Widget 不获得登录凭据或分享凭据。供应商配置和设备推送 token 加密保存；失败不会阻塞专家回复或打印凭据。没有账号资源时显示未配置，不报告后台投递已验证。

技术接口依据：[APNS](https://developer.apple.com/documentation/usernotifications/establishing-a-token-based-connection-to-apns)、[ActivityKit](https://developer.apple.com/documentation/activitykit/displaying-live-data-with-live-activities)、[FCM HTTP v1](https://firebase.google.com/docs/cloud-messaging/send/v1-api)、[Android 来源限定消息桥](https://developer.android.com/reference/androidx/webkit/WebViewCompat)、[Caddy 自动 HTTPS](https://caddyserver.com/docs/automatic-https)。


## 系统分享与本地草稿

iOS 系统分享扩展和 Android ACTION_SEND / ACTION_SEND_MULTIPLE 接收用户选定的文本、链接、图片及文件。原生入口限制 10 个文件、合计 10 MB；先选择已配对服务器和自己的专家，再明确点击「发送后台任务」。选择、预览、保存或关闭时不会调用模型。服务器给分享扩展独立的受限兄弟凭据，继承当前设备到期/撤销，仅允许读取账号和专家标签、上传附件、创建一次性任务；不能管理工作流、计划、控制工具或配置。

发送使用真正的 TaskManager，新建独立任务会话，不重置主聊天。上传响应的 `upload_receipt` 随附件提交，服务端绑定实际上传字节、账号、专家、路径和 SHA256，排队和执行再核对。账号或设备没有 tasks 能力时只能保存加密草稿，不绕过权限调用其他模型入口。iOS 使用共享容器的随机 AES-GCM 密钥，Android 使用独立 Keystore 密钥；当前聊天保持在原界面，草稿可从原生菜单/服务器列表打开。任务创建结果不明时保留未知状态，用户先查任务列表，客户端不自动重发。

## Live Activity 操作确认

活动展示实际专家名称与工作、等待审批、暂停、失败或完成状态。后台任务活动可「查看取消操作」：链接只是服务器签名的只读导航，App 仅接受已配对服务器指纹与设备 ID，不接受任意主机地址或命令。打开后用当前设备令牌 POST 拉取真实任务标题和执行批次；用户明确确认才 POST 执行。执行票据有效 120 秒、只存哈希、仅同一设备使用一次，并绑定任务 attempt 和操作摘要；服务端在 TaskManager 锁内核对 attempt，旧通知不能取消新重试。GET/链接预取不产生任务动作，响应不明时不自动重试。

审批活动仅打开真实会话的待批卡，由用户查看实际操作再决定；没有在锁屏通用提示上盲目批准。普通聊天活动当前只导航，不提供缺少 task attempt 的历史取消按钮。

原生界面使用完整 zh/en 资源，默认跟随账号 `/api/auth/me.locale`（配对前跟系统），也可在原生设置选中文或 English。静音日期使用 `/api/settings/timezone` 返回的服务器时区，不使用手机本地时区，也没有新增 config.json.language。

## 当前验收边界

隔离测试覆盖配对/重试、密钥不明文落库、跨账号隔离、服务端撤销、HTTP 与首帧 WebSocket 作用域、可信传输、推送内容隐私、Live Activity token 和主题、远程身份检测、Tailscale 配置保护。没有通过测试发送真实聊天、交易或推送。

iOS 四 target 无签名编译已经通过，132 个原生资源键与安装图标已检查，Python/Swift 加密黄金向量已通过；Android 构建与 JUnit 黄金向量交由独立 CI。真实 UI、分享扩展/App Group 权限、手机网络、APNS/FCM 投递和签名分发仍需要自己的资源验收。Docker/Caddy 和 Tailscale 入口有可执行配置与操作接口，本次没有对本机开放公网端口、安装网络软件、替用户登录或启动真实网络映射。
