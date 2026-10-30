"""Expert definition copy and CLI reuse without touching real user data."""
import copy
import json
from types import SimpleNamespace as NS
import unittest
from octop.infra.agents.manager import AgentManager
from octop.infra.errors import OctopError, ErrorCode


class Workspace:
    def __init__(self, files=None): self.files=files or {}
    async def aglob(self, pattern): return NS(matches=[{"path":p,"is_dir":False} for p in self.files])
    async def adownload_bytes(self,path): return self.files.get(path)
    async def aupload_many(self,pairs): self.files.update(pairs)


class Registry:
    def __init__(self):
        self.rows={k:NS(agent_id=k,user_id=1,name=k,kind="expert",description="Role",persona_mbti=None,default_model="selected",system_prompt="Role prompt",icon=None,icon_name=None,color=None,welcome_message="Welcome",skill_package_ids='[]',knowledge_base_ids='[]',mcp_servers='[]') for k in ['source','target']}
        self.configs={'source':{'workspace_dir':'original','acp':{'tool_enabled':True},'tools_disabled':['acp_runner'],'temperature':0.6},'target':{'workspace_dir':'target','tools_disabled':['execute'],'temperature':0.3}}
        self.source=Workspace({'SOUL.md':b'Role instructions','USER.md':b'private profile','MEMORY.md':b'private memory','.octop/auth/token':b'login','.octop/manifest.json':json.dumps({'id':'source','welcome_message':{'zh':'Hello'}}).encode(),'skills/role/SKILL.md':b'Role skill'})
        self.target=Workspace();self.busy=set();self.changes=[];self.spec=None
        self.teams=NS(jobs=NS(is_member_busy=lambda aid:False));self.acp_settings=NS(load_runners=lambda uid:{'codex':{'command':'existing'}})
    def get_row(self,aid): return self.rows.get(aid)
    def get_config(self,aid): return copy.deepcopy(self.configs[aid])
    def list_agents(self,uid): return [r for r in self.rows.values() if r.user_id==uid]
    def workspace_for_agent(self,aid): return self.source
    def validate_knowledge_base_ids(self,uid,ids): return ids
    def validate_mcp_servers(self,uid,ids): return ids
    def is_agent_active(self,aid): return aid in self.busy
    async def create(self,spec,*,workspace_initializer):
        self.spec=spec
        row=NS(agent_id='new',name=spec.name)
        await workspace_initializer(row,self.target)
        return row
    async def update_config_json(self,aid,value): self.configs[aid]=json.loads(value);self.changes.append(aid)


class ExpertCopyTests(unittest.IsolatedAsyncioTestCase):
    async def test_copy_uses_new_identity_and_seedable_workspace_only(self):
        r=Registry();before=copy.deepcopy(r.configs)
        row=await AgentManager.copy_expert(r,'source',user_id=1)
        self.assertEqual(row.agent_id,'new');self.assertEqual(r.configs,before)
        self.assertNotIn('workspace_dir',r.spec.config);self.assertNotIn('avatar',r.spec.config)
        self.assertFalse(r.spec.is_shared)
        self.assertEqual(r.target.files['SOUL.md'],b'Role instructions')
        self.assertEqual(r.target.files['skills/role/SKILL.md'],b'Role skill')
        self.assertNotIn('USER.md',r.target.files);self.assertNotIn('MEMORY.md',r.target.files)
        self.assertNotIn('.octop/auth/token',r.target.files)
        self.assertEqual(json.loads(r.target.files['.octop/manifest.json'])['id'],'new')
    async def test_foreign_copy_and_team_copy_are_rejected(self):
        r=Registry()
        with self.assertRaises(OctopError): await AgentManager.copy_expert(r,'source',user_id=2)
        r.rows['source'].kind='team'
        with self.assertRaises(OctopError): await AgentManager.copy_expert(r,'source',user_id=1)
        self.assertIsNone(r.spec)
    async def test_cli_reuse_is_narrow_and_deduplicates_targets(self):
        r=Registry();source=copy.deepcopy(r.configs['source'])
        result=await AgentManager.reuse_cli_config(r,'source',['target','target','source'],user_id=1)
        self.assertEqual(result['agent_ids'],['target']);self.assertEqual(r.changes,['target'])
        self.assertEqual(r.configs['source'],source)
        self.assertEqual(r.configs['target']['temperature'],0.3)
        self.assertEqual(r.configs['target']['workspace_dir'],'target')
        self.assertEqual(r.configs['target']['tools_disabled'],['acp_runner','execute'])
        self.assertEqual(r.configs['target']['acp'],{'tool_enabled':True})
    async def test_invalid_or_busy_selection_does_not_modify_any_target(self):
        r=Registry()
        for targets in [['target','missing'],['source']]:
            with self.assertRaises(OctopError): await AgentManager.reuse_cli_config(r,'source',targets,user_id=1)
            self.assertEqual(r.changes,[])
        r.busy.add('target')
        with self.assertRaises(OctopError) as error: await AgentManager.reuse_cli_config(r,'source',['target'],user_id=1)
        self.assertEqual(error.exception.code,ErrorCode.AGENT_BUSY);self.assertEqual(r.changes,[])
    async def test_pending_approval_cannot_be_overwritten(self):
        r=Registry();r._team_processor=NS(hitl_coordinator=NS(store=NS(pending_thread_ids=lambda **kwargs:{'paused'})))
        with self.assertRaises(OctopError): await AgentManager.reuse_cli_config(r,'source',['target'],user_id=1)
        self.assertEqual(r.changes,[])


if __name__=='__main__': unittest.main()
