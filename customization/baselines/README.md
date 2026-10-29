# 可复现程序基线

这里保存最初定制时使用的程序文件，供新克隆重建前端补丁和核对官方升级差异。

- `original/`：Octop 1.0.2 程序，保留当时已有的桌面 SSO 修复。
- `projects-v2/`：已加入项目会话与 ACP 目录绑定的程序，作为动态头像和后续 UI 调整的输入。

两份基线只包含 `octop`、`octop_harness`、`octop_gateway` 程序目录，不包含聊天数据库、账户配置、密钥、运行日志或 Python 缓存。各目录的 `manifest.json` 列出文件 SHA-256。上游版本锁定 `v1.0.2`，提交 `dd9dce470844c25d59effb50615bb3c667ea25cd`；这些是保留本地修复的发行基线，并非未修改的上游源码快照。

从仓库根目录执行：

```sh
python3 customization/frontend/patch_project_sidebar.py
node customization/avatar-library/build_assets.mjs
python3 customization/frontend/patch_expert_avatars.py
```

生成结果位于 `customization/packages/`，无需原机器的 `backups/`。不要从用户数据目录重新制作基线；后续升级应先审查上游变化，再更新基线和补丁。
