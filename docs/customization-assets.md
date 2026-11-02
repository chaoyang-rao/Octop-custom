# 定制程序与前端资源维护

自 `1.0.3b2` 起，React 界面统一从 `dashboard/` 源码构建。此前仅存在于编译补丁中的项目文件夹、目录选择器、头像、气泡配色及紧凑样式，已迁回源码，官方账户安全等新增页面也使用同一个构建。

## 重建发行覆盖层

```bash
uv run python scripts/custom/sync_octop_source.py --apply
cd dashboard
npm run build
cd ..
uv run python scripts/custom/sync_dashboard.py --apply
```

后端以 `src/octop/` 为准，只有健康检查中的定制版本标记、自动升级保护，以及运行库工具失败计数的三处请求作用域，作为明确的发行适配生成。同步前会拒绝冻结目录中的未知独立改动。

前端冻结产物位于 `customization/packages/octop/dashboard/`。生成前校验本地资源引用，不接受目录逃逸或符号链接；之后按已验证的完整源码构建替换，不累计历史版本文件。不要手工改这些生成文件。

```bash
uv run python scripts/custom/sync_octop_source.py --check
uv run python scripts/custom/sync_dashboard.py --check
```

`customization/packages/octop_harness/` 的运行库补丁单独与官方基线三方合并，不能通过复制 Octop 源码覆盖。`_vendor/http2` 保持独立的哈希锁验证。

## 历史测试基线

旧 `avatars-v60` 图及纯辅助模块保留在 `customization/baselines/avatars-v60/`，用于历史补丁回归，不随安装包发布。`avatar-asset-release.json` 明确指向此历史目录；当前发行资源由 `source-asset-release.json` 记录。

`patch_expert_avatars.py` 仅适用于 `1.0.2` 基线，升级后会主动拒绝运行，防止把缺少新版账户安全功能的旧界面覆盖回去。旧文件仍可从 Git 历史或被忽略的 `backups/` 恢复。
