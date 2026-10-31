/** Exercise the real TSX component without the repo's missing testing-library peer. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import { m as modelOptionLabel, e as modelOptionValue, c as modelShortLabel } from '../baselines/projects-v2/octop/dashboard/assets/modelOptions.BrFzajT7.projects-v2.js';

const require = createRequire(new URL('../../dashboard/package.json', import.meta.url));
const { JSDOM } = require('jsdom');
const dom = new JSDOM('<!doctype html><body></body>', { url: 'http://localhost/' });
for (const key of ['window', 'document', 'HTMLElement', 'Element', 'Node', 'MutationObserver']) globalThis[key] = key === 'window' ? dom.window : dom.window[key];
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator });
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
globalThis.ResizeObserver = class { observe() {} disconnect() {} };
const React = require('react');
const { createRoot } = require('react-dom/client');
const { Simulate } = require('react-dom/test-utils');
const h = React.createElement;
const { act } = React;
const Empty = () => null;
const Icon = ({ size = 16, ...props }) => h('svg', { width: size, height: size, ...props });
const t = (key, fallback) => typeof fallback === 'string' ? fallback : fallback?.defaultValue || key;
const navigation = [];
const style = new Proxy({}, { get: (_, key) => String(key) });
const Popover = ({ children, open, onOpenChange, content }) => h(React.Fragment, null,
  h('span', { onClick: () => onOpenChange?.(!open) }, children), open ? content : null);
const Tooltip = ({ children }) => children;
const source = fs.readFileSync(new URL('../../dashboard/src/pages/Chat/components/ChatInputActionsRow.tsx', import.meta.url), 'utf8');
const icons = Object.fromEntries(source.match(/import \{([^{}]*)\} from "lucide-react";/)[1].split(',').map(name => [name.trim(), Icon]));
const dependencies = {
  react: React,
  'react/jsx-runtime': require('react/jsx-runtime'),
  'react-i18next': { useTranslation: () => ({ t }) },
  'react-router-dom': { useNavigate: () => path => navigation.push(path) },
  'lucide-react': icons,
  antd: { Popover, Tooltip },
};
const sourceRequire = name => {
  if (name in dependencies) return dependencies[name];
  if (name.endsWith('modelOptions')) return { modelOptionLabel, modelOptionValue, modelShortLabel };
  if (name.endsWith('assets/providers')) return { getProviderLogo: () => null, customProviderLogo: 'provider.svg' };
  if (name.endsWith('antdMessage')) return { message: { info() {} } };
  if (name.endsWith('ConversationModePicker')) return { ConversationModeMenu: Empty, conversationModeIcon: () => Icon };
  if (name.endsWith('slashShortcutStyles')) return { SHORTCUT_ICON_TONE_CLASS: {} };
  if (name.endsWith('useVoiceInput')) return { isSttAvailable: () => true };
  if (name.endsWith('skillSlash')) return { parseSkillSlugsInText: () => [] };
  if (name.endsWith('skillDisplayNames')) return { useSkillDisplayName: () => skill => skill.name || skill.slug };
  if (name.endsWith('expertMention')) return { mentionedExpertIds: () => [], mentionedSubagentSlugs: () => [] };
  if (name.endsWith('.less')) return { __esModule: true, default: style };
  if (name.endsWith('.css')) return {};
  if (name.startsWith('./')) return { __esModule: true, default: Empty };
  throw new Error(`Unexpected source dependency: ${name}`);
};
const compiled = require('esbuild').transformSync(source, { loader: 'tsx', format: 'cjs', jsx: 'automatic', target: 'es2022' }).code;
const module = { exports: {} };
new Function('module', 'exports', 'require', compiled)(module, module.exports, sourceRequire);
const Component = module.exports.default;
const models = [
  { provider_name: 'Provider', provider_kind: 'openai', model: 'compact-model', name: 'Compact Model' },
  { provider_name: 'Other', provider_kind: 'openai', model: 'other-model', name: 'Other Model' },
];
let active;
async function mount(overrides = {}) {
  const container = document.createElement('div'); document.body.append(container);
  const root = createRoot(container);
  const changed = [], sent = [];
  const props = { isMobile: false, isStreaming: false, canSend: false, text: 'Draft stays', polishing: false,
    uploading: false, recording: false, transcribing: false, selectedModel: null, defaultModel: 'Provider/compact-model',
    availableModels: models, onModelChange: value => changed.push(value), onSubmit: () => sent.push(true),
    onFileSelect() {}, onFolderSelect() {}, onNewChat() {}, onPolish() {}, onToggleVoice() {}, onCancel() {},
    slashPickerGroups: null, slashMenuItems: [], onSlashShortcutSelect() {}, ...overrides };
  const view = {
    container, changed, sent, props,
    button() { return container.querySelector('[data-testid="composer-model-shortcut"]'); },
    menu() { return container.querySelector('[role="dialog"][aria-label="Model"]'); },
    async click(node) { assert.ok(node); await act(async () => node.click()); },
    async render(next) { Object.assign(props, next); await act(async () => root.render(h(Component, props))); },
    async destroy() { await act(async () => root.unmount()); container.remove(); },
  };
  active = view; await view.render({}); return view;
}
let passed = 0;
async function test(name, task) {
  try { await task(); passed++; console.log(`PASS ${name}`); }
  finally { if (active) { await active.destroy(); active = null; } }
}
try {
  await test('source TSX displays actual default without changing the Auto override', async () => {
    const v = await mount();
    assert.equal(v.button().textContent, 'Compact Model');
    assert.equal(v.button().getAttribute('aria-label'), 'Model: Auto · Provider / Compact Model');
    assert.equal(v.button().type, 'button'); assert.deepEqual(v.changed, []);
  });
  await test('source TSX opens the existing menu and changes only the composer model', async () => {
    const v = await mount(); await v.click(v.button());
    assert.ok(v.menu().querySelector('input[placeholder="Search models"]'));
    const choice = [...v.menu().querySelectorAll('button')].find(b => b.textContent === 'Other / Other Model');
    await v.click(choice);
    assert.deepEqual(v.changed, ['Other/other-model']); assert.deepEqual(v.sent, []); assert.deepEqual(navigation, []); assert.equal(v.menu(), null);
    await v.render({ selectedModel: v.changed[0] }); assert.equal(v.button().textContent, 'Other Model');
  });
  await test('source TSX preserves model search and Auto callbacks', async () => {
    const v = await mount({ selectedModel: 'Other/other-model' }); await v.click(v.button());
    const search = v.menu().querySelector('input');
    await act(async () => Simulate.change(search, { target: { value: 'compact' } }));
    assert.ok(v.menu().textContent.includes('Provider / Compact Model'));
    assert.ok(!v.menu().textContent.includes('Other / Other Model'));
    await act(async () => Simulate.change(search, { target: { value: '' } }));
    await v.click([...v.menu().querySelectorAll('button')].find(b => b.textContent.startsWith('Auto')));
    assert.deepEqual(v.changed, [null]);
  });
  await test('source TSX allows the next model during streaming without sending or cancelling', async () => {
    const v = await mount({ isStreaming: true }); assert.equal(v.button().disabled, false); await v.click(v.button());
    await v.click([...v.menu().querySelectorAll('button')].find(b => b.textContent === 'Other / Other Model'));
    assert.deepEqual(v.changed, ['Other/other-model']); assert.deepEqual(v.sent, []);
  });
  await test('source TSX honors disabled and closes a menu when disabled', async () => {
    const v = await mount(); await v.click(v.button()); assert.ok(v.menu());
    await v.render({ disabled: true }); assert.equal(v.button().disabled, true); assert.equal(v.menu(), null);
    await v.click(v.button()); assert.equal(v.menu(), null); assert.deepEqual(v.changed, []);
  });
  await test('source TSX hides unavailable pickers and never invents a selected model', async () => {
    const v = await mount({ availableModels: undefined }); assert.equal(v.button(), null);
    await v.render({ availableModels: [] }); assert.equal(v.button(), null);
    await v.render({ availableModels: models, onModelChange: undefined }); assert.equal(v.button(), null);
    assert.deepEqual(v.changed, []);
  });
  await test('source TSX retains accessible full refs in compact mode', async () => {
    const v = await mount({ isMobile: true, selectedModel: 'Provider/org/very-long-model' });
    assert.equal(v.button().textContent, 'very-long-model');
    assert.equal(v.button().dataset.compact, 'true');
    assert.equal(v.button().getAttribute('aria-label'), 'Model: Provider/org/very-long-model');
  });
  await test('source TSX coordinates the quick menu with More tools', async () => {
    const v = await mount(); await v.click(v.button()); assert.ok(v.menu());
    await v.click(v.container.querySelector('[data-testid="composer-plus"]')); assert.equal(v.menu(), null);
  });
  console.log(`PASS ${passed} real React source component checks; no testing-library peer or new package required.`);
} finally { if (active) await active.destroy(); dom.window.close(); }
