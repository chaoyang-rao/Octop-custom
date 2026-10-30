function once(source,before,after) {
  const count=source.split(before).length-1;
  if(count!==1)throw Error(`Expected one team-experience point, got ${count}: ${before.slice(0,100)}`);
  return source.replace(before,after);
}
function section(source,start,end,transform) {
  const a=source.indexOf(start),b=source.indexOf(end,a+start.length);
  if(a<0||b<=a)throw Error(`Missing section ${start}`);
  return source.slice(0,a)+transform(source.slice(a,b))+source.slice(b);
}
export function patchExpertPresentation(source) {
  source='import {createExpertPresentation} from "./expert-presentation.js";\n'+source;
  source=once(source,'const expertAvatarUi=createExpertAvatars({React:reactExports});','const expertAvatarUi=createExpertAvatars({React:reactExports}),expertPresentation=createExpertPresentation({React:reactExports,avatars:expertAvatarUi,useAgent});');
  source=section(source,'function teamPortraitUrl(','function ',part=>{const open=part.indexOf('{'),close=part.indexOf('}',open);return part.slice(0,open+1)+'return TEAM_AVATAR_URL'+part.slice(close)});
  for(const name of ['ExpertIcon','ExpertAgentAvatar']) {
    const a=source.indexOf(`function ${name}(props){`),b=source.indexOf(`function Legacy${name}(`,a);
    if(a<0||b<a)throw Error('Expert portrait wrapper changed');
    source=source.slice(0,a)+`function ${name}(props){return jsxRuntimeExports.jsx(expertPresentation.ExpertPortrait,props)}`+source.slice(b);
  }
  const marker='jsxRuntimeExports.jsx(ExpertIcon,{iconUrl:agent.icon_url,iconName:agent.icon_name,size:48})';
  if(source.split(marker).length-1!==3)throw Error('Three nav portrait sites expected');
  source=source.replaceAll(marker,marker.replace('{iconUrl:','{agent,iconUrl:'));
  source=section(source,'function useHiddenSharedExperts(){','const qqIcon=',part=>part
    .replace('!isSharedExpertViewer(agent)||keep.has(agent.agent_id)?!0:!hiddenIds.has(agent.agent_id)','keep.has(agent.agent_id)?!0:!hiddenIds.has(agent.agent_id)')
    .replace('isSharedExpertViewer(agent)&&hiddenIds.has(agent.agent_id)','hiddenIds.has(agent.agent_id)')
    .replace('canHide=reactExports.useCallback(agent=>isSharedExpertViewer(agent),[])','canHide=reactExports.useCallback(agent=>!!agent.agent_id,[])'));
  source=once(source,'keepAgentIds:activeAgentId2?[activeAgentId2]:[]','keepAgentIds:[]');
  source=section(source,'function MinimalAgentSessionNav(','const edge=',part=>{
    part=once(part,'}){const{t}=useTranslation()', '}){const visibility=useHiddenSharedExperts(),hiddenAgents=visibility.pickHidden(agents);const{t}=useTranslation()');
    part=once(part,'sortExpertsByPin(agents,pinnedIds)','sortExpertsByPin(visibility.filterVisible(agents),pinnedIds)');
    part=once(part,'[agents,pinnedIds,navScope]','[agents,pinnedIds,navScope,visibility.filterVisible]');
    part=once(part,'jsxRuntimeExports.jsx(ChatNavScopeTabs,{value:navScope,onChange:setNavScope})','jsxRuntimeExports.jsx(expertPresentation.HiddenRestore,{agents:hiddenAgents,onRestore:visibility.unhide,label:t("chat.expertListHidden",{count:hiddenAgents.length})}),jsxRuntimeExports.jsx(ChatNavScopeTabs,{value:navScope,onChange:setNavScope})');
    part=once(part,'variant:"minimal",pinned:isPinned(agent.agent_id)','variant:"minimal",onHide:()=>visibility.hide(agent.agent_id),pinned:isPinned(agent.agent_id)');
    return part;
  });
  source=once(source,'function ExpertNavActions({variant,pinned,onTogglePin,onNewChat}){',`function ExpertNavActions(props){const{t}=useTranslation();return jsxRuntimeExports.jsxs("span",{className:chatStyles.expertNavActions,children:[jsxRuntimeExports.jsx(LegacyExpertNavActions,props),props.onHide?jsxRuntimeExports.jsx("button",{type:"button",className:chatStyles.agentHideBtn,"aria-label":t("chat.expertHide"),title:t("chat.expertHide"),onClick:e=>{e.stopPropagation();props.onHide()},children:jsxRuntimeExports.jsx(EyeOff,{size:14})}):null]})}function LegacyExpertNavActions({variant,pinned,onTogglePin,onNewChat}){`);
  return source;
}
export function patchRandomAvatarCreate(source) {
  source='import {randomAvatar} from "./expert-presentation.js";import {createExpertWorkStatus} from "./expert-work-status.js";\nconst TeamWorkStatus=createExpertWorkStatus({React:reactExports,useTranslation});\n'+source;
  source=once(source,'setAvatarShape(source.expert.avatar_shape??"blob"),setAvatarColor(source.expert.avatar_color??"ink")','(()=>{const next=randomAvatar();setAvatarShape(next.shape);setAvatarColor(next.color)})()');
  source=source.replace('createAvatarSettings({React:reactExports,avatars:expertAvatarUi})','createAvatarSettings({React:reactExports,avatars:expertAvatarUi,useTranslation})');
  source=once(source,'jsxRuntimeExports.jsx(ExpertIcon,{iconUrl:teamPortraitUrl(agent.icon_url),iconName:TEAM_ICON_NAME,size:40})','jsxRuntimeExports.jsx(ExpertIcon,{agent,iconUrl:"/experts/avatars/team-host.svg",iconName:TEAM_ICON_NAME,size:48})');
  source=section(source,'TeamCard=reactExports.memo(function(','function ',part=>once(part,'jsxRuntimeExports.jsx(RemoteExpertHint,{agent}),','jsxRuntimeExports.jsx(RemoteExpertHint,{agent}),jsxRuntimeExports.jsx(TeamWorkStatus,{agent:{...agent,state:localState}}),'));
  return source;
}
export function patchAvatarEdit(source) {
  return source.replace('createAvatarSettings({React:reactExports,avatars:expertAvatarUi})','createAvatarSettings({React:reactExports,avatars:expertAvatarUi,useTranslation})');
}
export function patchManualProcessDetails(source) {
  source=once(source,'defaultValue:isTeam,listenStorageChange:!0','defaultValue:!0,listenStorageChange:!0');
  source=once(source,'[collapseThinking]=useCollapseThinking(isTeam),[expanded,setExpanded]=reactExports.useState(isStreaming&&!collapseThinking),prevStreaming=reactExports.useRef(isStreaming),prevCollapseThinking=reactExports.useRef(collapseThinking),','[expanded,setExpanded]=reactExports.useState(!1),');
  source=once(source,'if(reactExports.useEffect(()=>{if(prevStreaming.current===isStreaming&&prevCollapseThinking.current===collapseThinking)return;const wasStreaming=prevStreaming.current;if(prevStreaming.current=isStreaming,prevCollapseThinking.current=collapseThinking,isStreaming){setExpanded(!collapseThinking);return}(wasStreaming||collapseThinking)&&setExpanded(!1)},[isStreaming,collapseThinking]),toolCount===0&&thinkingCount===0)', 'if(toolCount===0&&thinkingCount===0)');
  source=once(source,'()=>partitionPinnedTools(split),[split,rendererVersion]','()=>({pinned:[],folded:split}),[split,rendererVersion]');
  source=once(source,'function turnHasProcessSummary(split){return hasFoldContent(partitionPinnedTools(split).folded)}','function turnHasProcessSummary(split){return hasFoldContent(split)}');
  source=once(source,'className:`${chatStyles.assistantText} ${groupCls}`,children:[','className:`${chatStyles.assistantText} ${groupCls}`,children:[isTeamRoom?jsxRuntimeExports.jsx("span",{className:"octop-member-name",children:avatarTooltip||(expert==null?void 0:expert.name)||speakerId||(activeAgent==null?void 0:activeAgent.name)}):null,');
  return source;
}
export function patchProcessPreferenceMenu(source) {
  return section(source,'function ChatTitleBar(','function ',part=>{
    const a=part.indexOf('{key:"collapse-thinking"'),b=part.indexOf('{key:"pin"',a);
    if(a<0||b<a)throw Error('Process preference menu changed');
    part=part.slice(0,a)+part.slice(b);
    part=once(part,'[collapseThinking,setCollapseThinking]=useCollapseThinking(isTeam),','');
    return once(part,'[collapseThinking,setCollapseThinking,session.id,','[session.id,');
  });
}
export function patchExperienceLocale(source) {
  if(source.includes('隐藏共享专家'))return source.replace('隐藏共享专家','隐藏专家').replace('暂无已隐藏的共享专家','暂无已隐藏的专家');
  return once(source,'Hide shared expert','Hide expert').replace('No hidden shared experts','No hidden experts');
}

export function patchToolbarGlyphs(source) {
  return once(source,'className:`${chatStyles.actionsRow}${','"data-octop-composer-tools":"",className:`${chatStyles.actionsRow}${');
}
