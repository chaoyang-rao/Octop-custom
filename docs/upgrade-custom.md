# 保留定制与安全升级

定制代码、程序基线、补丁、测试和动态头像 skill 都保存在 Git 中。官方更新可能替换程序文件；此定制版通过独立运行目录和更新保护标记避免直接被 PyPI 升级覆盖。

官方发布新版本时，先保存当前 Git 提交，在分支合并上游变化，审查项目会话、ACP、头像及界面差异，运行测试，再重新打包三个平台。旧补丁不能跨版本盲目覆盖；下面的恢复工具仅接受真实基础包版本 **1.0.2**，依据 `packages/octop-*.dist-info/METADATA`，不会信任修改过的 `VERSION.txt`。

关闭 Octop 后，从仓库根目录执行默认只读检查：

```sh
python3 scripts/custom/restore_customization.py --check
```

默认优先检查当前用户 `~/.octop/custom-runtime/portable/packages`，若不存在则使用 `~/.octop/portable/packages`。也可以显式指定 Windows 或 macOS 的 portable 程序目录：

```sh
python3 scripts/custom/restore_customization.py --packages "/path/to/portable/packages" --check
python3 scripts/custom/restore_customization.py --packages "/path/to/portable/packages" --apply
```

工具只安装仓内程序相对原始基线的差异。替换已有文件时，目标必须匹配基线、当前仓库或上次已记录安装的 SHA-256；新增文件必须不存在或已与仓库一致。独立修改会被拒绝，不会强制覆盖。恢复时补齐 `packages/octop-custom-release.json`，即使缺少启动环境变量也能启用官方自动升级保护。

写入前会在 portable 同级 `customization-backups/` 保存将修改的程序文件、旧安装清单，以及存在的用户 `~/.octop/octop.db` 的 SQLite 一致性备份。备份目录/文件设置私有权限；用户配置、专家工作区、上传图片及当前聊天数据库不会被程序恢复覆盖。不要把这些备份上传 GitHub。

检查和执行程序回退：

```sh
python3 scripts/custom/restore_customization.py --packages "/path/to/portable/packages" --rollback "/path/to/backup" --check
python3 scripts/custom/restore_customization.py --packages "/path/to/portable/packages" --rollback "/path/to/backup" --apply
```

回退前再次核验安装文件与备份；后续有独立修改时会拒绝。回退只还原程序和原安装清单，**不会自动还原数据库**，因此安装后产生的新聊天会保留。数据库快照仅供明确的数据灾难恢复操作使用。
