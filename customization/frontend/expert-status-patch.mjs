/** Expert activity badges and one shared activity refresh loop. */
function once(source, before, after) {
  const count = source.split(before).length - 1;
  if (count !== 1) throw new Error(`Expected one expert status patch point, found ${count}: ${before.slice(0, 100)}`);
  return source.replace(before, after);
}

const HELPERS = 'function invalidateExpertWorkFields(agents){let changed=!1;const next=agents.map(agent=>{if(agent.work_status==="unknown"&&agent.working_count===void 0&&agent.waiting_count===void 0)return agent;return changed=!0,{...agent,work_status:"unknown",working_count:void 0,waiting_count:void 0}});return changed?next:agents}function bridgeWorkFields(agent){if(typeof agent.work_status!=="string"||!["working","waiting","idle","stopped","starting","stopping","failed","unknown"].includes(agent.work_status))return{};const validCount=value=>typeof value==="number"&&Number.isSafeInteger(value)&&value>=0;return{work_status:agent.work_status,...validCount(agent.working_count)?{working_count:agent.working_count}:{},...validCount(agent.waiting_count)?{waiting_count:agent.waiting_count}:{}}}';

export const EXPERT_ACTIVITY_REFRESH_EFFECT = '()=>{let disposed=!1,pending=!1,queued=!1,debounce;const refreshVisible=async()=>{if(disposed||document.visibilityState==="hidden")return;if(pending){queued=!0;return}pending=!0;try{await refresh({silent:!0})}finally{pending=!1,queued&&!disposed&&(queued=!1,schedule())}},schedule=()=>{disposed||(window.clearTimeout(debounce),debounce=window.setTimeout(()=>{refreshVisible()},150))},onVisible=()=>{document.visibilityState==="visible"&&schedule()},interval=window.setInterval(()=>{refreshVisible()},5e3),stopStream=onStreamEvent(schedule),stopSession=onSessionEvent(schedule);return window.addEventListener("focus",schedule),document.addEventListener("visibilitychange",onVisible),()=>{disposed=!0,window.clearInterval(interval),window.clearTimeout(debounce),stopStream(),stopSession(),window.removeEventListener("focus",schedule),document.removeEventListener("visibilitychange",onVisible)}}';

export function patchExpertStatusSource(source) {
  if (source.includes('createExpertWorkStatus')) throw new Error('Expert work status already patched');
  source = 'import {createExpertWorkStatus} from "./expert-work-status.js";\nconst ExpertWorkStatus=createExpertWorkStatus({React:reactExports,useTranslation});\n' + HELPERS + source;
  for (const className of ['agentCardName', 'agentRowName', 'minimalAgentName']) {
    const marker = `jsxRuntimeExports.jsx(ExpertNameLabel,{name:agent.name,className:chatStyles.${className}})`;
    source = once(source, marker, marker + ',jsxRuntimeExports.jsx(ExpertWorkStatus,{agent})');
  }
  source = once(source, 'a.state===b.state&&a.unread_count===b.unread_count',
    'a.state===b.state&&a.work_status===b.work_status&&a.working_count===b.working_count&&a.waiting_count===b.waiting_count&&a.unread_count===b.unread_count');
  source = once(source, 'config:bridgeShadowConfig(agent.config),knowledge_base_ids:',
    'config:bridgeShadowConfig(agent.config),...bridgeWorkFields(agent),knowledge_base_ids:');
  source = once(source, 'catch(err){setError(err instanceof Error?err.message:"Failed to load agents")}finally',
    'catch(err){setError(err instanceof Error?err.message:"Failed to load agents"),setAgents(invalidateExpertWorkFields)}finally');
  source = once(source,
    '()=>{const onFocus=()=>void refresh({silent:!0});return window.addEventListener("focus",onFocus),()=>window.removeEventListener("focus",onFocus)}',
    EXPERT_ACTIVITY_REFRESH_EFFECT);
  return source;
}

export function patchExpertManagementStatus(source) {
  if (source.includes('ExpertManagementWorkStatus')) throw new Error('Expert management work status already patched');
  const start = source.indexOf('AgentCard=reactExports.memo(function(');
  const end = source.indexOf('function EditAgentDrawerBody(', start);
  if (start < 0 || end <= start) throw new Error('Expert management card boundary changed');
  let card = source.slice(start, end);
  card = once(card, 'const{t}=useTranslation(),navigate=useNavigate()', 'const{t,i18n}=useTranslation(),navigate=useNavigate()');
  card = once(card, 'formatAgentState(localState,t)]}),memorySlimming',
    '(localState==="running"?t("chat.expertWorkEnabled",{defaultValue:i18n.language.toLowerCase().startsWith("zh")?"已启用":"Enabled"}):formatAgentState(localState,t))]}),jsxRuntimeExports.jsx(ExpertManagementWorkStatus,{agent:{...agent,state:localState}}),memorySlimming');
  source = source.slice(0, start) + card + source.slice(end);
  return 'import {createExpertWorkStatus} from "./expert-work-status.js";\nconst ExpertManagementWorkStatus=createExpertWorkStatus({React:reactExports,useTranslation});\n' + source;
}
