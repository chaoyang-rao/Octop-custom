#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
import {SHAPES,COLORS,VIEWBOXES,avatarFrame,animatedSvg,bubbleStyle,contrast} from '../assets/avatar-library.mjs';
const args=process.argv.slice(2),opts={};
for(let i=0;i<args.length;i++){
  const key=args[i];
  if(key==='--help'||key==='-h'){console.log('Usage: node export_avatars.mjs --out NEW_DIR [--shapes blob,star] [--colors ink,jade] [--frames] [--fps 25] [--bubble-demo]');process.exit(0);}
  if(key==='--frames'){opts.frames=true;continue;}
  if(key==='--bubble-demo'){opts.bubbleDemo=true;continue;}
  if(!['--out','--shapes','--colors','--fps'].includes(key)||!args[i+1])throw new Error(`Unknown or incomplete option: ${key}`);
  opts[key.slice(2)]=args[++i];
}
if(!opts.out)throw new Error('--out is required');
function select(all,raw,label){
  if(!raw)return all;
  const ids=[...new Set(raw.split(',').filter(Boolean))];
  if(!ids.length||ids.some(id=>!all.some(x=>x.id===id)))throw new Error(`Invalid ${label}: ${raw}`);
  return all.filter(x=>ids.includes(x.id));
}
const shapes=select(SHAPES,opts.shapes,'shape'),colors=select(COLORS,opts.colors,'color'),fps=Number(opts.fps||25);
if(!Number.isInteger(fps)||fps<5||fps>60)throw new Error('--fps must be integer 5–60');
const out=path.resolve(opts.out);
if(fs.existsSync(out)&&fs.readdirSync(out).length)throw new Error('Output must be new or empty; choose a sibling version directory.');
fs.mkdirSync(path.join(out,'assets'),{recursive:true});
if(opts.frames)fs.mkdirSync(path.join(out,'frames'),{recursive:true});
const skill=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
for(const [src,dst] of [['avatar-library.mjs','avatar-library.mjs'],['avatar-picker.css','avatar-picker.css']])fs.copyFileSync(path.join(skill,'assets',src),path.join(out,dst));
let gallery=fs.readFileSync(path.join(skill,'assets/gallery.html'),'utf8');
const bubbleStyles=Object.fromEntries(colors.map(c=>[c.id,bubbleStyle(c.id)]));
// The preview itself must also work when double-clicked, without file-origin
// module fetches. Keep the reusable module alongside it for application use.
gallery=gallery.replace('<script type="module">','<script>')
  .replace("import {SHAPES,COLORS,bubbleStyle} from './avatar-library.mjs';",`const SHAPES=${JSON.stringify(shapes)},COLORS=${JSON.stringify(colors)},BUBBLE_STYLES=${JSON.stringify(bubbleStyles)};\nconst bubbleStyle=id=>BUBBLE_STYLES[id]||BUBBLE_STYLES[COLORS[0].id];`)
  .replaceAll('COLORS[i].id','COLORS[i%COLORS.length].id')
  .replace('七个小家伙，各有脾气。',`${shapes.length} 个小家伙，各有脾气。`)
  .replace('七种头像形状',`${shapes.length} 种头像形状`)
  .replace('7 种形状和 7 种颜色自由搭配。',`${shapes.length} 种形状和 ${colors.length} 种颜色自由搭配。`);
if(!opts.bubbleDemo)gallery=gallery.replace(/\s*<section class="bubble-demo"[\s\S]*?<\/section>/,'');
fs.writeFileSync(path.join(out,'index.html'),gallery);
const variants=[];
for(const shape of shapes){
  const [vx,vy,vw,vh]=VIEWBOXES[shape.id].split(' ').map(Number);
  for(const color of colors){
    const name=`${shape.id}-${color.id}.svg`;assert.deepEqual(avatarFrame(shape.id,color.id,0),avatarFrame(shape.id,color.id,6));
    const samples=[];
    for(let i=0;i<6*fps;i++){
      const f=avatarFrame(shape.id,color.id,i/fps);
      for(const [x,y] of [...f.body,...f.eyes.flat()])assert.ok(Number.isFinite(x)&&Number.isFinite(y)&&x>vx&&x<vx+vw&&y>vy&&y<vy+vh,`${name}: clipped frame ${i}`);
      if(opts.frames)samples.push(f);
    }
    fs.writeFileSync(path.join(out,'assets',name),animatedSvg(shape.id,color.id));
    const style=bubbleStyle(color.id);assert.ok(contrast(style.backgroundColor,style.color)>=4.5);
    if(opts.frames)fs.writeFileSync(path.join(out,'frames',`${shape.id}-${color.id}.json`),JSON.stringify({shape:shape.id,color:color.id,fps,duration:6,viewBox:VIEWBOXES[shape.id],frames:samples}));
    variants.push({shape:shape.id,color:color.id,path:`assets/${name}`});
  }
}
fs.writeFileSync(path.join(out,'catalog.json'),JSON.stringify({name:'动态表情头像',shapes,colors,variants,duration_seconds:6,checks:{loop:'passed',bounds:'passed',bubble_contrast:'>=4.5:1'}},null,2));
console.log(JSON.stringify({output:out,shapes:shapes.length,colors:colors.length,variants:variants.length,frames:!!opts.frames}));
