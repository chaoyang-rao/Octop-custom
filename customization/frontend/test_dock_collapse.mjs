import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { createDockCollapseUi } from '../packages/octop/dashboard/assets/dock-collapse.js';

const root = path.dirname(fileURLToPath(import.meta.url));
const sourcePath = path.join(root, '../packages/octop/dashboard/assets/index.BsYGCvv_.avatars-v3.js');
const original = fs.readFileSync(sourcePath, 'utf8');
const result = spawnSync('python3', ['-c',
  'from pathlib import Path; import runpy,sys; p=runpy.run_path(sys.argv[1]); print(p["patch_dock_collapse"](Path(sys.argv[2]).read_text()),end="")',
  path.join(root, 'dock-collapse-patch.py'), sourcePath], { encoding: 'utf8', maxBuffer: 4 * 1024 * 1024 });
assert.equal(result.status, 0, result.stderr);
const main = result.stdout;
const h = (type, props, key) => ({ type, props: { ...props, key } });
const React = {
  createElement: (type, props, ...children) => ({ type, props: { ...props, children } }),
  useMemo: fn => fn(), useState: initial => [typeof initial === 'function' ? initial() : initial, () => {}],
  useEffect() {}, useCallback: fn => fn,
};
const Toggle = createDockCollapseUi({ React });
let toggles = 0;
const onToggle = () => { toggles++; };
for (const collapsed of [false, true]) {
  const button = Toggle({ collapsed, onToggle }).props.children[0];
  assert.equal(button.type, 'button');
  assert.equal(button.props.type, 'button');
  assert.equal(button.props['aria-expanded'], !collapsed);
  assert.equal(button.props['aria-controls'], 'octop-global-dock');
  assert.equal(button.props['aria-label'], collapsed ? '展开导航' : '收起导航');
  button.props.onClick();
}
assert.equal(toggles, 2);

const marker = () => null;
let layoutMode = 'classic';
let chatPanelChanges = 0;
const deps = {
  jsxRuntimeExports: { jsx: h, jsxs: h, Fragment: 'fragment' }, reactExports: React,
  useNavigate: () => () => {}, useLocation: () => ({ pathname: '/experts' }),
  useTranslation: () => ({ t: (key, fallback) => fallback || key }),
  useTheme: () => ({ isDark: false }), useUserRole: () => 'admin', useCurrentUser: () => ({ id: 1 }),
  useSetCurrentUser: () => () => {}, useUpdateStatus: () => ({ hasUpdate: false }),
  useServerCapabilities: () => ({ mobileEnabled: false }),
  useLayoutMode: () => ({ layoutMode, minimalPane: 'settings', setMinimalPane() {} }),
  buildNavSections: () => [{ items: [{ key: 'experts', path: '/experts', labelKey: 'nav.experts', icon: null }] }],
  sectionsFromLayout: catalog => catalog, useNavGroupCollapse: () => ({ toggleGroup() {}, isGroupCollapsed: () => false }),
  useChatSidebarOpen: () => [true, () => { chatPanelChanges++; }], isChatPath: () => false,
  CurrentVersionBadge: marker, AppVersionBadge: marker, AvatarDropdown: marker,
  SidebarNavCustomizer: marker, navSectionLabel: () => '设置', SidebarMinimalPaneToggle: marker,
  SidebarCollapsedIconNav: marker, NavList: marker, MinimalRecordsHost: marker,
  CHAT_HISTORY_RAIL_ID: 'existing-chat-history-panel', EXPANDED_WIDTH: 220, COLLAPSED_WIDTH: 56,
  styles$d: new Proxy({}, { get: (_, key) => String(key) }),
  DockCollapseToggle: Toggle, DESKTOP_DRAG_REGION_CLASS: 'desktop-drag-region', X: marker,
};
const sidebarStart = main.indexOf('function Sidebar({');
const sidebarEnd = main.indexOf('const installBtn=', sidebarStart);
const Sidebar = new Function('deps', `with(deps){${main.slice(sidebarStart, sidebarEnd)};return Sidebar;}`)(deps);
function all(tree, predicate) {
  if (Array.isArray(tree)) return tree.flatMap(child => all(child, predicate));
  if (!tree || typeof tree !== 'object') return [];
  return [...(predicate(tree) ? [tree] : []), ...all(tree.props?.children, predicate)];
}
for (const mode of ['classic', 'minimal']) {
  layoutMode = mode;
  for (const collapsed of [false, true]) {
    const tree = Sidebar({ selectedKey: 'experts', collapsed, onToggle, isMobile: false });
    assert.equal(tree.props.id, 'octop-global-dock');
    assert.equal(tree.props.style.width, collapsed ? 56 : 220);
    assert.equal(tree.props.style.minWidth, collapsed ? 56 : 220);
    const toggle = all(tree, node => node.type === Toggle)[0];
    assert.equal(toggle.props.collapsed, collapsed);
    assert.equal(toggle.props.onToggle, onToggle, 'The visible button must reuse the existing global state callback');
  }
  const mobile = Sidebar({ selectedKey: 'experts', collapsed: true, onToggle, isMobile: true });
  assert.equal(all(mobile, node => node.type === Toggle).length, 0, 'Mobile keeps its existing drawer interaction');
  assert.equal(mobile.props.style.transform, 'translateX(-100%)');
}
assert.equal(chatPanelChanges, 0, 'Global dock controls must not alter the separate conversation panel');

const startPersist = main.indexOf('persistNavCollapsed=reactExports.useCallback(') + 'persistNavCollapsed=reactExports.useCallback('.length;
const endPersist = main.indexOf(',[]),toggleCollapsed=', startPersist);
const saved = new Map();
let collapsedState;
const persist = new Function('setCollapsed', 'localStorage', 'SIDEBAR_COLLAPSED_KEY', `return (${main.slice(startPersist, endPersist)});`)(
  value => { collapsedState = value; }, { setItem: (key, value) => saved.set(key, value) }, 'octop:sidebar:collapsed');
const eventSnippet = 'const handler=()=>{persistNavCollapsed(!collapsed)};return window.addEventListener("octop:toggle-nav",handler)';
assert.ok(main.includes(eventSnippet));
const keyboardToggle = new Function('persistNavCollapsed', 'collapsed', 'return ()=>{persistNavCollapsed(!collapsed)};')(persist, false);
keyboardToggle();
assert.equal(collapsedState, true);
assert.equal(saved.get('octop:sidebar:collapsed'), 'true');
assert.ok(main.includes('},[collapsed,persistNavCollapsed])'), 'Keyboard handler must see the latest state');

const iconsStart = main.indexOf('function SidebarCollapsedIconNav(');
const iconsEnd = main.indexOf('function SidebarMinimalPaneToggle(', iconsStart);
const IconNav = new Function('jsxRuntimeExports', 'Tooltip', 'styles$d', 'COLLAPSED_WIDTH', 'prefetchRoute',
  `${main.slice(iconsStart, iconsEnd)};return SidebarCollapsedIconNav;`)(
  { jsx: h, jsxs: h, Fragment: 'fragment' }, marker, {}, 56, () => {});
const iconTree = IconNav({ items: [{ key: 'experts', path: '/experts', labelKey: '专家', icon: null }],
  selectedKey: 'experts', onNavigate() {}, role: 'admin', hasUpdate: false, t: key => key });
const iconButton = all(iconTree, node => node.type === 'button')[0];
assert.equal(iconButton.props['aria-label'], '专家');
assert.equal(iconButton.props['aria-current'], 'page');

// Existing conversation panel and global edge toggle logic are retained.
for (const [start, end] of [
  ['function ChatSidebarPanel(', 'const EXPANDED_WIDTH='],
  ['handleNavRailToggle=reactExports.useCallback(', ';reactExports.useEffect(()=>{setCollapsed(isMobile'],
]) {
  const before = original.slice(original.indexOf(start), original.indexOf(end, original.indexOf(start)));
  const after = main.slice(main.indexOf(start), main.indexOf(end, main.indexOf(start)));
  assert.equal(after, before, `${start} must remain unchanged`);
}
console.log('PASS visible global toggle, classic/minimal 220↔56 widths, native keyboard button semantics, saved event state, named icon links, unchanged mobile/conversation panels');
