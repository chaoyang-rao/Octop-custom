/* Original Octop geometric avatars. Geometry, expression and motion are authored
 * here; no artwork or implementation from another product is embedded. */
export const SHAPES = Object.freeze([
  { id: 'blob', name: '软团', mood: '安静', motion: '轻呼吸 · 双眨眼' },
  { id: 'pebble', name: '棱石', mood: '好奇', motion: '左右张望 · 单眨轻跳' },
  { id: 'squircle', name: '圆方', mood: '专注', motion: '眯眼思考 · 轻偏头' },
  { id: 'droplet', name: '水滴', mood: '腼腆', motion: '探头 · 害羞眨眼' },
  { id: 'cloud', name: '云朵', mood: '开心', motion: '轻轻漂浮 · 笑眼' },
  { id: 'star', name: '星星', mood: '兴奋', motion: '蓄力跳起 · 摇摆' },
  { id: 'triangle', name: '三角', mood: '沉稳', motion: '缓慢环顾 · 点头' },
]);
export const COLORS = Object.freeze([
  { id: 'ink', name: '曜石', hex: '#252830' },
  { id: 'jade', name: '青绿', hex: '#19B7A2' },
  { id: 'blue', name: '晴蓝', hex: '#5277DD' },
  { id: 'violet', name: '鸢紫', hex: '#9370D8' },
  { id: 'rose', name: '莓粉', hex: '#DB779A' },
  { id: 'amber', name: '蜜橙', hex: '#DCAA46' },
  { id: 'coral', name: '珊瑚', hex: '#E5805D' },
]);
const shapeIds = new Set(SHAPES.map(x => x.id));
const colorIds = new Set(COLORS.map(x => x.id));
export const validShape = id => shapeIds.has(id);
export const validColor = id => colorIds.has(id);
export const getColor = id => COLORS.find(x => x.id === id) || COLORS[0];
// Tight but motion-safe framing: the whole six-second motion remains visible.
export const VIEWBOXES = Object.freeze({
  blob: '40 40 432 432', pebble: '40 32 432 432',
  squircle: '56 56 400 400', droplet: '40 48 432 432',
  cloud: '32 32 448 448', star: '40 24 432 432',
  triangle: '64 64 384 384',
});
const TAU = Math.PI * 2;
const clamp = (v, lo = 0, hi = 1) => Math.max(lo, Math.min(hi, v));
const smooth = v => { v = clamp(v); return v * v * (3 - 2 * v); };
const windowAt = (t, from, to, ramp = .25) => smooth((t - from) / ramp) * smooth((to - t) / ramp);
const pulse = (t, center, width) => Math.abs(t - center) < width / 2 ? (1 + Math.cos(TAU * (t - center) / width)) / 2 : 0;
const blinkAt = (t, events) => Math.max(0, ...events.map(([at, width]) => pulse(t, at, width)));
const lerp = (a, b, t) => a + (b - a) * t;

function roundedPolygon(vertices, rounding = .24, steps = 7) {
  const out = [];
  for (let i = 0; i < vertices.length; i++) {
    const v = vertices[i], p = vertices[(i - 1 + vertices.length) % vertices.length], n = vertices[(i + 1) % vertices.length];
    const a = [lerp(v[0], p[0], rounding), lerp(v[1], p[1], rounding)];
    const b = [lerp(v[0], n[0], rounding), lerp(v[1], n[1], rounding)];
    for (let j = 0; j <= steps; j++) {
      const u = j / steps;
      out.push([(1-u)**2*a[0]+2*u*(1-u)*v[0]+u*u*b[0], (1-u)**2*a[1]+2*u*(1-u)*v[1]+u*u*b[1]]);
    }
  }
  return out;
}
const pebble = roundedPolygon([[-104,-175],[77,-172],[176,-66],[161,101],[33,177],[-126,130],[-183,-29]]);
const triangle = roundedPolygon([[0,-191],[186,145],[-186,145]], .18, 14);
const star = roundedPolygon(Array.from({length:10}, (_, i) => {
  const a=-Math.PI/2+i*TAU/10, r=i%2 ? 112 : 192;
  return [Math.cos(a)*r, Math.sin(a)*r];
}), .24, 6);

function cloudBody() {
  const out=[];
  const segments=[
    [[-178,41],[-213,-9],[-168,-67],[-119,-56]],
    [[-119,-56],[-123,-136],[-30,-164],[18,-110]],
    [[18,-110],[66,-161],[144,-113],[142,-61]],
    [[142,-61],[207,-43],[221,55],[164,92]],
    [[164,92],[110,139],[-115,145],[-169,88]],
    [[-169,88],[-182,75],[-184,58],[-178,41]],
  ];
  for(const [a,b,c,d] of segments) for(let i=0;i<15;i++) {
    const u=i/15, v=1-u;
    out.push([v*v*v*a[0]+3*v*v*u*b[0]+3*v*u*u*c[0]+u*u*u*d[0],v*v*v*a[1]+3*v*v*u*b[1]+3*v*u*u*c[1]+u*u*u*d[1]]);
  }
  return out;
}
const cloud=cloudBody();
function bodyPoints(shape, phase) {
  if(shape==='pebble') return pebble;
  if(shape==='triangle') return triangle;
  if(shape==='star') return star;
  if(shape==='cloud') return cloud;
  const out=[];
  for(let i=0;i<96;i++) {
    const a=i*TAU/96;
    if(shape==='squircle') {
      const c=Math.cos(a),s=Math.sin(a);
      out.push([174*Math.sign(c)*Math.abs(c)**.53,168*Math.sign(s)*Math.abs(s)**.53]);
    } else if(shape==='droplet') {
      // Pointed crown with one continuous, broad lower belly.
      const s=Math.sin(a), radius=158*(1+.25*s);
      out.push([radius*Math.cos(a), 188*s]);
    } else {
      const r=1+.032*Math.sin(3*a+.28)+.017*Math.cos(5*a-.4)+.006*Math.sin(2*a+phase);
      out.push([184*r*Math.cos(a),180*r*Math.sin(a)]);
    }
  }
  return out;
}
function eyePoints(cx,cy,diameter,open=1,smile=0) {
  const rx=diameter/2, ry=Math.max(2,diameter*open/2);
  // Equal radii when open: a round eye. Lids compress during a blink.
  return Array.from({length:40},(_,i)=>{
    const a=i*TAU/40, x=Math.cos(a)*rx;
    return [cx+x,cy+Math.sin(a)*ry-smile*(1-(x/rx)**2)];
  });
}
function shade(hex, delta) {
  return '#'+[1,3,5].map(i=>Math.round(clamp(parseInt(hex.slice(i,i+2),16)+delta,0,255)).toString(16).padStart(2,'0')).join('');
}
export function avatarFrame(shape='blob',color='ink',seconds=0) {
  shape=validShape(shape)?shape:'blob';
  const base=getColor(color).hex, t=((seconds%6)+6)%6, p=t*TAU/6;
  let rot=0,sx=1,sy=1,dy=0,gx=0,gy=0,faceX=0,faceY=-30,diameter=56,openL=1,openR=1,smile=0;
  const b=Math.sin(p);
  if(shape==='blob') {
    const look=windowAt(t,2.15,3.65,.35),back=windowAt(t,4.9,5.7,.22);
    rot=-4.5+2.2*b+4.1*look; sx=1+.013*b;sy=1+.017*b;dy=3*b;
    faceX=38;faceY=-55;gx=10*look-4*back;gy=-4*look;
    openL=openR=1-blinkAt(t,[[1.26,.24],[1.62,.21],[4.5,.25]]);
  } else if(shape==='pebble') {
    const l=windowAt(t,.4,1.65,.3),r=windowAt(t,3.2,4.35,.3),u=(t-2.12)/.86;
    const jump=u>0&&u<1?Math.sin(Math.PI*u)**2:0,squash=.065*pulse(t,2.04,.32)+.055*pulse(t,3.03,.28);
    rot=3.5+3.1*b-3.8*l+4*r;sx=1+.014*b+squash*.7-jump*.018;sy=1+.014*b-squash+jump*.035;dy=2*b-23*jump;
    faceX=24;faceY=-48;gx=-11*l+9*r;gy=-3*jump+2*l;
    openL=1-blinkAt(t,[[.98,.23],[4.95,.24]]);openR=Math.min(openL,1-pulse(t,3.76,.38));
  } else if(shape==='squircle') {
    const think=windowAt(t,2.05,3.3,.4),look=windowAt(t,3.8,5.25,.35);
    rot=-2+5*look;sx=1+.006*b;sy=1+.008*b;dy=1.5*b;
    gx=6*look;gy=5*think;faceY=-25;
    openL=openR=1-.65*think-blinkAt(t,[[.8,.25],[4.95,.23]])*(1-.65*think);smile=1.8*think;
  } else if(shape==='droplet') {
    const shy=windowAt(t,1.35,3.55,.45),peek=windowAt(t,3.9,5.35,.3);
    rot=-5-7*shy+4*peek;dy=4*b+4*shy;sx=1+.01*b;sy=1+.018*b;
    faceY=15;faceX=-8;gx=-11*shy+7*peek;gy=4*shy;diameter=55;
    openL=1-blinkAt(t,[[.75,.3],[3.3,.36]]);openR=Math.min(openL,1-pulse(t,4.65,.34));
  } else if(shape==='cloud') {
    const happy=windowAt(t,2.15,3.3,.3);
    rot=2.2*Math.sin(p);dy=8*Math.sin(p)+3*Math.sin(2*p);sx=1+.015*b;sy=1+.01*b;
    faceY=9;diameter=55;gx=7*Math.sin(p);gy=-2;
    openL=openR=(1-.78*happy)*(1-blinkAt(t,[[1.05,.25],[4.8,.25]]));smile=8*happy;
  } else if(shape==='star') {
    const u=(t-1.8)/1.18,jump=u>0&&u<1?Math.sin(Math.PI*u)**2:0,anticipate=pulse(t,1.69,.34),land=pulse(t,3.05,.3);
    rot=6*Math.sin(p)+11*jump*Math.sin((t-1.8)*TAU/1.18);dy=-31*jump+3*b;
    sx=1+anticipate*.05+land*.04-jump*.02;sy=1-anticipate*.07-land*.055+jump*.05;
    faceY=0;diameter=58;gx=8*Math.sin(p);gy=-6*jump;
    openL=openR=1-blinkAt(t,[[.6,.18],[.88,.17],[4.4,.22]]);
  } else {
    const nod=4*pulse(t,2.1,.52)+3*pulse(t,2.83,.48),look=windowAt(t,3.6,5.3,.5);
    rot=-2+3*look;dy=nod+1.5*b;sx=1+.005*b;sy=1+.008*b;
    faceY=20;diameter=54;gx=8*look;gy=nod*.8;
    openL=openR=1-blinkAt(t,[[1,.32],[4.7,.36]]);
  }
  const angle=rot*Math.PI/180, tx=points=>points.map(([x,y])=>{
    x*=sx;y*=sy;return [256+x*Math.cos(angle)-y*Math.sin(angle),264+dy+x*Math.sin(angle)+y*Math.cos(angle)];
  });
  const body=tx(bodyPoints(shape,p));
  // 100 px between eye centers (v2 was 71–73): visibly wider spacing.
  const eyes=[tx(eyePoints(faceX-50+gx,faceY+gy,diameter,clamp(openL),smile)),tx(eyePoints(faceX+50+gx,faceY-3+gy,diameter,clamp(openR),smile))];
  const facets=shape==='pebble'?[
    {points:tx([[-240,-210],[15,-210],[-33,6],[-230,72]]),fill:shade(base,-8)},
    {points:tx([[120,-220],[240,-150],[250,220],[86,220],[40,28]]),fill:shade(base,8)},
  ]:[];
  return {shape,color:getColor(color).id,base,outline:shade(base,base==='#252830'?24:-18),body,eyes,facets};
}
export const pathData=points=>'M'+points.map(([x,y])=>`${x.toFixed(2)},${y.toFixed(2)}`).join('L')+'Z';

export function avatarUrl(shape,color='ink') {
  return validShape(shape)?`/expert-avatars/v1/${shape}-${getColor(color).id}.svg`:null;
}
export function parseAvatarUrl(url) {
  if(typeof url!=='string') return null;
  const match=url.match(/^\/expert-avatars\/v1\/([a-z]+)-([a-z]+)\.svg(?:[?#].*)?$/);
  return match&&validShape(match[1])&&validColor(match[2])?{shape:match[1],color:match[2]}:null;
}
function luminance(hex) {
  const a=[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4);
  return a[0]*.2126+a[1]*.7152+a[2]*.0722;
}
export function contrast(a,b) { const x=luminance(a),y=luminance(b);return(Math.max(x,y)+.05)/(Math.min(x,y)+.05); }
export function bubbleStyle(color='ink') {
  const hex=getColor(color).hex,dark='#0B101B';
  const foreground=contrast(hex,'#FFFFFF')>=contrast(hex,dark)?'#FFFFFF':dark;
  return {backgroundColor:hex,color:foreground,'--expert-bubble-bg':hex,'--expert-bubble-fg':foreground};
}

export function createExpertAvatars({React}) {
  const h=React.createElement;
  // One clock for all visible avatars, capped at 25 fps. Unmounted/hidden views
  // unsubscribe; reduced-motion users receive the exact static initial pose.
  const listeners=new Set();let raf=0,last=0;
  function tick(now) {
    if(now-last>=40) {last=now;for(const cb of listeners) cb(now/1000);}
    raf=listeners.size&&!document.hidden?requestAnimationFrame(tick):0;
  }
  function start() {if(!raf&&listeners.size&&!document.hidden) raf=requestAnimationFrame(tick);}
  function subscribe(cb) {
    listeners.add(cb);start();
    return()=>{listeners.delete(cb);if(!listeners.size&&raf){cancelAnimationFrame(raf);raf=0;}};
  }
  if(typeof document!=='undefined') document.addEventListener('visibilitychange',()=>{
    if(document.hidden&&raf){cancelAnimationFrame(raf);raf=0;}else start();
  });
  function Avatar({shape='blob',color='ink',size=32,className,style,static:still=false,title,...rest}) {
    const [time,setTime]=React.useState(0),ref=React.useRef(null),id=React.useId().replace(/:/g,'');
    React.useEffect(()=>{
      const media=window.matchMedia('(prefers-reduced-motion: reduce)');
      let off=()=>{},visible=true;
      const update=()=>{off();off=()=>{};if(!still&&!media.matches&&visible)off=subscribe(setTime);else setTime(0);};
      const observer=typeof IntersectionObserver==='function'?new IntersectionObserver(([entry])=>{visible=entry.isIntersecting;update();}):null;
      if(ref.current)observer?.observe(ref.current);
      media.addEventListener('change',update);update();
      return()=>{off();observer?.disconnect();media.removeEventListener('change',update);};
    },[shape,still]);
    const f=avatarFrame(shape,color,time),clip=`oa-${id}`;
    const name=SHAPES.find(x=>x.id===f.shape)?.name||'软团';
    return h('svg',{ref,width:size,height:size,viewBox:VIEWBOXES[f.shape],className,
      style:{display:'inline-block',width:size,height:size,flexShrink:0,verticalAlign:'middle',overflow:'visible',...style},
      role:'img','aria-label':title||`${name} · ${getColor(color).name}`,focusable:'false',...rest},
      h('defs',null,h('clipPath',{id:clip},h('path',{d:pathData(f.body)}))),
      h('path',{d:pathData(f.body),fill:f.base,stroke:f.outline,strokeWidth:1.2,strokeLinejoin:'round'}),
      ...f.facets.map((part,i)=>h('path',{key:`facet${i}`,d:pathData(part.points),fill:part.fill,clipPath:`url(#${clip})`})),
      ...f.eyes.map((points,i)=>h('path',{key:`eye${i}`,d:pathData(points),fill:'#FFFDF7'})));
  }
  const MemoAvatar=React.memo(Avatar);
  const renderAvatar=props=>h(MemoAvatar,props);
  function ShapeColorPicker({shape,color,onShapeChange,onColorChange,disabled=false}) {
    const selectedColor=getColor(color);
    return h('div',{className:'oa-picker'},
      h('div',{className:'oa-picker-label'},'头像形状',h('span',null,'每种形状都有自己的神态和动作')),
      h('div',{className:'oa-shapes','aria-label':'头像形状'},...SHAPES.map(s=>h('button',{
        key:s.id,type:'button',className:'oa-shape','aria-pressed':shape===s.id,disabled,
        title:`${s.name} · ${s.mood} · ${s.motion}`,onClick:()=>onShapeChange?.(s.id)},
        renderAvatar({shape:s.id,color:selectedColor.id,size:80}),
        h('span',{className:'oa-shape-name'},s.name),h('span',{className:'oa-shape-mood'},s.mood)))),
      h('div',{className:'oa-picker-label'},'头像颜色',h('span',null,selectedColor.name)),
      h('div',{className:'oa-colors','aria-label':'头像颜色'},...COLORS.map(c=>h('button',{
        key:c.id,type:'button',className:'oa-color','aria-label':`${c.name} ${c.hex}`,'aria-pressed':selectedColor.id===c.id,disabled,
        title:c.name,onClick:()=>{if(!validShape(shape))onShapeChange?.('blob');onColorChange?.(c.id);}},
        h('span',{className:'oa-swatch',style:{backgroundColor:c.hex,color:bubbleStyle(c.id).color}},selectedColor.id===c.id?'✓':''),
        h('span',null,c.name)))));
  }
  function Picker({shape,color,onChange,...rest}) {
    return h(ShapeColorPicker,{shape,color,...rest,onShapeChange:s=>onChange?.({shape:s,color:getColor(color).id}),
      onColorChange:c=>onChange?.({shape:validShape(shape)?shape:'blob',color:c})});
  }
  return {Avatar:MemoAvatar,Picker,ShapeColorPicker,renderAvatar,SHAPES,COLORS,parseAvatarUrl,avatarUrl,bubbleStyle,validShape,validColor};
}

export function animatedSvg(shape,color) {
  const count=75,frames=Array.from({length:count+1},(_,i)=>avatarFrame(shape,color,i*6/count));
  const a=frames[0],timing='dur="6s" repeatCount="indefinite" calcMode="linear"';
  const animation=values=>`<animate attributeName="d" values="${values.join(';')}" ${timing}/>`;
  const animated=(name,selector,fill,extra='')=>`<path id="${name}" d="${pathData(selector(a))}" fill="${fill}" ${extra}>${animation(frames.map(f=>pathData(selector(f))))}</path>`;
  const staticParts=()=>`<path d="${pathData(a.body)}" fill="${a.base}" stroke="${a.outline}" stroke-width="1.2"/>`+
    a.facets.map(part=>`<path d="${pathData(part.points)}" fill="${part.fill}" clip-path="url(#still-clip)"/>`).join('')+
    a.eyes.map(eye=>`<path d="${pathData(eye)}" fill="#FFFDF7"/>`).join('');
  return `<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="${VIEWBOXES[shape]||VIEWBOXES.blob}" role="img" aria-label="${SHAPES.find(x=>x.id===shape)?.name} · ${getColor(color).name}">`+
    `<style>.still{display:none}@media(prefers-reduced-motion:reduce){.motion{display:none}.still{display:inline}}</style>`+
    `<defs><clipPath id="clip">${animated('clip-body',f=>f.body,'#fff')}</clipPath><clipPath id="still-clip"><path d="${pathData(a.body)}"/></clipPath></defs>`+
    `<g class="motion">${animated('body',f=>f.body,a.base,`stroke="${a.outline}" stroke-width="1.2" stroke-linejoin="round"`)}${a.facets.map((part,i)=>animated(`facet${i}`,f=>f.facets[i].points,part.fill,'clip-path="url(#clip)"')).join('')}${[0,1].map(i=>animated(`eye${i}`,f=>f.eyes[i],'#FFFDF7')).join('')}</g>`+
    `<g class="still">${staticParts()}</g></svg>`;
}
