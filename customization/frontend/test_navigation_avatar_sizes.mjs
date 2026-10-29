import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.dirname(fileURLToPath(import.meta.url));
const assets = path.join(root, '../packages/octop/dashboard/assets');
const release = JSON.parse(fs.readFileSync(path.join(root, 'avatar-asset-release.json')));
const main = fs.readFileSync(path.join(assets, release.main), 'utf8');
const css = fs.readFileSync(path.join(assets, `index.Ds_DN6_-.${release.release}.css`), 'utf8');
const relevantClasses = {
  agentCardAvatar: 'index-module__agentCardAvatar__vcyg9',
  agentRowAvatar: 'index-module__agentRowAvatar__RwSkb',
  minimalAgentIconSlot: 'index-module__minimalAgentIconSlot__x98C5',
  minimalAgentAvatar: 'index-module__minimalAgentAvatar__M4ZP0',
  minimalAgentHeader: 'index-module__minimalAgentHeader__C9cuU',
};
const h = (type, props, key) => ({ type, props: { ...props, key } });
const marker = () => null;
const React = {
  useMemo: fn => fn(), useRef: value => ({ current: value }), useEffect() {},
  useState: initial => [typeof initial === 'function' ? initial() : initial, () => {}], useCallback: fn => fn,
};
let selectedScope = 'experts';
const deps = {
  jsxRuntimeExports: { jsx: h, jsxs: h, Fragment: 'fragment' }, reactExports: React,
  chatStyles: new Proxy(relevantClasses, { get: (target, name) => target[name] || name }),
  useTranslation: () => ({ t: (key, fallback) => fallback || key }),
  isAgentChatReady: () => true, ExpertIcon: marker, ExpertNameLabel: marker,
  TeamChatBadge: marker, SharedExpertHint: marker, RemoteExpertHint: marker,
  AgentUnreadBadge$1: marker, AgentUnreadBadge: marker, ExpertNavActions: marker,
  EyeOff: marker, Eye: marker, ProjectSessionList: marker,
  useNavigate: () => () => {}, useSessionWorkIds: () => new Set(),
  loadCollapsedFolders: () => new Set(), initialChatNavScope: () => selectedScope,
  usePinnedExperts: () => ({ pinnedIds: [], isPinned: () => false, togglePin() {} }),
  sortExpertsByPin: agents => agents, matchesChatNavScope: () => true,
  useExpertSessionCatalog: () => ({ byAgent: {}, patch() {}, loading: false }),
  onSessionEvent: () => () => {}, ChatNavScopeTabs: marker, Search: marker,
  ChatNavScopeEmpty: marker, ChevronRight: marker,
};
function component(name, next) {
  const start = main.indexOf(`function ${name}(`);
  const end = main.indexOf(next, start);
  assert.ok(start >= 0 && end > start, `Missing shared navigation component ${name}`);
  return new Function('deps', `with(deps){${main.slice(start, end)};return ${name};}`)(deps);
}
const Active = component('ActiveAgentCard', 'function InactiveAgentRow(');
const Inactive = component('InactiveAgentRow', 'function SessionList(');
const Minimal = component('MinimalAgentSessionNav', 'const edge="RailEdgeControl');
function all(node, predicate) {
  if (Array.isArray(node)) return node.flatMap(child => all(child, predicate));
  if (!node || typeof node !== 'object') return [];
  return [...(predicate(node) ? [node] : []), ...all(node.props?.children, predicate)];
}
for (const [scope, agent] of [
  ['experts', { agent_id: 'expert', kind: 'expert' }],
  ['teams', { agent_id: 'team', kind: 'team' }],
  ['cloud', { agent_id: 'cloud', kind: 'expert', bridge: true }],
]) {
  selectedScope = scope;
  Object.assign(agent, { name: scope, state: 'running', icon_url: '/expert-avatars/v1/squircle-ink.svg' });
  const common = { agent, sessions: [], activeId: null, searchQuery: '', agents: [agent], activeSessions: [],
    activeAgentId: agent.agent_id, onSelect() {}, onNewChat() {}, onAgentSelect() {}, liveWorkingIds: new Set() };
  for (const [label, render, slot] of [
    ['classic-active', Active, relevantClasses.agentCardAvatar],
    ['classic-inactive', Inactive, relevantClasses.agentRowAvatar],
    ['minimal', Minimal, relevantClasses.minimalAgentIconSlot],
  ]) {
    const tree = render(common);
    assert.equal(all(tree, node => node.props?.className === slot).length, 1, `${scope}/${label} uses its enlarged outer slot`);
    const icon = all(tree, node => node.type === marker && node.props?.iconUrl === agent.icon_url)[0];
    assert.equal(icon?.props.size, 48, `${scope}/${label} supplies a full 48px image as well as a 48px slot`);
  }
}
for (const name of ['agentCardAvatar', 'agentRowAvatar', 'minimalAgentIconSlot']) {
  const selector = `.${relevantClasses[name]}{`;
  const at = css.indexOf(selector);
  const rule = css.slice(at + selector.length, css.indexOf('}', at));
  assert.ok(rule.includes('width:48px') && rule.includes('height:48px'), `${name} defines a real 48px outer box`);
  if (name !== 'minimalAgentIconSlot') assert.ok(rule.includes('overflow:visible'), `${name} cannot crop character corners or motion`);
}
assert.ok(css.includes(`.${relevantClasses.minimalAgentHeader}{display:flex;align-items:center;gap:6px;width:100%;min-height:56px;`));
assert.ok(css.includes(`.${relevantClasses.minimalAgentAvatar}{position:absolute;top:0;right:0;bottom:0;left:0;border-radius:6px;display:inline-flex;align-items:center;justify-content:center;overflow:visible;`));

// v3 changed navigation size; v4 changes the Dock/account renderers while
// keeping those sizes. Compare the shared graph to the correct prior release.
const previousRelease = release.release === 'avatars-v3' ? 'avatars-v2' : 'avatars-v3';
const changed = [];
for (const name of release.assets) {
  const previousName = name.replace(`.${release.release}.`, `.${previousRelease}.`);
  if (!fs.existsSync(path.join(assets, previousName))) {
    assert.ok(release.additional_assets?.includes(name), `Unexpected extra graph asset ${name}`);
    continue;
  }
  const previous = fs.readFileSync(path.join(assets, previousName), 'utf8');
  const current = fs.readFileSync(path.join(assets, name), 'utf8').replaceAll(`.${release.release}.`, `.${previousRelease}.`);
  if (previous !== current) changed.push(name);
}
const expectedChanged = release.release === 'avatars-v3'
  ? ['index.BsYGCvv_.avatars-v3.js', 'index.Ds_DN6_-.avatars-v3.css']
  : [`index.BsYGCvv_.${release.release}.js`, `index.Bexwf9h5.${release.release}.js`];
if (Number(release.release.split('-v')[1]) >= 5) expectedChanged.push(`index.G9_xhF8C.${release.release}.js`);
if (Number(release.release.split('-v')[1]) >= 10) expectedChanged.push(`expert-avatars.${release.release}.js`);
if (Number(release.release.split('-v')[1]) >= 11) expectedChanged.push(`project-folders.${release.release}.js`, `project-folders.${release.release}.css`);
if (Number(release.release.split('-v')[1]) >= 14) expectedChanged.push(`en.CaWe8dRV.${release.release}.js`, `zh.D-7HvP3m.${release.release}.js`);
assert.deepEqual(changed.sort(), expectedChanged.sort());
console.log('PASS all three tabs retain 48px slots and images; compact header 56px; scoped module changes only');
