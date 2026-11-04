import * as React from 'react';
import {createRoot} from 'react-dom/client';
import './design-canvas.jsx';
import {Icon,labels,families} from './icons.jsx';
import {createExpertAvatars} from './avatar-library.mjs';
import {createExpertPresentation} from './presentation.mjs';
import './avatars.css';
import './presentation.css';
import './preview.css';
const {DesignCanvas,DCSection,DCArtboard}=window;
const avatars=createExpertAvatars({React});
const {ExpertPortrait,TeamPortrait}=createExpertPresentation({React,avatars});
const experts=[{agent_id:'main',name:'小通',avatar_shape:'pebble',avatar_color:'blue',is_team_primary:true},{agent_id:'analyst',name:'数据分析师',avatar_shape:'squircle',avatar_color:'jade'},{agent_id:'designer',name:'设计师',avatar_shape:'cloud',avatar_color:'rose'}];
const nav=['chat','experts','teams','tasks','automations','files','connectors','cloud'];
const tools=['attach','image','mic','search','think','terminal'];
function Tool({name,family,active,onClick,disabled=false,nav=false}){
 return <button type="button" title={labels[name]} aria-label={labels[name]} aria-pressed={active===undefined?undefined:active} disabled={disabled} onClick={onClick} className={`icon-button ${nav?'rail-button':''} ${active?'is-active':''}`}><Icon family={family} name={name} size={nav?21:16}/></button>;
}
function MockApp({family}){
 const [tab,setTab]=React.useState('chat');
 const [enabled,setEnabled]=React.useState(['think']);
 const [draft,setDraft]=React.useState('');
 const [sent,setSent]=React.useState(false);
 const [model,setModel]=React.useState('自动选择');
 const [modelOpen,setModelOpen]=React.useState(false);
 const [note,setNote]=React.useState('');
 const toggle=name=>{
  if(['think','search','terminal'].includes(name))setEnabled(v=>v.includes(name)?v.filter(x=>x!==name):[...v,name]);
  setNote(`${labels[name]}${['think','search','terminal'].includes(name)?'已切换':' · 预览'}`);
 };
 return <div className="mock-app" data-family={family}>
  <nav className="rail" aria-label="侧边栏预览"><div className="appmark">o<span>·</span></div><div className="rail-top">{nav.map(name=><Tool key={name} family={family} name={name} nav active={tab===name} onClick={()=>{setTab(name);setNote(`已选择${labels[name]}`)}}/>)}</div><div className="rail-bottom"><Tool name="settings" family={family} nav onClick={()=>setNote('设置 · 预览')}/><button className="account" title="账号头像 · 姓名缩写">CR</button></div></nav>
  <aside className="expert-pane"><div className="pane-label">我的专家 <span>＋</span></div>{experts.map((agent,i)=><button key={agent.agent_id} className={`expert-row ${i===0?'selected':''}`} onClick={()=>setNote(`${agent.name} · 预览`)}><ExpertPortrait agent={agent} size={36}/><span>{agent.name}<small>{i===0?'主专家':i===1?'空闲':'工作中'}</small></span></button>)}<div className="pane-label team-label">团队</div><button className="expert-row team-row" onClick={()=>setNote('产品工作室 · 预览')}><TeamPortrait members={experts} size={36}/><span>产品工作室<small>小通主持</small></span></button><div className="pane-footer">{tab==='chat'?'最近对话':labels[tab]} <span>›</span></div></aside>
  <section className="chat-pane"><header className="chat-header"><span><strong>小通</strong><small><i/>空闲</small></span><Tool family={family} name="expand" onClick={()=>setNote('全屏 · 可点上方单独查看')}/></header>
   <div className="messages"><div className="day-label">今天</div><div className="chat-message"><ExpertPortrait agent={experts[0]} size={28}/><div><div className="speaker">小通</div><p>需要一起推进什么？<br/>我可以安排合适的专家协作。</p></div></div><div className="user-message">帮我看看本周的工作安排。</div><div className="chat-message reply"><ExpertPortrait agent={experts[0]} size={28}/><div><div className="speaker">小通</div><p>好，我先整理待办，再和相关专家确认。<br/>关键进展会在任务群同步。</p><button className="reasoning" onClick={()=>setNote('分析过程已展开 · 预览')}><Icon family={family} name="think" size={13}/><span>分析与工具记录</span><span>›</span></button></div></div>{sent&&<div className="user-message">{sent}</div>}</div>
   <div className="composer"><textarea aria-label="聊天输入框预览" placeholder="给小通发消息…" value={draft} onChange={e=>setDraft(e.target.value)} rows={2}/><div className="tool-row"><div className="model-control"><button className="model-button" onClick={()=>setModelOpen(!modelOpen)} aria-expanded={modelOpen} aria-label="切换模型"><Icon family={family} name="model" size={16}/><span>{model}</span><span className="chevron">⌄</span></button>{modelOpen&&<div className="model-menu">{['自动选择','推理模型','快速模型'].map(v=><button key={v} onClick={()=>{setModel(v);setModelOpen(false);setNote(`模型：${v}`)}}>{v}{model===v?' ✓':''}</button>)}</div>}</div><span className="tool-divider"/>{tools.map(name=><Tool key={name} name={name} family={family} active={['think','search','terminal'].includes(name)?enabled.includes(name):undefined} onClick={()=>toggle(name)}/>)}</div><div className="composer-footer"><span className="composer-hint">Enter 发送 · Shift + Enter 换行</span><div className="send-tools"><button className="context-control" title="上下文用量 28%" aria-label="上下文用量 28%" onClick={()=>setNote('当前上下文 28% · 预览')}><Icon family={family} name="context" size={16}/><span>28%</span></button><Tool family={family} name="send" disabled={!draft.trim()} onClick={()=>{setSent(draft);setDraft('');setNote('消息已展示 · 预览')}}/></div></div></div><div className="live-note" aria-live="polite">{note||'可点侧栏、工具和模型菜单体验'}</div>
  </section>
 </div>;
}
function Direction({item,selected,onSelect}){
 const specimen=['chat','experts','teams','tasks','automations','files','connectors','cloud','model','attach','image','mic','search','think','terminal','context','settings','send'];
 return <article className="direction" style={{'--accent':item.accent}} data-family={item.id}><div className="direction-head"><div className="edition">{item.id.toUpperCase()} <span>{item.en}</span></div><h2>{item.title}</h2><p>{item.desc}</p></div><div className="hero-icons">{["chat","experts","teams","files","cloud","settings"].map(name=><div key={name}><Icon family={item.id} name={name} size={38}/><span>{labels[name]}</span></div>)}</div><div className="actual-label">实际界面 <span>侧栏 21 px / 工具栏 16 px</span></div><MockApp family={item.id}/><div className="specimens"><div className="specimen-label">图标全览 <span>20 px</span></div><div className="glyph-grid">{specimen.map(name=><div key={name} className="glyph-cell" title={labels[name]}><Icon family={item.id} name={name} size={20}/><span>{labels[name]}</span></div>)}</div></div><footer className="direction-footer"><div><a href={`option-${item.id}.html`} target="_blank" rel="noreferrer">单独查看 ↗</a><a href={`option-${item.id}.html`} download>下载方案</a><a className="credits" href="CREDITS.html" target="_blank" rel="noreferrer">来源</a></div><button className={`choose ${selected===item.id?'chosen':''}`} aria-pressed={selected===item.id} onClick={()=>onSelect(item.id)}>{selected===item.id?'✓ 已选 '+item.id.toUpperCase():'选用 '+item.id.toUpperCase()}</button></footer></article>;
}
function App(){
 const standalone=document.body.dataset.family;
 const [theme,setTheme]=React.useState('light');
 const [selected,setSelected]=React.useState(()=>localStorage.getItem('octop-icon-refined-choice')||'');
 React.useEffect(()=>{document.documentElement.dataset.theme=theme},[theme]);
 const choose=id=>{setSelected(id);localStorage.setItem('octop-icon-refined-choice',id)};
 const item=families.find(x=>x.id===standalone);
 return <><header className="page-head"><div className="project-caption">OCTOP / ICON STUDY <span>02</span></div><div className="page-title"><div><h1>图标 · 第二轮</h1><p>先看放大的造型细节，再比较实际尺寸的侧栏和工具栏</p></div><div className="page-actions">{!standalone&&<><a href="option-a.html">看 A</a><a href="option-b.html">看 B</a><a href="option-c.html">看 C</a></>}{standalone&&<a href="index.html">全部方案</a>}<button onClick={()=>setTheme(theme==='light'?'dark':'light')} aria-label="切换浅深色">{theme==='light'?'深色预览':'浅色预览'}</button></div></div></header>{item?<main className="single"><Direction item={item} selected={selected} onSelect={choose}/></main>:<DesignCanvas style={{height:1180}}><DCSection id="directions" title="第二轮 / A · B · C" subtitle="点击单独查看，可体验完整布局与交互" gap={28}><DCArtboard id="precision" label="A · 圆弧细线" width={352} height={955}><Direction item={families[0]} selected={selected} onSelect={choose}/></DCArtboard><DCArtboard id="solid" label="B · 墨色双层" width={352} height={955}><Direction item={families[1]} selected={selected} onSelect={choose}/></DCArtboard><DCArtboard id="facet" label="C · 柔光彩塑" width={352} height={955}><Direction item={families[2]} selected={selected} onSelect={choose}/></DCArtboard></DCSection></DesignCanvas>}<div className="review-status" aria-live="polite">{selected?`预览选择：${selected.toUpperCase()} · 告诉我所选方案后，应用到 Octop。`:'第二轮三版 · 可从顶部单独查看完整界面。'}</div></>;
}
createRoot(document.getElementById('root')).render(<App/>);
