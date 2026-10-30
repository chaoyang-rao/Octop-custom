import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { patchApplicationChannels, patchApplicationChannelForms, patchApplicationConnectorCard, patchApplicationLocale } from './application-connectors-patch.mjs';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const base=path.join(root,'customization/baselines/projects-v2/octop/dashboard/assets');
const cases=[['index.BsYGCvv_.projects-v2.js',patchApplicationChannels],['AgentPluginsPanel.BJlhPlDN.projects-v2.js',patchApplicationChannelForms],['index.C1lMbskB.projects-v2.js',patchApplicationConnectorCard],['en.CaWe8dRV.projects-v2.js',patchApplicationLocale],['zh.D-7HvP3m.projects-v2.js',patchApplicationLocale]];
for(const [name,patch] of cases){
 const source=fs.readFileSync(path.join(base,name),'utf8');
 const output=patch(source);
 const parsed=spawnSync(process.execPath,['--input-type=module','--check'],{input:output,encoding:'utf8'});
 assert.equal(parsed.status,0,parsed.stderr);
 assert.notEqual(output,source);
 assert.throws(()=>patch('changed upstream layout'));
 if(name.startsWith('zh.'))assert.ok(output.includes('当前主机系统不支持'));
 if(name.startsWith('en.'))assert.ok(output.includes('Not supported on this host'));
}
console.log('Application connector patches: 5 preserved modules parsed; host gating, Slack schema and both locales checked.');
