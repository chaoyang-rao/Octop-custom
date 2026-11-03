import * as React from "react";
import { createRoot } from "react-dom/client";
import { SHAPES, COLORS, bubbleStyle, createExpertAvatars } from "../../../dashboard/src/components/expertPortrait/avatar-library.mjs";
import { createExpertPresentation } from "../../../dashboard/src/components/expertPortrait/presentation.mjs";
import "../../../dashboard/src/components/expertPortrait/presentation.css";
import "./preview.css";

const avatars = createExpertAvatars({ React });
const { TeamPortrait } = createExpertPresentation({ React, avatars });
const member = (i: number) => ({ agent_id: `preview-${i}`, avatar_shape: SHAPES[i % 9].id, avatar_color: ["ink", "rose", "coral", "jade"][i % 4] });

function Preview() {
  const [color, setColor] = React.useState<string | null>(null);
  const [dark, setDark] = React.useState(false);
  return <main data-theme={dark ? "dark" : "light"}>
    <header><div><p className="eyebrow">OCTOP · 动态表情头像</p><h1>规整的轮廓，鲜明的性格。</h1><p>九种形状 × 九种颜色 · 保留大圆眼与宽眼距</p></div><button className="theme-button" onClick={() => setDark(!dark)}>{dark ? "浅色背景" : "深色背景"}</button></header>
    <nav aria-label="头像颜色"><button className="reset" onClick={() => setColor(null)} aria-pressed={color === null}>各自配色</button>{COLORS.map(c => <button key={c.id} onClick={() => setColor(c.id)} aria-label={c.name} aria-pressed={color === c.id}><i style={{ background: c.hex }} />{c.name}</button>)}</nav>
    <section className="shape-grid" aria-label="九种动态形状">{SHAPES.map((s, i) => <article key={s.id}>
      {avatars.renderAvatar({ shape: s.id, color: color || COLORS[i].id, size: 112 })}<div><h2>{s.name}<small>{s.mood}</small></h2><p>{s.motion}</p></div>
    </article>)}</section>
    <section className="team-section"><h2>团队头像</h2><p>略微倾斜，朝右上看；轮廓之间用细白边分隔，整体无外框。</p><div className="team-examples">{[2, 3, 4].map(count => <div className="team-example" key={count}><TeamPortrait members={Array.from({ length: count }, (_, i) => member(i))} size={64} /><div><h3>{count} 位成员</h3><span>固定 64px 空间</span></div></div>)}</div>
    <div className="size-grid">{[24, 32, 48, 64].map(size => <div className="size-example" key={size}><span>{size}px</span>{[2, 3, 4].map(count => <TeamPortrait key={count} members={Array.from({ length: count }, (_, i) => member(i))} size={size} />)}</div>)}</div></section>
    <section className="bubble-examples"><p>私聊气泡继续跟随头像配色</p><div>{COLORS.map(c => <span key={c.id} style={bubbleStyle(c.id)}>{c.name} · 清晰文字</span>)}</div></section>
    <footer>此页使用 Octop 实际头像组件 · 六秒循环 · 支持减少动态效果</footer>
  </main>;
}
createRoot(document.getElementById("root")!).render(<Preview />);
