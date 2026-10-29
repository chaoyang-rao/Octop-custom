import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';
const base=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const modulePath=path.join(base,'packages/octop/dashboard/assets/expert-avatars.js');
const {SHAPES,COLORS,VIEWBOXES,avatarFrame,animatedSvg,avatarUrl,parseAvatarUrl,bubbleStyle,contrast}=await import(pathToFileURL(modulePath));
const assets=path.join(base,'packages/octop/dashboard/expert-avatars/v2');
const preview=path.resolve(base,'../designs/avatar-library-20261028');
fs.mkdirSync(assets,{recursive:true});
fs.mkdirSync(path.join(preview,'assets'),{recursive:true});
fs.mkdirSync(path.join(preview,'qa'),{recursive:true});
assert.equal(SHAPES.length,7);assert.equal(COLORS.length,7);
const catalog={version:2,shapes:SHAPES,colors:COLORS,variants:[]};
const frames=[];
for(const [i,shape] of SHAPES.entries()) {
  const [vx,vy,vw,vh]=VIEWBOXES[shape.id].split(' ').map(Number);
  const first=avatarFrame(shape.id,COLORS[i].id,0);
  assert.deepEqual(first,avatarFrame(shape.id,COLORS[i].id,6));
  assert.notDeepEqual(first.body,avatarFrame(shape.id,COLORS[i].id,2.56).body);
  for(let t=0;t<6;t+=.12) {
    const f=avatarFrame(shape.id,COLORS[i].id,t);
    for(const [x,y] of [...f.body,...f.eyes.flat()]) {
      assert.ok(Number.isFinite(x)&&Number.isFinite(y));
      assert.ok(x>vx+2&&x<vx+vw-2&&y>vy+2&&y<vy+vh-2,`${shape.id}: clipped geometry in enlarged viewBox`);
    }
  }
  frames.push({shape:shape.id,name:shape.name,color:COLORS[i].id,poses:[0,1,2.56,3.76].map(t=>({t,frame:avatarFrame(shape.id,COLORS[i].id,t)}))});
  for(const color of COLORS) {
    const name=`${shape.id}-${color.id}.svg`,url=avatarUrl(shape.id,color.id);
    const text=animatedSvg(shape.id,color.id);
    assert.deepEqual(parseAvatarUrl(url),{shape:shape.id,color:color.id});
    assert.ok(text.includes('prefers-reduced-motion'));assert.ok(!/<script\b/i.test(text));
    fs.writeFileSync(path.join(assets,name),text);
    fs.writeFileSync(path.join(preview,'assets',name),text);
    catalog.variants.push({shape:shape.id,color:color.id,url});
  }
}
for(const color of COLORS) {
  const style=bubbleStyle(color.id);assert.equal(style.backgroundColor,color.hex);
  assert.ok(contrast(style.backgroundColor,style.color)>=4.5,`${color.id} text contrast`);
  assert.equal(style.color,['ink','blue','violet'].includes(color.id)?'#FFFFFF':'#0B101B',`${color.id} preferred text polarity`);
}
assert.equal(new Set(catalog.variants.map(v=>v.url)).size,49);
fs.writeFileSync(path.join(assets,'catalog.json'),JSON.stringify(catalog,null,2));
fs.writeFileSync(path.join(preview,'catalog.json'),JSON.stringify(catalog,null,2));
fs.writeFileSync(path.join(preview,'qa/frames.json'),JSON.stringify(frames));
fs.copyFileSync(modulePath,path.join(preview,'expert-avatars.js'));
fs.writeFileSync(path.join(preview,'qa/checks.json'),JSON.stringify({variant_count:49,shape_count:7,color_count:7,loop:'6 seconds',bounds:'all sampled body and eye geometry inside viewBox',bubble_contrast:'all >=4.5:1',group_scope:'frontend guard required; tested separately'},null,2));
console.log('Built 49 SVG assets. All geometry, loop, URL and bubble contrast checks passed.');
