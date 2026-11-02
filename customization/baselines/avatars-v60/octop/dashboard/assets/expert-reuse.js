/** Shared source/frozen expert-copy and account-local CLI reuse dialogs. */
export function createExpertReuseDialogs({React,Modal,Input,Select,Alert,useTranslation,useAgent,api,notify}) {
 const h=React.createElement;
 return function ExpertReuseDialogs({agent,onCopied,children}) {
  const {t}=useTranslation(),{agents,refresh}=useAgent(),saving=React.useRef(false);
  const [mode,setMode]=React.useState(null),[name,setName]=React.useState(''),[targets,setTargets]=React.useState([]),[busy,setBusy]=React.useState(false);
  const eligible=agents.filter(item=>item.agent_id!==agent.agent_id&&item.is_owner===true&&!item.bridge&&item.kind!=='team');
  const working=item=>['working','waiting','starting','stopping'].includes(item.work_status)||['starting','stopping'].includes(item.state);
  const close=()=>{if(!busy)setMode(null)};
  const save=async()=>{
   if(saving.current)return;
   const selected=targets.filter(id=>eligible.some(item=>item.agent_id===id));
   if(mode==='cli'&&(!selected.length||selected.length!==targets.length||selected.some(id=>working(eligible.find(item=>item.agent_id===id))))){notify.error(t('experts.reuse.busySelection'));return;}
   saving.current=true;setBusy(true);
   try {
    if(mode==='copy')await api.copyExpert(agent.agent_id,name.trim()||undefined);
    else await api.reuseCli(agent.agent_id,selected);
    notify.success(t(mode==='copy'?'experts.reuse.copySuccess':'experts.reuse.cliSuccess'));
    setMode(null);await refresh({silent:true,force:true});onCopied?.();
   } catch(error) {notify.error(error?.message||t('experts.reuse.failed'))}
   finally {saving.current=false;setBusy(false)}
  };
  return h(React.Fragment,null,children({copy:()=>{setName('');setMode('copy')},cli:()=>{setTargets([]);setMode('cli')}}),
   h(Modal,{open:mode!==null,title:t(mode==='copy'?'experts.reuse.copyTitle':'experts.reuse.cliTitle'),onCancel:close,onOk:save,confirmLoading:busy,closable:!busy,maskClosable:!busy,keyboard:!busy,okText:t(mode==='copy'?'common.create':'experts.reuse.apply'),cancelText:t('common.cancel'),okButtonProps:{disabled:mode==='cli'&&!targets.some(id=>eligible.some(item=>item.agent_id===id&&!working(item)))}},
    h('p',null,t('experts.reuse.source',{name:agent.name})),
    h(Alert,{type:'info',showIcon:true,message:t(mode==='copy'?'experts.reuse.copyHint':'experts.reuse.cliHint'),style:{marginBottom:16}}),
    mode==='cli'?h('p',null,t('experts.reuse.sourceState',{state:agent.config?.acp?.tool_enabled&&!agent.config?.tools_disabled?.includes('acp_runner')?t('experts.reuse.enabled'):t('experts.reuse.disabled')})):null,
    mode==='copy'?h(Input,{value:name,maxLength:100,placeholder:t('experts.reuse.namePlaceholder',{name:agent.name}),onChange:e=>setName(e.target.value),disabled:busy,'aria-label':t('experts.agentName')}):h(Select,{mode:'multiple',style:{width:'100%'},value:targets,disabled:busy,placeholder:t('experts.reuse.targets'),optionFilterProp:'label',options:eligible.map(item=>({value:item.agent_id,label:item.name+(working(item)?` · ${t('experts.reuse.busy')}`:''),disabled:working(item)})),onChange:setTargets,'aria-label':t('experts.reuse.targets')})
   ));
 };
}
