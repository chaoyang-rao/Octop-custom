import * as React from 'react';
import data from './icon-data.json';
export const labels = {chat:'对话',experts:'专家',teams:'团队',tasks:'任务队列',automations:'定时任务',files:'工作空间',connectors:'连接器',cloud:'云端协作',settings:'设置',model:'切换模型',attach:'添加附件',image:'添加图片',mic:'语音输入',search:'联网搜索',think:'深度思考',terminal:'终端',context:'上下文用量',send:'发送',expand:'全屏'};
export function Icon({family='a',name,size=20}) {
 const id=React.useId().replace(/:/g,'');
 const icon=data[family][name]||data[family].chat;
 const body=React.useMemo(()=>{
  const prefix=`icon-${id}-`;
  const ids=[...icon.body.matchAll(/\bid="([^"]+)"/g)].map(match=>match[1]);
  return ids.reduce((svg,original)=>svg.replaceAll(`id="${original}"`,`id="${prefix}${original}"`).replaceAll(`url(#${original})`,`url(#${prefix}${original})`).replaceAll(`href="#${original}"`,`href="#${prefix}${original}"`),icon.body);
 },[icon,id]);
 return <svg aria-hidden="true" width={size} height={size} viewBox={`0 0 ${icon.width} ${icon.height}`} fill="none" className={`glyph family-${family} glyph-${name}`} dangerouslySetInnerHTML={{__html:body}}/>;
}
export const families = [
 {id:'a',title:'圆弧细线',en:'ARC / LINE',desc:'舒展的圆弧、均匀的笔画，保持清透与秩序。',accent:'#53647e'},
 {id:'b',title:'墨色双层',en:'INK / DUOTONE',desc:'深色骨架叠加柔和底层，形体清楚而不厚重。',accent:'#496f68'},
 {id:'c',title:'柔光彩塑',en:'SOFT / COLOR',desc:'圆润体积、细腻渐变，用克制的光影建立层次。',accent:'#6364af'},
];
