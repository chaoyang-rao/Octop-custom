import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createRequire} from 'node:module';
import {randomAvatar,createExpertPresentation} from '../packages/octop/dashboard/assets/expert-presentation.js';
import {createExpertAvatars} from '../packages/octop/dashboard/assets/expert-avatars.js';
import {createAccountAvatar} from '../packages/octop/dashboard/assets/account-avatar.js';
import {createAvatarSettings} from '../packages/octop/dashboard/assets/expert-avatar-integration.js';
const require=createRequire(new URL('../../dashboard/package.json',import.meta.url));
const {JSDOM}=require('jsdom');const dom=new JSDOM('<!doctype html><body></body>',{url:'http://localhost/'});
for(const key of ['window','document','HTMLElement','Element','Node','MutationObserver','localStorage'])globalThis[key]=dom.window[key];
Object.defineProperty(globalThis,'navigator',{value:dom.window.navigator,configurable:true});
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
window.matchMedia=()=>({matches:true,addEventListener(){},removeEventListener(){}});
globalThis.requestAnimationFrame=()=>1;globalThis.cancelAnimationFrame=()=>{};
const React=require('react'),{act}=React,{createRoot}=require('react-dom/client');const h=React.createElement;
const avatars=createExpertAvatars({React});
const presentation=createExpertPresentation({React,avatars,useAgent:()=>({agents:[]})});
const styles=new Proxy({},{get:(_,key)=>String(key)});const Empty=()=>null;
const t=(key,opts)=>opts?.defaultValue||key;
async function mount(Component,props={}){const el=document.createElement('div');document.body.append(el);const root=createRoot(el);await act(()=>root.render(h(Component,props)));return{el,render:async p=>act(()=>root.render(h(Component,p))),close:async()=>{await act(()=>root.unmount());el.remove()}}}
let previous;
for(let i=0;i<200;i++){const value=randomAvatar(()=>i%2?0.999:0);assert.ok(avatars.SHAPES.some(s=>s.id===value.shape));assert.ok(avatars.COLORS.some(c=>c.id===value.color));if(previous){assert.notEqual(value.shape,previous.shape);assert.notEqual(value.color,previous.color)}previous=value}
for(const iconUrl of ['/old-photo.png','/experts/avatars/cpu.svg',null]){
 const app=await mount(presentation.ExpertPortrait,{iconUrl,iconName:'cpu'});assert.equal(app.el.querySelectorAll('img').length,0);assert.equal(app.el.querySelectorAll('svg').length,1);await app.close();
}
const metadataAvatar=await mount(presentation.ExpertPortrait,{agent:{agent_id:'remote',avatar_shape:'triangle',avatar_color:'rose'},iconUrl:'https://remote.invalid/old.png'});
assert.match(metadataAvatar.el.querySelector('svg').getAttribute('aria-label'),/三角/);assert.match(metadataAvatar.el.querySelector('svg').getAttribute('aria-label'),/莓粉/);await metadataAvatar.close();
const team=await mount(presentation.ExpertPortrait,{agent:{kind:'team',member_ids:['a','b','c']},size:48});
assert.equal(team.el.querySelectorAll('.octop-team-face').length,3);assert.equal(team.el.querySelectorAll('svg').length,3);assert.equal(team.el.querySelectorAll('img').length,0);await team.close();
const Account=createAccountAvatar({React,ProfileAvatar:props=>h('img',{src:props.url,'data-kind':props.kind})});
const account=await mount(Account,{user:{display_name:'Account',avatar_url:'/my-login-photo.png'}});assert.equal(account.el.querySelector('img').getAttribute('src'),'/my-login-photo.png');await account.close();
const Picker=createAvatarSettings({React,avatars,useTranslation:()=>({t,i18n:{language:'en'}})});
const picker=await mount(Picker,{shape:'cloud',color:'jade',onShapeChange(){},onColorChange(){}});assert.equal(picker.el.querySelectorAll('.oa-shape').length,7);assert.equal(picker.el.querySelectorAll('.oa-color').length,7);assert.equal(picker.el.querySelectorAll('details,input[type=file]').length,0);assert.match(picker.el.textContent,/Randomize/);await picker.close();
const countProcessStats=split=>({toolCount:split.tools.length,thinkingCount:split.thinkings.length});
function compile(file,resolver){const module={exports:{}};const code=require('esbuild').transformSync(fs.readFileSync(new URL(file,import.meta.url),'utf8'),{loader:'tsx',format:'cjs',jsx:'automatic',target:'es2022'}).code;new Function('module','exports','require',code)(module,module.exports,resolver);return module.exports}
function processDependency(name){if(name==='react')return React;if(name==='react/jsx-runtime')return require(name);if(name==='react-i18next')return{useTranslation:()=>({t})};if(name==='lucide-react')return{ChevronRight:Empty,Scale:Empty};if(name.endsWith('messageContent'))return{countProcessStats};if(name.endsWith('MessageBubble'))return{ToolDetailsInline:()=>h('pre',null,'tool output')};if(name.endsWith('LazyMarkdown'))return{__esModule:true,default:({content})=>h('pre',null,content)};if(name.endsWith('.less'))return{__esModule:true,default:styles};throw Error(name)}
const SourceProcess=compile('../../dashboard/src/pages/Chat/components/AssistantProcessSummary.tsx',processDependency).default;
const release=JSON.parse(fs.readFileSync(new URL('avatar-asset-release.json',import.meta.url)));
const frozen=fs.readFileSync(new URL(`../packages/octop/dashboard/assets/index.Bexwf9h5.${release.release}.js`,import.meta.url),'utf8');
const a=frozen.indexOf('function AssistantProcessSummary('),b=frozen.indexOf('const AssistantProcessSummary$1=',a);
const FrozenProcess=new Function('deps',`with(deps){${frozen.slice(a,b)}return AssistantProcessSummary}`)({reactExports:React,jsxRuntimeExports:require('react/jsx-runtime'),useTranslation:()=>({t}),countProcessStats,resolveLiveProcessHint:()=>null,chatStyles:styles,ChevronRight:Empty,DecisionToolRow:Empty,ToolDetailsInline:()=>h('pre',null,'tool output'),LazyMarkdown:({content})=>h('pre',null,content)});
for(const Process of [SourceProcess,FrozenProcess]){
 const item={messageId:'think',content:'private detailed reasoning',isStreaming:true};const split={tools:[],thinkings:[item],processSteps:[{kind:'thinking',item}],answerMessage:null};
 localStorage.setItem('octop:collapse-thinking','false');
 const app=await mount(Process,{split,isStreaming:true});assert.equal(app.el.querySelector('button').getAttribute('aria-expanded'),'false');assert.equal(app.el.querySelector('pre'),null);
 await app.render({split:{...split},isStreaming:true});assert.equal(app.el.querySelector('pre'),null);
 await act(()=>app.el.querySelector('button').click());assert.match(app.el.querySelector('pre').textContent,/private detailed reasoning/);
 await app.render({split,isStreaming:false});assert.ok(app.el.querySelector('pre'),'manual expansion survives completion');
 await act(()=>app.el.querySelector('button').click());await app.render({split,isStreaming:true});assert.equal(app.el.querySelector('pre'),null,'streaming cannot reopen a manually collapsed panel');await app.close();
}
let userId=1,visibility;
const prefs=compile('../../dashboard/src/pages/Chat/utils/hiddenExpertsPrefs.ts',()=>{throw Error('pure prefs require no dependencies')});
const hidden=compile('../../dashboard/src/pages/Chat/hooks/useHiddenSharedExperts.ts',name=>name==='react'?React:name.endsWith('useCurrentUser')?{useCurrentUser:()=>({id:userId})}:name.endsWith('hiddenExpertsPrefs')?prefs:(()=>{throw Error(name)})());
const agents=[{agent_id:'owned',name:'Owned',is_owner:true},{agent_id:'shared',name:'Shared',is_owner:false,is_shared:true}];
function HiddenHarness(){visibility=hidden.useHiddenSharedExperts();return h('div',null,visibility.filterVisible(agents).map(a=>a.name).join(','))}
localStorage.clear();const list=await mount(HiddenHarness);assert.equal(visibility.canHide(agents[0]),true);await act(()=>visibility.hide('owned'));assert.equal(list.el.textContent,'Shared');assert.equal(visibility.pickHidden(agents)[0].agent_id,'owned');await list.close();
const reload=await mount(HiddenHarness);assert.equal(reload.el.textContent,'Shared');userId=2;await reload.render({});assert.equal(reload.el.textContent,'Owned,Shared');userId=1;await reload.render({});await act(()=>visibility.unhide('owned'));assert.equal(reload.el.textContent,'Owned,Shared');await reload.close();
assert.ok(frozen.includes('className:"octop-member-name"'),'group replies visibly identify speakers');
assert.ok(frozen.includes('()=>({pinned:[],folded:split})'),'rich tools stay behind the same manual disclosure');
console.log('PASS varied random creation, no legacy expert images, unframed team collage, preserved login image, geometry-only picker, real source/frozen manual streaming disclosures, owned/shared per-account hide/restore, member labels and folded rich tools');
