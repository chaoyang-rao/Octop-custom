# 通知封装协议 v1

仅用于通知内容。设备凭据仍只保存 SHA256 校验值；消息密钥是 `HKDF-SHA256(SHA256(credential), salt="octop-mobile-notifications-salt-v1", info="octop/mobile/notification-content/v1", length=32)`，不能作为登录凭据使用。

AES-256-GCM 每条消息独立生成 12 字节随机 nonce。`sealed` 为 URL-safe Base64 的 `nonce || ciphertext || tag16`。关联数据依次取 `seal_version, host_fingerprint, device_id, agent_id, thread_id, issued_at, expires_at, message_id`，每段为大端 uint32 字节长度加 UTF-8 字节，不拼接含糊的分隔符。

时间戳为 UTC epoch 秒字符串；有效期最多五分钟，未来时钟容差一分钟。客户端核对自己保存的 host/device，认证关联数据，拒绝过期/未来消息，并缓存已见 message id；跳转元数据同时在密文内核对。解封或缓存失败只留下通用提示，不显示预览或跳转数据。iOS 共享 Keychain 只保存用途隔离后的消息密钥，NSE 使用本地文件锁保护持久重放缓存；Android 密钥从 Keystore 保护的设备凭据导出。

`notification-vector.json` 和 `.properties` 是完全虚构、不可登录的固定输入。向量包含 Unicode 以验证三端的 UTF-8 与关联数据编码。随机 nonce 被固定仅用于该向量，运行时从密码学随机源生成。

Swift 独立协议验证，不启动 App 或模拟器：

```sh
xcrun swiftc -parse-as-library clients/mobile/ios/Sources/OctopMobile/NotificationEnvelope.swift \
  clients/mobile/protocol/verify-swift.swift -o /tmp/octop-notification-protocol
/tmp/octop-notification-protocol clients/mobile/protocol/notification-vector.json
```

Android：`gradle :app:testDebugUnitTest`，使用 Google Tink 的标准 HKDF 与 JCA AES/GCM；Python：`uv run pytest tests/unit/mobile_access -q`。

这些验证证明协议和失败分支一致，不代表已在真机、APNS 或 FCM 完成实际投递。
