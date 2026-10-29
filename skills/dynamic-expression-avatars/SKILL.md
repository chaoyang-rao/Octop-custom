---
name: dynamic-expression-avatars
description: 制作和接入“动态表情头像”：大圆眼、宽眼距、几何角色、独立神态动作与可组合配色。用于 AI 专家/助手头像、动态头像选择器、已有头像系统升级，以及指定列表中的头像尺寸调整。支持 React 与透明 SVG、WebP/GIF 导出；不用于照片人像或 ChatGPT 宠物。
---

# 动态表情头像

复用附带的原创几何角色库。默认 7 种形状、7 种独立颜色，共 49 种组合；用户指定其他数量或样式时按其要求调整。程序生成主体、眼神和动作，无需图片或视频生成服务。

## 确定工作位置

- 新素材或预览：运行下方脚本，输出到任务目录的新子目录。
- 接入产品：读 [接入约定](references/integration.md)，检查已有头像数据、创建/编辑表单与实际显示组件。
- 调整尺寸：确认用户指哪个位置，检查**主体 viewBox、组件尺寸、外层槽位和 overflow**，只改指定位置。增大内部 SVG 不会突破固定槽位。
- 本机 Octop 续改：另读 [Octop 案例](references/octop.md)，先核对当前版本，不把案例补丁直接覆盖到其他版本。

用户已给出参考、数量和目标位置时直接做；只在缺失信息会改变结果时询问。

## 视觉与动作

`assets/avatar-library.mjs` 是形状、颜色、动作和对比度的唯一代码源。

- 大圆眼，常态双眼中心间距 100、直径约 54～58（512 设计坐标）；眨眼自然压缩。改眼距后检查主体边界及小尺寸可读性。
- 软团安静呼吸、棱石好奇张望轻跳、圆方专注思考、水滴腼腆探头、云朵开心漂浮、星星兴奋蓄力、三角沉稳点头。不能只换轮廓却让动作全相同。
- 默认色：曜石、青绿、晴蓝、鸢紫、莓粉、蜜橙、珊瑚。形色独立组合，不为每个组合重画角色。
- 默认 6 秒闭环。React 版支持减少动态效果、不可见暂停和卸载清理；复用模块级 factory，不在每次 render 中重建时钟。
- 可参考产品气质，不复制第三方头像素材或实现。

## 导出

需 Node.js，无 npm 依赖。`<skill-dir>` 指本 SKILL.md 所在目录，输出必须是新目录或空目录：

```sh
node <skill-dir>/scripts/export_avatars.mjs --out <任务目录>/avatars-v1
```

输出透明动态 SVG、形色目录、可交互 `index.html` 和检查结果；预览无需外部模块，可直接打开，也可通过本地 HTTP 服务展示。只生成部分组合：

```sh
node <skill-dir>/scripts/export_avatars.mjs --out <任务目录>/avatar-pilot --shapes blob,star --colors ink,jade
```

素材预览默认不带产品气泡功能。目标包含单独对话框，或需要查看头像与气泡的配色示例时，可加 `--bubble-demo`；这仍只是预览，不代表产品已经接入。

要求 WebP/GIF 时，先为选定组合导出确定性帧，再编码；Python 环境需已有 Pillow：

```sh
node <skill-dir>/scripts/export_avatars.mjs --out <任务目录>/avatar-export --shapes blob --colors jade --frames
python3 <skill-dir>/scripts/encode_animation.py <任务目录>/avatar-export/frames/blob-jade.json --out <任务目录>/avatar-export
```

WebP 保留完整 Alpha，GIF 使用其格式支持的透明边缘。不要改扩展名冒充格式。脚本不覆盖同名输出，修改时用新版本目录。

## 接入与验证

从 `createExpertAvatars({React})` 取得 `Avatar`、`ShapeColorPicker`、`renderAvatar`。复制 `assets/avatar-picker.css` 并接入现有样式，不替换产品其他主题。

形色各自持久化；展示 URL 只是投影，不能覆盖原上传图片。保留用户当前组合。旧图恢复、模板和部分字段更新见 [接入约定](references/integration.md)。

目标包含单独对话框时，保留同色气泡的接入方案，可联动 `bubbleStyle(color)`：用户正文气泡使用该专家的头像基色，并自动选清晰文字；群聊、助手和附件不跟随改色。判断群聊依据当前会话类型，不修改全局品牌色。纯头像素材或没有对话框的界面不附加气泡方案；本次若仅调整头像尺寸，保留产品既有气泡行为。

预览真实动画，检查眨眼、动作极值、循环接缝、真实列表尺寸与裁剪。导出脚本验证形色、边界、闭环和对比度；工程接入还需保存读回、切换会话、减少动态效果与作用范围验证。只做与改动有关的检查，不为素材任务启动模型会话或改生产数据。

展示可直接观看的结果，素材用绝对路径，工程修改说明位置与实际验证范围。制作素材不等于授权修改运行中的产品。
