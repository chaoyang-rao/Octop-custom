# 接入约定

## 库接口

`avatar-library.mjs` 支持浏览器 ESM 和 Node，无第三方运行依赖。

- `SHAPES`：`blob / pebble / squircle / droplet / cloud / star / triangle`。
- `COLORS`：`ink / jade / blue / violet / rose / amber / coral`，带中文名和 `hex`。
- `createExpertAvatars({React})`：返回 `Avatar`、`ShapeColorPicker`、`renderAvatar` 及兼容别名。保存返回值，复用已有 React 实例。
- `Avatar({shape,color,size,className,style,static})`：原生 SVG；`static:true` 固定初始姿态。
- `ShapeColorPicker({shape,color,onShapeChange,onColorChange,disabled})`：独立选择形色。
- `avatarFrame(shape,color,time)`：单帧几何；`VIEWBOXES` 容纳各形状全部动作。
- `animatedSvg(shape,color)`：有减少动态效果静态替代的独立 SVG。
- `bubbleStyle(color)`：返回 `backgroundColor`、`color` 与局部选区变量。
- `avatarUrl` 默认输出 `/avatars/v2/`，`parseAvatarUrl` 兼容 v1/v2；接服务时按真实路由适配。处理绝对 URL 时核对 origin 和受控 pathname，不把任意图片 URL 识别为内置头像。

## 数据与旧图

独立存 `{shape,color}`，不混入已有卡片主题色。现有 JSON 配置可满足时，不必强制加表。

- 省略字段保留原值，显式 `shape:null` 才恢复旧图。只改颜色不丢形状。
- 仅计算展示 URL，保留原上传路径和文件。旧编辑器原样回传生成 URL 时，不得覆盖原图地址。
- 上传新图明确切回图片模式，颜色可保留。创建表单切回几何模式时清理待上传临时引用，避免提交后图片再次覆盖选择。
- 列表/详情返回同一份形色；编辑器可另取 `uploaded_icon_url` 显示原图。
- 模板导出/安装携带形色；只改一项时逐字段继承，显式空值保持恢复语义。
- 保持原权限及上传限制。受控 SVG 不意味着开放任意 SVG 上传。

账号的姓名头像是“无图片/未选内置头像”时的回退，不能无条件覆盖已上传图片或明确选中的内置头像。账号选择器可将“无图片（显示姓名）”放在第一项，保存后同步账号上下文；图片与内置选项仍须可用。更换图片时确保版本 URL 随内容更新，防止缓存把新选择显示成旧图。

## UI 与尺寸

设置、专家列表、团队列表、云端列表、聊天及手机紧凑模式可能共享内图，却各有固定外槽。只改用户指定位置的外槽宽高、行高、flex、overflow 与调用 `size`；旧图和几何图使用一致目标尺寸。不要把列表调整传播到聊天或设置。

新旧图分支挂载为独立 React 组件，避免改变 hooks 数量。颜色按钮有名称和选中标记，形状选择键盘可达。

## 单聊气泡（目标包含对话框时）

目标包含单独对话框时可使用本方案；纯头像素材或无对话框界面不附加。仅调整某处头像大小时，不顺带更改已有气泡。

同时满足：用户消息、当前会话不是群聊、角色启用有效几何形状。不要用发言成员的普通专家类型代替当前会话类型判断。

背景用实际 `hex`，不暗换成浅色透明底。本套蓝紫已适当加深：曜石、晴蓝、鸢紫配白字，青绿、莓粉、蜜橙、珊瑚配 `#0B101B`，均满足 4.5:1。修改配色后重新核算对比度，头像与气泡使用同一基色。局部 `::selection` 反转前景背景并覆盖正文子节点；别改全局品牌色，别强改附件后代正常文字颜色。

核对七色对比、旧图模式、单聊→群聊→单聊、助手/附件、保存与刷新。没有群聊实机环境时，说明自动检查范围，不声称已完成群聊实机验证。
