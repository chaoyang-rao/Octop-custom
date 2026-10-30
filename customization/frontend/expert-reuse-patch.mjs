import fs from 'node:fs';
function once(source,before,after){const n=source.split(before).length-1;if(n!==1)throw Error(`Expected one expert-reuse point, got ${n}: ${before.slice(0,90)}`);return source.replace(before,after)}
export function patchExpertReuse(source){
 source='import {createExpertReuseDialogs} from "./expert-reuse.js";\nconst ExpertReuseDialogs=createExpertReuseDialogs({React:reactExports,Modal,Input,Select,Alert,useTranslation,useAgent,notify:message,api:{copyExpert:(id,name)=>request(`/agents/${encodeURIComponent(id)}/copy`,{method:"POST",body:JSON.stringify(name?{name}:{})}),reuseCli:(id,agent_ids)=>request(`/agents/${encodeURIComponent(id)}/cli/reuse`,{method:"POST",body:JSON.stringify({agent_ids})})}});\n'+source;
 source=once(source,'function AgentMoreActions({buttonClassName,','function AgentMoreActions({agent,onCopied,buttonClassName,');
 const a=source.indexOf('function AgentMoreActions('),b=source.indexOf('const STATE_META=',a);if(a<0||b<a)throw Error('Missing expert menu section');
 let menu=source.slice(a,b);
 menu=once(menu,'return jsxRuntimeExports.jsx(Dropdown,{menu:{items},','return jsxRuntimeExports.jsx(ExpertReuseDialogs,{agent,onCopied,children:actions=>jsxRuntimeExports.jsx(Dropdown,{menu:{items:[...items,...(agent.is_owner&&!agent.bridge?[{type:"divider"},{key:"copy-expert",icon:jsxRuntimeExports.jsx(Copy,{size:14}),label:t("experts.reuse.copyTitle"),onClick:actions.copy},{key:"reuse-cli",icon:jsxRuntimeExports.jsx(Wrench,{size:14}),label:t("experts.reuse.cliTitle"),onClick:actions.cli}]:[])]},');
 if(!menu.endsWith('})}'))throw Error('Unexpected expert menu ending');
 menu=menu.slice(0,-1)+'})}';
 source=source.slice(0,a)+menu+source.slice(b);
 return once(source,'jsxRuntimeExports.jsx(AgentMoreActions,{buttonClassName:','jsxRuntimeExports.jsx(AgentMoreActions,{agent,onCopied:onPollSettled,buttonClassName:');
}
export function patchExpertReuseLocale(source){
 const lang=source.includes('"teamBadge":"团队"')?'zh':'en';
 const json=JSON.parse(fs.readFileSync(new URL(`../../dashboard/src/locales/${lang}.json`,import.meta.url),'utf8'));
 if(!source.includes('experts='))throw Error('Missing experts locale namespace');
 return source+'\nObject.assign(experts,{reuse:'+JSON.stringify(json.experts.reuse)+'});\n';
}

export function patchExpertReuseTable(source){return once(source,'jsxRuntimeExports.jsx(AgentMoreActions,{buttonClassName:expertStyles.tableActionBtn,','jsxRuntimeExports.jsx(AgentMoreActions,{agent:row,buttonClassName:expertStyles.tableActionBtn,')}
