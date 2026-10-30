import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createRequire} from 'node:module';
import {createExpertReuseDialogs as Frozen} from '../packages/octop/dashboard/assets/expert-reuse.js';
import {createExpertReuseDialogs as Source} from '../../dashboard/src/components/expertReuse/dialogs.mjs';
const require=createRequire(new URL('../../dashboard/package.json',import.meta.url));
const {JSDOM}=require('jsdom'),dom=new JSDOM('<body></body>',{url:'http://localhost'});
for(const k of ['window','document','HTMLElement','Element','Node','MutationObserver'])globalThis[k]=dom.window[k];
Object.defineProperty(globalThis,'navigator',{value:dom.window.navigator,configurable:true});
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const React=require('react'),{act}=React,{createRoot}=require('react-dom/client'),{fireEvent}=require('@testing-library/dom'),h=React.createElement;
const Input=props=>h('input',{...props});
const Select=({options,value,onChange,disabled})=>h('select',{multiple:true,disabled,value,onChange:event=>onChange([...event.target.selectedOptions].map(o=>o.value))},options.map(o=>h('option',{key:o.value,value:o.value,disabled:o.disabled},o.label)));
const Alert=({message})=>h('p',null,message);
const Modal=props=>props.open?h('div',{role:'dialog'},h('h1',null,props.title),props.children,h('button',{type:'button',onClick:props.onOk,disabled:props.confirmLoading||props.okButtonProps.disabled},'save'),h('button',{type:'button',onClick:props.onCancel,disabled:props.confirmLoading},'cancel')):null;
for(const Factory of [Source,Frozen]){
 let agents=[{agent_id:'source',name:'Source',is_owner:true,config:{acp:{tool_enabled:true}}},{agent_id:'a',name:'Target',is_owner:true,work_status:'idle'},{agent_id:'b',name:'Busy',is_owner:true,work_status:'waiting'},{agent_id:'foreign',name:'Foreign',is_owner:false},{agent_id:'remote',name:'Remote',is_owner:true,bridge:true},{agent_id:'team',name:'Team',is_owner:true,kind:'team'}];
 const calls=[],notices=[];let refreshes=0;
 const Component=Factory({React,Modal,Input,Select,Alert,useTranslation:()=>({t:key=>key}),useAgent:()=>({agents,refresh:async()=>{refreshes++}}),api:{copyExpert:async(...args)=>calls.push(['copy',...args]),reuseCli:async(...args)=>calls.push(['cli',...args])},notify:{success:message=>notices.push(message),error:message=>notices.push(message)}});
 const el=document.createElement('div');document.body.append(el);const root=createRoot(el);
 const render=()=>act(()=>root.render(h(Component,{agent:agents[0]},actions=>h('div',null,h('button',{onClick:actions.copy},'copy'),h('button',{onClick:actions.cli},'cli')))));
 await render();const button=text=>[...el.querySelectorAll('button')].find(b=>b.textContent===text);
 assert.equal(el.querySelector('[role=dialog]'),null);
 await act(()=>button('copy').click());await act(()=>button('cancel').click());assert.equal(calls.length,0);
 await act(()=>button('copy').click());await act(()=>fireEvent.change(el.querySelector('input'),{target:{value:'My copy'}}));await act(async()=>{button('save').click();await Promise.resolve();await Promise.resolve();await Promise.resolve()});
 assert.deepEqual(calls,[['copy','source','My copy']]);assert.equal(refreshes,1);assert.equal(el.querySelector('[role=dialog]'),null);
 await act(()=>button('cli').click());const options=[...el.querySelectorAll('option')];assert.deepEqual(options.map(o=>o.value),['a','b']);assert.equal(options[1].disabled,true);assert.equal(button('save').disabled,true);
 await act(()=>{options[0].selected=true;fireEvent.change(el.querySelector('select'))});await act(async()=>{button('save').click();await Promise.resolve();await Promise.resolve();await Promise.resolve()});assert.deepEqual(calls[1],['cli','source',['a']]);
 await act(()=>button('cli').click());await act(()=>{el.querySelector('option').selected=true;fireEvent.change(el.querySelector('select'))});agents=agents.map(a=>a.agent_id==='a'?{...a,work_status:'working'}:a);await render();assert.equal(button('save').disabled,true);assert.equal(calls.length,2);
 await act(()=>root.unmount());el.remove();
}
const release=JSON.parse(fs.readFileSync(new URL('avatar-asset-release.json',import.meta.url)));
for(const name of [`EditAgentDrawer.w674TDCV.${release.release}.js`,`index.Bxr_iAco.${release.release}.js`])assert.ok(fs.readFileSync(new URL(`../packages/octop/dashboard/assets/${name}`,import.meta.url),'utf8').includes('AgentMoreActions,{agent'));
for(const name of ['zh.D-7HvP3m','en.CaWe8dRV']){const module=await import(new URL(`../packages/octop/dashboard/assets/${name}.${release.release}.js`,import.meta.url));assert.ok(module.default.experts.reuse.copyTitle);assert.ok(module.default.experts.reuse.cliTitle)}
console.log('PASS real source/frozen copy and multi-target CLI dialogs: cancel, names, refresh, owned/local filtering, busy selection, narrow API payloads, both card/table wiring and bilingual labels');
