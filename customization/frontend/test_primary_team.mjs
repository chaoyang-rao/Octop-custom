import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createRequire} from 'node:module';
import {primaryExpertForTeam} from '../packages/octop/dashboard/assets/expert-presentation.js';
const require=createRequire(new URL('../../dashboard/package.json',import.meta.url)),ts=require('typescript');
const release=JSON.parse(fs.readFileSync(new URL('./avatar-asset-release.json',import.meta.url)));
const path=new URL(`../packages/octop/dashboard/assets/index.BsYGCvv_.${release.release}.js`,import.meta.url),main=fs.readFileSync(path,'utf8');
const ast=ts.createSourceFile('main.js',main,ts.ScriptTarget.ESNext,true,ts.ScriptKind.JS);
function declaration(name){const node=ast.statements.find(n=>ts.isFunctionDeclaration(n)&&n.name?.text===name);assert.ok(node,`missing ${name}`);return node.getText(ast)}
const parse=new Function(`${declaration('optionalAgentId')}\n${declaration('parseHarnessChunkBase')}\n${declaration('parseHarnessChunk')}\nreturn parseHarnessChunk`)();
assert.equal(parse('garbage'),null);assert.equal(parse('data:{invalid'),null);
const frame=parse('data:'+JSON.stringify({type:'token',content:'小通回答',agent_id:'room',speaker_agent_id:'lead',turn_owner_agent_id:'room'}));
assert.equal(frame.agent_id,'lead');assert.equal(frame.turn_owner_agent_id,'room');assert.equal(frame.speaker_agent_id,'lead');
const rewritePeerSpeakerId=(_host,id)=>id,chunkSpeakerId=data=>data.agent_id;
const terminal=new Function('rewritePeerSpeakerId','chunkSpeakerId',declaration('isHostTurnTerminal')+';return isHostTurnTerminal')(rewritePeerSpeakerId,chunkSpeakerId);
assert.equal(terminal({...frame,type:'done'},'room',null),true);
assert.equal(terminal({type:'done',agent_id:'member'},'room',null),false);
assert.equal(terminal({...frame,type:'done',team_wrapup:true},'room',null),false);
const state={messages:[{role:'assistant',status:'streaming',content:'',speakerAgentId:'room'}]};
const deps={chunkSpeakerId,sessionHostAgentId:()=> 'room',rewritePeerSpeakerId,touchStreamActivity(){},updateContextUsageFromChunk(){},notify(){}};
const consume=new Function('deps',`with(deps){${declaration('handleHarnessChunk')};return handleHarnessChunk}`)(deps);
consume(state,{...frame,type:'state_update'},'session');assert.equal(state.messages[0].speakerAgentId,'lead');
const memberState={messages:[{role:'assistant',status:'streaming',content:'',speakerAgentId:'room'}]};
consume(memberState,{type:'state_update',agent_id:'member'},'session');assert.equal(memberState.messages[0].speakerAgentId,'room');
const experts=[{agent_id:'lead',name:'小通',is_team_primary:true},{agent_id:'other',name:'小通',is_owner:false}];
assert.equal(primaryExpertForTeam(experts)?.agent_id,'lead');assert.equal(primaryExpertForTeam(experts,{primary_agent_id:'lead'})?.agent_id,'lead');
const messages=fs.readFileSync(new URL(`../packages/octop/dashboard/assets/index.Bexwf9h5.${release.release}.js`,import.meta.url),'utf8');
assert.ok(messages.includes('authorId=isTeamHostSpeaker$1&&primaryId?primaryId:speakerId'));
assert.ok(messages.includes('authorId=hostSpeaker&&primaryId?primaryId:speakerId'));
const drawer=fs.readFileSync(new URL(`../packages/octop/dashboard/assets/index.Bxr_iAco.${release.release}.js`,import.meta.url),'utf8');
assert.ok(drawer.includes('memberPickerExperts=pickerExperts.filter(expert=>expert.agent_id!==primaryExpert?.agent_id)'));
assert.ok(drawer.includes('PrimaryExpertNotice,{expert:primaryExpert'));
for(const locale of ['zh.D-7HvP3m','en.CaWe8dRV']){
 const text=fs.readFileSync(new URL(`../packages/octop/dashboard/assets/${locale}.${release.release}.js`,import.meta.url),'utf8');assert.ok(text.includes('"teamPrimaryHostHover":'));assert.ok(text.includes('"primaryExpert":'));
}
console.log('PASS frozen real-primary actor, root terminal ownership, independent members, pending placeholder adoption, global primary notice, speaker avatars and localized labels');
