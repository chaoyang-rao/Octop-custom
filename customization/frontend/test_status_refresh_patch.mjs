import assert from 'node:assert/strict';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import { patchChatStatusPollingSource, patchSessionStatusPriority, patchExpertStatusLocaleSource } from './status-refresh-patch.mjs';
const require = createRequire(new URL('../../dashboard/package.json', import.meta.url));
const ts = require('typescript');
const assets = new URL('../baselines/projects-v2/octop/dashboard/assets/', import.meta.url);
const composer = fs.readFileSync(new URL('index.G9_xhF8C.projects-v2.js', assets), 'utf8');
const main = fs.readFileSync(new URL('index.BsYGCvv_.projects-v2.js', assets), 'utf8');
const patched = patchChatStatusPollingSource(composer);
assert.ok(!patched.includes('setInterval(refreshBadges,1e4)'));
assert.ok(patched.includes('function useChatNavigation('));
assert.ok(patched.includes('event2.kind==="streamEnd"'));
assert.throws(() => patchChatStatusPollingSource(patched), /anchor/);
const updated = patchSessionStatusPriority(main);
const body = updated.match(/function resolveSessionWorkStatus\([^)]*\)\{[^}]*\}/)[0];
const resolver = new Function(`${body};return resolveSessionWorkStatus;`)();
const source = fs.readFileSync(new URL('../../dashboard/src/pages/Chat/utils/sessionWorkStatus.ts', import.meta.url), 'utf8');
const sourceJS = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
const exports = {};new Function('exports', sourceJS)(exports);
for (const [session, live, expected] of [
  [{ id: 'x', turnActive: true, awaitingUser: true }, [], 'waiting'],
  [{ id: 'x', awaitingUser: true }, ['x'], 'waiting'],
  [{ id: 'x', turnActive: true }, [], 'working'],
  [{ id: 'x' }, ['x'], 'working'],
  [{ id: 'x' }, [], 'idle'],
]) {
  assert.equal(resolver(session, new Set(live)), expected);
  assert.equal(exports.resolveSessionWorkStatus(session, new Set(live)), expected);
}
assert.throws(() => patchSessionStatusPriority(updated), /anchor/);
for (const [name, expected] of [['zh.D-7HvP3m.projects-v2.js', '工作中'], ['en.CaWe8dRV.projects-v2.js', 'Working']]) {
  const locale = fs.readFileSync(new URL(name, assets), 'utf8');
  const changed = patchExpertStatusLocaleSource(locale);
  const body = changed.slice(0, changed.lastIndexOf('export{'));
  const messages = new Function(`${body};return chat;`)();
  assert.equal(messages.expertWorkStatus.working, expected);
  assert.ok(messages.expertWorkEnabled);
  assert.throws(() => patchExpertStatusLocaleSource(changed), /anchor/);
}
console.log('PASS single global refresh integration and source/frozen pending-confirmation priority');
