import assert from 'node:assert/strict';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import { patchExpertStatusSource, patchExpertManagementStatus, EXPERT_ACTIVITY_REFRESH_EFFECT } from './expert-status-patch.mjs';
import { createExpertWorkStatus, deriveExpertWorkStatus } from '../packages/octop/dashboard/assets/expert-work-status.js';

const require = createRequire(new URL('../../dashboard/package.json', import.meta.url));
const esbuild = require('esbuild');
const { JSDOM } = require('jsdom');
const dom = new JSDOM('<!doctype html><body></body>', { url: 'http://localhost/', pretendToBeVisual: true });
for (const key of ['window', 'document', 'HTMLElement', 'Element', 'Node', 'MutationObserver']) globalThis[key] = key === 'window' ? dom.window : dom.window[key];
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator });
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const React = require('react'), { createRoot } = require('react-dom/client');
const { act } = React;
const read = relative => fs.readFileSync(new URL(relative, import.meta.url), 'utf8');
function compile(source, loader, dependencies = {}) {
  const result = { exports: {} };
  const code = esbuild.transformSync(source, { loader, format: 'cjs', jsx: 'automatic', target: 'es2022' }).code;
  new Function('module', 'exports', 'require', code)(result, result.exports, name => {
    if (name in dependencies) return dependencies[name];
    if (name === 'react') return React;
    if (name === 'react/jsx-runtime') return require('react/jsx-runtime');
    if (/\.(css|less)$/.test(name)) return {};
    throw new Error(`Unexpected test dependency: ${name}`);
  });
  return result.exports;
}
const sourceLogic = compile(read('../../dashboard/src/pages/Chat/utils/expertWorkStatus.ts'), 'ts');
let language = 'zh';
const useTranslation = () => ({ t: (key, options) => options?.defaultValue || key, i18n: { language } });
const SourceBadge = compile(read('../../dashboard/src/pages/Chat/components/ExpertWorkStatus.tsx'), 'tsx', {
  'react-i18next': { useTranslation }, '../utils/expertWorkStatus': sourceLogic,
}).default;
const RawBadge = createExpertWorkStatus({ React, useTranslation });
const cases = [
  ['work and waiting are both visible', { state: 'running', work_status: 'working', working_count: 2, waiting_count: 1 }, [{ kind: 'working', count: 2 }, { kind: 'waiting', count: 1 }]],
  ['waiting is not falsely busy', { state: 'running', work_status: 'waiting', working_count: 0, waiting_count: 3 }, [{ kind: 'waiting', count: 3 }]],
  ['trusted idle', { state: 'running', work_status: 'idle', working_count: 0, waiting_count: 0 }, [{ kind: 'idle', count: null }]],
  ['old backend is only online', { state: 'running' }, [{ kind: 'online', count: null }]],
  ['untrusted counts alone are not work', { state: 'running', working_count: 8 }, [{ kind: 'online', count: null }]],
  ['remote legacy status', { state: 'running', bridge: true }, [{ kind: 'remote_online', count: null }]],
  ['remote disconnection wins over stale work', { state: 'running', bridge: true, bridge_disconnected: true, work_status: 'working', working_count: 1 }, [{ kind: 'disconnected', count: null }]],
  ['explicit unknown invalidates old work', { state: 'running', work_status: 'unknown', working_count: 6 }, [{ kind: 'unknown', count: null }]],
  ['failure lifecycle wins over unknown', { state: 'failed', work_status: 'unknown' }, [{ kind: 'failed', count: null }]],
  ['local startup wins over a previous failed snapshot', { state: 'starting', work_status: 'failed' }, [{ kind: 'starting', count: null }]],
  ['local stopping lifecycle wins over stale idle', { state: 'stopping', work_status: 'idle' }, [{ kind: 'stopping', count: null }]],
  ['not started', { state: 'created' }, [{ kind: 'stopped', count: null }]],
  ['starting', { state: 'starting' }, [{ kind: 'starting', count: null }]],
  ['trusted failed', { state: 'running', work_status: 'failed' }, [{ kind: 'failed', count: null }]],
  ['counts are not invented for status-only data', { state: 'running', work_status: 'working' }, [{ kind: 'working', count: null }]],
  ['invalid counters never display', { state: 'running', work_status: 'waiting', working_count: -1, waiting_count: NaN }, [{ kind: 'waiting', count: null }]],
  ['fractional/unsafe counters never display', { state: 'running', work_status: 'working', working_count: 1.5, waiting_count: Number.MAX_SAFE_INTEGER + 1 }, [{ kind: 'working', count: null }]],
  ['empty data remains unknown', {}, [{ kind: 'unknown', count: null }]],
];
for (const [label, input, expected] of cases) {
  assert.deepEqual(sourceLogic.deriveExpertWorkStatus(Object.freeze(input)), expected, label);
  assert.deepEqual(deriveExpertWorkStatus(Object.freeze(input)), expected, `frozen/${label}`);
}
console.log(`PASS ${cases.length} real status scenarios in source and frozen logic; lifecycle and account-visible counters`);

async function render(Component, agent) {
  const container = document.createElement('div'); document.body.append(container);
  const root = createRoot(container);
  await act(async () => root.render(React.createElement(Component, { agent: { name: 'Expert A', ...agent } })));
  return { container, destroy: async () => { await act(async () => root.unmount()); container.remove(); } };
}
for (const [lang, working, waiting] of [['zh', '工作中 2', '待确认 1'], ['en', 'Working 2', 'Waiting 1']]) {
  language = lang;
  let expected;
  for (const Component of [SourceBadge, RawBadge]) {
    const view = await render(Component, cases[0][1]);
    const badges = [...view.container.querySelectorAll('[data-work-status]')];
    assert.deepEqual(badges.map(x => x.textContent), [working, waiting]);
    assert.ok(badges.every(x => x.getAttribute('aria-label').includes('Expert A') && x.title.includes(':')));
    assert.equal(view.container.querySelectorAll('img,svg,[data-octop-geometric-avatar],button').length, 0, 'Status cannot replace, wrap or click an avatar');
    const output = view.container.innerHTML;
    if (expected) assert.equal(output, expected, 'Source and frozen display/ARIA/title stay aligned');
    expected = output;
    await view.destroy();
  }
}
console.log('PASS real React bilingual badges, readable labels/counts, no avatar/backplate or button side effects');

const baseline = read('../baselines/projects-v2/octop/dashboard/assets/index.BsYGCvv_.projects-v2.js');
const patched = patchExpertStatusSource(baseline);
esbuild.transformSync(patched, { loader: 'js', format: 'esm' });
assert.equal((patched.match(/jsxRuntimeExports\.jsx\(ExpertWorkStatus,\{agent\}\)/g) || []).length, 3);
for (const name of ['agentCardAvatar', 'agentRowAvatar', 'minimalAgentAvatar']) {
  const at = baseline.indexOf('className:chatStyles.' + name + ',');
  const imageEnd = baseline.indexOf('size:', at);
  assert.ok(patched.includes(baseline.slice(at, imageEnd + 5)), `Unchanged ${name} rendering`);
}
assert.throws(() => patchExpertStatusSource(patched), /already/);
assert.throws(() => patchExpertStatusSource(''), /patch point/);
const originalEqual = baseline.slice(baseline.indexOf('function agentsSnapshotEqual('), baseline.indexOf('function projectChatAgentOption('));
const patchedEqual = patched.slice(patched.indexOf('function agentsSnapshotEqual('), patched.indexOf('function projectChatAgentOption('));
const sameMemberIds = (a, b) => JSON.stringify(a || []) === JSON.stringify(b || []);
const oldEqual = new Function('sameMemberIds', originalEqual + ';return agentsSnapshotEqual;')(sameMemberIds);
const newEqual = new Function('sameMemberIds', patchedEqual + ';return agentsSnapshotEqual;')(sameMemberIds);
const sourceContext = read('../../dashboard/src/context/AgentContext.tsx');
const context = compile(sourceContext, 'tsx', {
  '../api/request': { setActiveAgentId() {} }, '../api/modules/agent': { agentApi: {} },
  '../utils/remoteExpert': { retainDisconnectedBridgeAgents: (prev, next) => next, toBridgeShadowAgentId: (connection, id) => `${connection}:${id}` },
  '../pages/Chat/hooks/chatStore': { onStreamEvent: () => () => {}, onSessionEvent: () => () => {} },
});
const agent = { agent_id: 'a', state: 'running', name: 'A', default_model: 'p/model', config: { stable: true }, work_status: 'idle', working_count: 0, waiting_count: 0 };
for (const update of [{ work_status: 'working' }, { working_count: 1 }, { waiting_count: 1 }]) {
  assert.equal(oldEqual([agent], [{ ...agent, ...update }]), true);
  assert.equal(newEqual([agent], [{ ...agent, ...update }]), false);
  assert.equal(context.agentsSnapshotEqual([agent], [{ ...agent, ...update }]), false);
}
assert.equal(newEqual([agent], [{ ...agent }]), true);
const invalidatePart = patched.slice(patched.indexOf('function invalidateExpertWorkFields('), patched.indexOf('function bridgeWorkFields('));
const frozenInvalidate = new Function(invalidatePart + ';return invalidateExpertWorkFields;')();
for (const invalidate of [context.invalidateExpertWorkFields, frozenInvalidate]) {
  const input = Object.freeze([Object.freeze({ ...agent, work_status: 'working', working_count: 2 })]);
  const output = invalidate(input);
  assert.equal(output[0].work_status, 'unknown'); assert.equal(output[0].working_count, undefined); assert.equal(output[0].waiting_count, undefined);
  for (const name of ['agent_id', 'name', 'state', 'default_model', 'config']) assert.equal(output[0][name], input[0][name]);
  assert.equal(invalidate(output), output, 'Repeated failures do not churn the snapshot');
  assert.equal(deriveExpertWorkStatus(output[0])[0].kind, 'unknown');
}
const connection = { connection_id: 'c', display_name: 'Remote' };
const valid = context.mapBridgeAgent({ id: 'r', name: 'R', work_status: 'working', working_count: 2, waiting_count: -1 }, connection);
assert.equal(valid.work_status, 'working'); assert.equal(valid.working_count, 2); assert.equal(valid.waiting_count, undefined);
const invalid = context.mapBridgeAgent({ id: 'r', work_status: 'private-global-busy', working_count: 99 }, connection);
assert.equal(invalid.work_status, undefined); assert.equal(invalid.working_count, undefined);
console.log('PASS snapshot-only activity updates, failure invalidation preserves config/defaults, remote field validation');

const originalCard = read('../baselines/projects-v2/octop/dashboard/assets/EditAgentDrawer.w674TDCV.projects-v2.js');
const card = patchExpertManagementStatus(originalCard);
esbuild.transformSync(card, { loader: 'js', format: 'esm' });
assert.equal((card.match(/jsxRuntimeExports\.jsx\(ExpertManagementWorkStatus/g) || []).length, 1);
assert.ok(card.includes('localState==="running"?t("chat.expertWorkEnabled"'));
assert.ok(card.includes('onChange:checked=>void handleToggle(checked)'), 'The enabled switch stays authoritative');
assert.throws(() => patchExpertManagementStatus(card), /already/);
assert.throws(() => patchExpertManagementStatus(baseline), /boundary/);
console.log('PASS three navigation badges and management card activity; existing switch and avatar rendering preserved');

function clockFixture(effect) {
  let next = 0, pending = 0, peak = 0;
  const timers = new Map(), focus = new Map(), visibility = new Map(), stream = new Set(), session = new Set(), calls = [];
  const win = { setInterval: (fn, delay) => { const id = ++next; timers.set(id, { fn, delay, interval: true }); return id; }, clearInterval: id => timers.delete(id), setTimeout: (fn, delay) => { const id = ++next; timers.set(id, { fn, delay, interval: false }); return id; }, clearTimeout: id => timers.delete(id), addEventListener: (name, fn) => focus.set(name, fn), removeEventListener: name => focus.delete(name) };
  const doc = { visibilityState: 'visible', addEventListener: (name, fn) => visibility.set(name, fn), removeEventListener: name => visibility.delete(name) };
  const subscribe = set => fn => { set.add(fn); return () => set.delete(fn); };
  const refresh = options => { assert.deepEqual(options, { silent: true }); pending++; peak = Math.max(peak, pending); let resolve; const promise = new Promise(r => { resolve = () => { pending--; r(); }; }); calls.push({ resolve }); return promise; };
  const cleanup = effect(win, doc, subscribe(stream), subscribe(session), refresh)();
  const flush = () => { for (const [id, timer] of [...timers]) if (!timer.interval) { timers.delete(id); assert.equal(timer.delay, 150); timer.fn(); } };
  const interval = () => { for (const timer of [...timers.values()]) if (timer.interval) { assert.equal(timer.delay, 5000); timer.fn(); } };
  return { calls, timers, focus, visibility, stream, session, win, doc, cleanup, flush, interval, peak: () => peak };
}
const sourceEffectStart = sourceContext.indexOf('// One activity refresh loop');
const sourceEffectEnd = sourceContext.indexOf('\n  }, [refresh]);', sourceEffectStart);
const sourceEffectBody = sourceContext.slice(sourceContext.indexOf('useEffect(() => {', sourceEffectStart) + 'useEffect(() => {'.length, sourceEffectEnd);
const sourceWatcher = compile(`export function watch(window:any,document:any,onStreamEvent:any,onSessionEvent:any,refresh:any){return()=>{${sourceEffectBody}\n}}`, 'ts').watch;
const frozenWatcher = new Function('window', 'document', 'onStreamEvent', 'onSessionEvent', 'refresh', `return(${EXPERT_ACTIVITY_REFRESH_EFFECT});`);
for (const factory of [sourceWatcher, frozenWatcher]) {
  const c = clockFixture(factory);
  assert.equal(c.calls.length, 0, 'Initial fetch is not duplicated by watcher');
  for (const fn of c.stream) { fn({ kind: 'streamStart', sessionId: 'a' }); fn({ kind: 'streamEnd', sessionId: 'a' }); }
  c.focus.get('focus')();
  assert.equal([...c.timers.values()].filter(x => !x.interval).length, 1);
  c.flush(); assert.equal(c.calls.length, 1);
  c.interval(); c.interval(); assert.equal(c.calls.length, 1, 'No overlap while previous snapshot is pending');
  c.calls[0].resolve(); await Promise.resolve(); await Promise.resolve(); c.flush();
  assert.equal(c.calls.length, 2, 'Pending hints are coalesced into one trailing refresh');
  assert.equal(c.peak(), 1, 'Slow snapshots are serialized and cannot arrive backwards');
  c.cleanup(); c.calls[1].resolve(); await Promise.resolve(); await Promise.resolve(); c.flush();
  assert.equal(c.calls.length, 2); assert.equal(c.timers.size, 0); assert.equal(c.stream.size, 0); assert.equal(c.session.size, 0); assert.equal(c.focus.size, 0); assert.equal(c.visibility.size, 0);
  const hidden = clockFixture(factory); hidden.doc.visibilityState = 'hidden'; hidden.interval(); hidden.focus.get('focus')(); hidden.flush(); assert.equal(hidden.calls.length, 0);
  hidden.doc.visibilityState = 'visible'; hidden.visibility.get('visibilitychange')(); hidden.flush(); assert.equal(hidden.calls.length, 1); hidden.cleanup(); hidden.calls[0].resolve(); await Promise.resolve();
}
console.log('PASS source/frozen single 5s watcher: visible-only polling, debounced hints, no overlapping snapshots, trailing refresh and complete cleanup');
const css = read('../packages/octop/dashboard/assets/expert-work-status.css');
assert.equal(css, read('../../dashboard/src/pages/Chat/components/ExpertWorkStatus.css'));
assert.ok(css.includes('prefers-reduced-motion')); assert.ok(css.includes('animation: none !important'));
console.log('PASS shared scoped CSS and reduced-motion state indicators');
