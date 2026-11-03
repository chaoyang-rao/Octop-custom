# Octop 案例

这是接入参考，不是自动部署指令。只有请求修改该应用时使用，先核对路径、版本和本地定制。

- 存储为 `config_json.avatar={shape,color}`，API 顶层 `avatar_shape/avatar_color`。
- `icon_url` 只在响应中投影，`uploaded_icon_url` 保留原图展示地址；存储中不替换原上传路径。
- 新建/编辑和模板均携带元数据；更新接口忽略旧客户端回传的合法生成 URL，防止原图地址丢失。
- 当前资源路由 `/expert-avatars/v2/{shape}-{color}.svg` 与通用模板不同；兼容识别旧 v1 投影，避免旧客户端回传时破坏原上传图。
- `ExpertIcon/ExpertAgentAvatar` 分派新旧图，表单接选择器；`MessageBubble` 仅在单聊用户正文联动配色。
- 当前采用九形九色。`dashboard/src/components/expertPortrait/avatar-library.mjs` 负责视觉；后端 `infra/agents/settings/geometric_avatar.py` 接受同一组 ID，`presentation.mjs` 从视觉库获取随机选项，不再另写七项列表。旧 ID 保留，避免清空专家设置。
- `TeamPortrait` 按可见人数布局：一人占满、两人错位、三人三角聚合、四人紧凑四宫格；同组成员的尺寸一致，整个构图保持在指定槽位内，不添加整体外圈或阴影。倾斜及右上视线来自头像库本身，不另外叠加容器旋转；使用 `[data-avatar-body]` 的白色轮廓描边分隔成员。检查 24/32/48/64px 及深浅背景。

此案例尺寸的最终指向是**“专家、团队、云端”入口列表中的头像**。经典与极简共用内图但外槽不同，旧槽 28/26/22px 会限制内图放大。修正同时改列表外槽和调用尺寸；设置及聊天先前已做的放大保留，不再扩大。

构建资源有 immutable 缓存时，给受影响的完整模块图统一新版本，更新入口与引用，不能仅改同名主文件。保留项目会话、ACP、登录等其他定制。备份后按差异安装、回读并实机验证；不要在通用 skill 中放机器绝对路径、凭据或自动重启命令。
