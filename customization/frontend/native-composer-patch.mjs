function once(source, from, to){const count=source.split(from).length-1;if(count!==1)throw new Error(`Native composer patch expected one anchor, got ${count}: ${from.slice(0,90)}`);return source.replace(from,to);}

export function patchNativeComposer(source){
 const start=source.indexOf('function ChatInputActionsRow('),end=source.indexOf('function previewText(',start);
 if(start<0||end<start)throw new Error('Composer action boundary changed');
 let block=source.slice(start,end);
 block=once(block,'const{t}=useTranslation(),navigate=useNavigate(),','const{t}=useTranslation(),navigate=useNavigate(),nativeCli=useNativeCliPresentation(agentId2),');
 block=once(block,'showModelPicker=!!(availableModels&&availableModels.length>0&&onModelChange)','showModelPicker=!!(!nativeCli&&availableModels&&availableModels.length>0&&onModelChange)');
 const badge='jsxRuntimeExports.jsx(Tooltip,{title:t(nativeCli.canManage?"nativeCli.composerManage":"nativeCli.composerReadOnly"),children:jsxRuntimeExports.jsxs("button",{type:"button",className:"octop-model-shortcut","data-testid":"composer-native-cli",disabled:disabled||!nativeCli.canManage,onClick:()=>navigate("/native-cli?agent="+encodeURIComponent(nativeCli.agentId)),children:[jsxRuntimeExports.jsx(Cpu,{size:16,"aria-hidden":!0}),jsxRuntimeExports.jsx("span",{children:nativeCli.runner+" · "+(nativeCli.modelId||t("nativeCli.composerDefault"))})]})})';
 const anchor='showModelPicker&&jsxRuntimeExports.jsx(Popover,{trigger:"click",placement:"topLeft",arrow:!1,destroyOnHidden:!0,open:modelShortcutOpen,';
 block=once(block,anchor,`nativeCli?${badge}:${anchor}`);
 source=source.slice(0,start)+block+source.slice(end);
 source=once(source,'!showWelcome&&modelsReady&&availableModels.length===0?', '!showWelcome&&modelsReady&&availableModels.length===0&&!nativeCliForChat(activeAgent,agents,false)?');
 source=once(source,'showWelcome&&modelsReady&&availableModels.length===0?', 'showWelcome&&modelsReady&&availableModels.length===0&&!nativeCliForChat(activeAgent,agents,false)?');
 return 'import{nativeCliForChat}from"./native-cli-presentation.js";\nimport{u as useNativeAgentContext,d as useNativeCurrentUser}from"./index.BsYGCvv_.projects-v2.js";\nfunction useNativeCliPresentation(agentId){const{agents}=useNativeAgentContext(),user=useNativeCurrentUser();return nativeCliForChat(agents.find(agent=>agent.agent_id===agentId)||null,agents,user?.role==="admin")}\n'+source;
}
