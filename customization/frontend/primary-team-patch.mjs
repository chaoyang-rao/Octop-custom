/** Preserve room transport lifecycle while rendering the real primary expert. */
function once(source,before,after) {
  const count=source.split(before).length-1;
  if(count!==1)throw Error(`Expected one primary-team point, got ${count}: ${before.slice(0,100)}`);
  return source.replace(before,after);
}
function section(source,start,end,transform) {
  const a=source.indexOf(start),b=source.indexOf(end,a+start.length);
  if(a<0||b<=a)throw Error(`Missing primary-team section ${start}`);
  return source.slice(0,a)+transform(source.slice(a,b))+source.slice(b);
}
export function patchPrimaryTransport(source) {
  source=once(source,'function parseHarnessChunk(line2){',`function parseHarnessChunk(line2){const parsed=parseHarnessChunkBase(line2);if(!parsed)return null;const raw=JSON.parse(line2.slice(5).trim()),speaker=typeof raw.speaker_agent_id==="string"?raw.speaker_agent_id.trim():undefined,owner=typeof raw.turn_owner_agent_id==="string"?raw.turn_owner_agent_id:speaker&&typeof raw.agent_id==="string"&&speaker!==raw.agent_id?raw.agent_id:undefined;return {...parsed,...speaker?{speaker_agent_id:speaker}:{},...owner?{turn_owner_agent_id:owner}:{},...raw.team_wrapup===true?{team_wrapup:true}:{},...raw.team_snapshot===true?{team_snapshot:true}:{}}}function parseHarnessChunkBase(line2){`);
  source=once(source,'["agent_id","agent","speaker_agent_id"]','["speaker_agent_id","agent_id","agent"]');
  source=section(source,'function isHostTurnTerminal(','function ',part=>{
    part=once(part,'{if(data.type===','{if(data.team_wrapup===true&&data.turn_owner_agent_id)return false;if(data.type===');
    return once(part,'const speaker=chunkSpeakerId(data,hostAgentId);','const speaker=typeof data.turn_owner_agent_id==="string"?rewritePeerSpeakerId(hostAgentId,data.turn_owner_agent_id)||data.turn_owner_agent_id:chunkSpeakerId(data,hostAgentId);');
  });
  source=once(source,'function handleHarnessChunk(state,chunk,sessionId){const speaker=chunkSpeakerId(chunk,sessionHostAgentId(state,sessionId));',`function handleHarnessChunk(state,chunk,sessionId){const speaker=chunkSpeakerId(chunk,sessionHostAgentId(state,sessionId)),owner=sessionHostAgentId(state,sessionId);if(speaker&&!chunk.team_wrapup&&!chunk.team_snapshot&&chunk.turn_owner_agent_id&&rewritePeerSpeakerId(owner,chunk.turn_owner_agent_id)===owner){state.messages=state.messages.map(message=>message.role==="assistant"&&message.status==="streaming"&&(!message.speakerAgentId||message.speakerAgentId===owner)&&!message.content&&!message.toolData&&!message.contentBlocks?.length?{...message,speakerAgentId:speaker}:message)}`);
  source=once(source,'a.state===b.state&&a.work_status','a.state===b.state&&a.is_team_primary===b.is_team_primary&&a.primary_agent_id===b.primary_agent_id&&a.primary_agent_name===b.primary_agent_name&&a.primary_icon_url===b.primary_icon_url&&a.work_status');
  source=section(source,'function mapBridgeAgent(','function ',part=>once(part,'mcp_servers:kind==="team"?[]:stringIdList(agent.mcp_servers),kind,member_ids:memberIds,','mcp_servers:kind==="team"&&!agent.primary_agent_id?[]:stringIdList(agent.mcp_servers),kind,member_ids:memberIds,primary_agent_id:typeof agent.primary_agent_id==="string"?toBridgeShadowAgentId(conn.connection_id,agent.primary_agent_id):null,primary_agent_name:agent.primary_agent_name,primary_icon_url:agent.primary_icon_url,'));
  return source;
}
export function patchPrimarySpeakers(source) {
  source=once(source,'expert=reactExports.useMemo(()=>speakerId&&agents.find(item=>item.agent_id===speakerId)||(isTeamHostSpeaker$1||!isTeamRoom?activeAgent:void 0),[speakerId,agents,activeAgent,isTeamHostSpeaker$1,isTeamRoom]),avatarTooltip=isTeamHostSpeaker$1?t("chat.teamHostHover",{name:(activeAgent==null?void 0:activeAgent.name)||(expert==null?void 0:expert.name)||""}):expert==null?void 0:expert.name,avatarProfileId=isTeamHostSpeaker$1?activeAgent==null?void 0:activeAgent.agent_id:speakerId,',
    'primaryId=rewritePeerSpeakerId(activeAgent?.agent_id,activeAgent?.primary_agent_id)||activeAgent?.primary_agent_id,authorId=isTeamHostSpeaker$1&&primaryId?primaryId:speakerId,expert=reactExports.useMemo(()=>authorId&&agents.find(item=>item.agent_id===authorId)||(!isTeamRoom?activeAgent:void 0),[authorId,agents,activeAgent,isTeamRoom]),avatarTooltip=isTeamHostSpeaker$1?primaryId?t("chat.teamPrimaryHostHover",{name:expert?.name||activeAgent?.primary_agent_name||"小通"}):t("chat.teamHostHover",{name:activeAgent?.name||""}):expert?.name,avatarProfileId=authorId,');
  source=once(source,'expert=speakerId&&agents.find(item=>item.agent_id===speakerId)||(!isTeamRoom||hostSpeaker?activeAgent:void 0),avatarTooltip=hostSpeaker?t("chat.teamHostHover",{name:(activeAgent==null?void 0:activeAgent.name)||(expert==null?void 0:expert.name)||""}):(expert==null?void 0:expert.name)||void 0,avatarProfileId=hostSpeaker?activeAgent==null?void 0:activeAgent.agent_id:speakerId||void 0,',
    'primaryId=rewritePeerSpeakerId(activeAgent?.agent_id,activeAgent?.primary_agent_id)||activeAgent?.primary_agent_id,authorId=hostSpeaker&&primaryId?primaryId:speakerId,expert=authorId&&agents.find(item=>item.agent_id===authorId)||(!isTeamRoom?activeAgent:void 0),avatarTooltip=hostSpeaker?primaryId?t("chat.teamPrimaryHostHover",{name:expert?.name||activeAgent?.primary_agent_name||"小通"}):t("chat.teamHostHover",{name:activeAgent?.name||""}):expert?.name||void 0,avatarProfileId=authorId||void 0,');
  source=once(source,'hostName:activeAgent==null?void 0:activeAgent.name,limit:2','hostName:activeAgent?.primary_agent_name||activeAgent?.name,limit:2');
  // Include the primary display name in the live-speaker memo dependencies.
  return once(source,'[liveSpeakers,agents,activeAgent==null?void 0:activeAgent.agent_id,activeAgent==null?void 0:activeAgent.name]','[liveSpeakers,agents,activeAgent?.agent_id,activeAgent?.primary_agent_name,activeAgent?.name]');
}
export function patchPrimaryDrawer(source) {
  source='import {primaryExpertForTeam,createPrimaryNotice} from "./expert-presentation.js";\nconst PrimaryExpertNotice=createPrimaryNotice({React:reactExports,Avatar:ExpertIcon});\n'+source;
  return section(source,'function TeamDrawer(','const STATE_META=',part=>{
    part=once(part,'[experts,rosterExtras]);reactExports.useEffect','[experts,rosterExtras]),primaryExpert=primaryExpertForTeam(pickerExperts,team),memberPickerExperts=pickerExperts.filter(expert=>expert.agent_id!==primaryExpert?.agent_id);reactExports.useEffect');
    part=once(part,'blocked=submitting||hasNoModels,','blocked=submitting||hasNoModels||!primaryExpert,');
    part=once(part,'member_ids:selectedRosterIds(values.member_ids,pickerExperts)','member_ids:selectedRosterIds(values.member_ids,memberPickerExperts)');
    part=once(part,'jsxRuntimeExports.jsx(Form.Item,{name:"member_ids",','jsxRuntimeExports.jsx(PrimaryExpertNotice,{expert:primaryExpert,label:t("experts.teams.primaryExpert",{name:primaryExpert?.name||"小通"})}),jsxRuntimeExports.jsx(Form.Item,{name:"member_ids",');
    part=once(part,'if(selectedRosterIds(value,pickerExperts).length<2)throw new Error(t("experts.teams.membersMin"))','if(selectedRosterIds(value,memberPickerExperts).length<(primaryExpert?1:2))throw new Error(t(primaryExpert?"experts.teams.otherMemberMin":"experts.teams.membersMin"))');
    return once(part,'TeamMemberPicker,{experts:pickerExperts}','TeamMemberPicker,{experts:memberPickerExperts}');
  });
}
export function patchPrimaryLocale(source) {
  const zh=source.includes('\"teamBadge\":\"团队\"');
  source=once(source,'"teamHostHover":',`"teamPrimaryHostHover":${JSON.stringify(zh?'{{name}} · 主专家／主持人':'{{name}} · Primary expert / host')},"teamHostHover":`);
  // The primary notice belongs in experts.teams beside its roster validation.
  return once(source,'"membersMin":',`"primaryExpert":${JSON.stringify(zh?'主专家／主持人：{{name}}（所有团队固定）':'Primary expert / host: {{name}} (all teams)')},"otherMemberMin":${JSON.stringify(zh?'请至少选择一位其他专家':'Select at least one other expert')},"membersMin":`);
}
