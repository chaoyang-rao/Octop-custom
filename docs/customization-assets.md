# 定制前端资源维护

React 源码位于 `dashboard/`，定制安装包使用
`customization/packages/octop/dashboard/`。后者还保留构建所需的未版本化辅助文件；
不能整目录删除，也不能用源码构建结果直接覆盖并丢弃既有定制。

## 重建和清理

修改定制补丁后，递增 `customization/frontend/patch_expert_avatars.py` 的
`RELEASE`，再运行：

```bash
uv run python customization/frontend/patch_expert_avatars.py
```

构建器从 `customization/baselines/projects-v2/` 和辅助文件生成当前资源及清单，
校验页面与延迟加载资源的引用后，清理旧 `avatars-vN` 文件及未使用的生成样式。
它会保留构建基线、未版本化辅助文件、字体、图片和当前页面的完整依赖。
当前资源缺失或仍引用旧版本时，清理会失败，不会删除候选文件。

单独预览或执行清理：

```bash
uv run python customization/frontend/prune_assets.py
uv run python customization/frontend/prune_assets.py --apply
```

执行清理前应提交代码或将待保存文件归档到被 Git 忽略的 `backups/`。
旧发布资源可以从 Git 历史及归档恢复，不再为测试常驻安装包目录。
头像、账号及导航测试使用保留的构建基线和当前发布清单。
