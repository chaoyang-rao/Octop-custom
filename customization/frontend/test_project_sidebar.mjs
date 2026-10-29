import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createProjectFolders } from '../packages/octop/dashboard/assets/project-folders.js';

// These interaction tests execute the shipped component without a DOM, using a
// small hook harness. The live desktop checks cover dialog focus and rendering.
globalThis.localStorage = { getItem: () => null, setItem() {} };
globalThis.window = { setTimeout };
const project = { project_path: '/tmp/项目 A', project_name: '项目 A' };
const threads = [
  { id: 'one', name: '修改导航', projectPath: project.project_path, projectName: project.project_name },
  { id: 'two', name: '旧会话', projectPath: null },
];
const icon = () => null;
const Row = () => null;
const CompactRow = () => null;
const calls = [], selected = [], notices = [];
let state, cursor;
const React = {
  createElement(type, props, ...children) { return { type, props: { ...props, children } }; },
  useState(initial) {
    const index = cursor++;
    if (!(index in state)) state[index] = typeof initial === 'function' ? initial() : initial;
    return [state[index], next => { state[index] = typeof next === 'function' ? next(state[index]) : next; }];
  },
  useRef(value) { return { current: value }; },
  useEffect() {}, useCallback(callback) { return callback; },
};
const Component = createProjectFolders({ React,
  request: async (url, options = {}) => {
    calls.push({ url, ...options });
    if (options.method === 'POST' && url.endsWith('/threads')) return { thread_id: 'created-project-chat' };
    if (url.endsWith('/projects')) return [project];
    if (url.includes('/threads?')) return threads;
    return { removed: true };
  },
  toSession: value => value, sortSessions: value => value,
  Row, CompactRow: () => CompactRow, resolveStatus: () => 'idle',
  emitSessionEvent: event => notices.push(event), onSessionEvent: () => () => {},
  Dropdown: icon, Plus: icon, More: icon, Chevron: icon,
});
const props = { agent: { agent_id: 'codex' }, sessions: threads, activeId: 'one',
  onSelect: (...args) => selected.push(args), onDelete() {}, onRename() {}, onPin() {}, onFork() {},
  liveWorkingIds: new Set(),
};
function reset(overrides = {}) {
  calls.length = selected.length = notices.length = 0;
  state = [[project], threads, false, '', false, null, '', '', new Set()];
  for (const [key, value] of Object.entries(overrides)) state[Number(key)] = value;
}
function render(extra = {}) { cursor = 0; return Component({ ...props, ...extra }); }
function all(tree, predicate) {
  if (Array.isArray(tree)) return tree.flatMap(child => all(child, predicate));
  if (!tree || typeof tree !== 'object') return [];
  return [...(predicate(tree) ? [tree] : []), ...all(tree.props?.children, predicate)];
}
function button(tree, label) {
  return all(tree, node => node.type === 'button' && (node.props['aria-label'] === label || node.props.children.includes(label)))[0];
}
const tick = () => new Promise(resolve => setTimeout(resolve, 0));

reset();
let tree = render();
assert.equal(all(tree, node => node.type === 'section' && node.props['aria-label'] === '项目 A').length, 1);
assert.equal(all(tree, node => node.type === Row && node.props.session.id === 'one').length, 1);
assert.equal(all(tree, node => node.type === 'section' && node.props['aria-label'] === '未分组会话').length, 1);
const folderNode = all(tree, node => typeof node.type === 'function' && node.type.name === 'Folder')[0];
const folderSvg = folderNode.type(folderNode.props);
assert.equal(folderSvg.props.width, 14);
assert.equal(folderSvg.props.height, 14);
assert.equal(folderSvg.props.style.flexShrink, 0);
await button(tree, '在 项目 A 新建对话').props.onClick();
assert.equal(JSON.parse(calls.find(call => call.method === 'POST').body).project_path, '/tmp/项目 A');
assert.deepEqual(selected[0], ['created-project-chat', 'codex']);

reset();
tree = render();
await button(tree, '新建未分组对话').props.onClick();
assert.equal(JSON.parse(calls.find(call => call.method === 'POST').body).project_path, null);

reset({ 5: { kind: 'move', session: threads[1] }, 6: project.project_path });
tree = render();
const moveForm = all(tree, node => node.type === 'form')[0];
moveForm.props.onSubmit({ preventDefault() {} }); await tick();
const moveCall = calls.find(call => call.method === 'PATCH');
assert.equal(moveCall.url, '/agents/codex/threads/two/project');
assert.equal(JSON.parse(moveCall.body).project_path, '/tmp/项目 A');

reset({ 5: { kind: 'remove', project } });
tree = render();
await button(tree, '移除分组').props.onClick();
assert.equal(calls.filter(call => call.method === 'DELETE').length, 1);
assert.equal(calls.find(call => call.method === 'DELETE').url, '/agents/codex/projects');
assert.ok(!calls.some(call => call.url.includes('/files') || call.url.includes('/workspace')));

reset({ 1: [{ ...threads[0], turnActive: true }] });
tree = render({ compact: true });
assert.equal(all(tree, node => node.type === CompactRow)[0].props.projectMenuItems[0].disabled, true);

reset();
tree = render({ searchQuery: '项目 A' });
assert.equal(all(tree, node => node.type === Row).length, 1);
assert.equal(all(tree, node => node.type === Row)[0].props.session.id, 'one');

// Every rewritten static module edge must exist, and no new module may import
// the old app state module after the versioned main entry has loaded.
const root = path.dirname(fileURLToPath(import.meta.url));
const release = JSON.parse(fs.readFileSync(path.join(root, 'asset-release.json')));
const assets = path.join(root, '../packages/octop/dashboard/assets');
for (const name of release.assets.filter(name => name.endsWith('.js'))) {
  const source = fs.readFileSync(path.join(assets, name), 'utf8');
  assert.ok(!source.includes('./index.BsYGCvv_.js'), `Stale main module reference: ${name}`);
  for (const match of source.matchAll(/(?:from\s*|import\s*\()?["']\.\/([^"']+\.(?:js|css))["']/g)) {
    assert.ok(fs.existsSync(path.join(assets, match[1])), `Missing module ${match[1]} in ${name}`);
  }
}
console.log('PASS: grouping, project/ungrouped creation, move, safe removal, busy-session guard, project search, versioned module graph');
