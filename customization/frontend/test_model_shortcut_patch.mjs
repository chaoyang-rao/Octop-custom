import assert from 'node:assert/strict';
import fs from 'node:fs';
import { patchComposerModelShortcut } from './model-shortcut-patch.mjs';
import { m as modelOptionLabel, e as modelOptionValue, c as modelShortLabel } from '../baselines/projects-v2/octop/dashboard/assets/modelOptions.BrFzajT7.projects-v2.js';

const original = fs.readFileSync(new URL('../baselines/projects-v2/octop/dashboard/assets/index.G9_xhF8C.projects-v2.js', import.meta.url), 'utf8');
const patched = patchComposerModelShortcut(original);
const start = patched.indexOf('function ChatInputActionsRow(');
const end = patched.indexOf('function previewText(', start);
const oldStart = original.indexOf('function ChatInputActionsRow(');
const oldEnd = original.indexOf('function previewText(', oldStart);
assert.equal(patched.slice(0, start), original.slice(0, oldStart));
assert.equal(patched.slice(end), original.slice(oldEnd));
const menu = source => source.slice(source.indexOf('modelMenu=jsxRuntimeExports'), source.indexOf(',shortcutMenu=', source.indexOf('modelMenu=jsxRuntimeExports')));
assert.equal(menu(patched), menu(original), 'The authoritative model selector and callbacks must remain byte-identical');
assert.throws(() => patchComposerModelShortcut(patched), /already patched/);
assert.throws(() => patchComposerModelShortcut(''), /boundary changed/);

const Icon = () => null;
const Tooltip = () => null;
const Popover = () => null;
const nodes = (tree, predicate) => {
  if (Array.isArray(tree)) return tree.flatMap(child => nodes(child, predicate));
  if (!tree || typeof tree !== 'object') return [];
  return [...(predicate(tree) ? [tree] : []), ...nodes(tree.props?.children, predicate)];
};
const content = tree => typeof tree === 'string' ? tree : Array.isArray(tree) ? tree.map(content).join('') : tree && typeof tree === 'object' ? content(tree.props?.children) : '';
const element = (type, props, key) => ({ type, props: { ...props, key } });
let values, cursor, effects;
const changed = [], submitted = [], navigated = [];
const deps = {
  reactExports: {
    useState(initial) {
      const index = cursor++;
      if (!(index in values)) values[index] = typeof initial === 'function' ? initial() : initial;
      return [values[index], value => { values[index] = typeof value === 'function' ? value(values[index]) : value; }];
    },
    useRef: current => ({ current }), useMemo: fn => fn(),
    useEffect: fn => effects.push(fn), useLayoutEffect() {},
  },
  jsxRuntimeExports: { jsx: element, jsxs: element, Fragment: 'fragment' },
  chatStyles: new Proxy({}, { get: (_, key) => String(key) }),
  useTranslation: () => ({ t: (key, fallback) => fallback ?? key }),
  useNavigate: () => path => navigated.push(path),
  useSkillDisplayName: () => skill => skill.name || skill.slug,
  mentionedExpertIds: () => [], mentionedSubagentSlugs: () => [], parseSkillSlugsInText: () => [],
  conversationModeIcon: () => Icon, _sttAvailable: true,
  resolveModelLogo: () => 'provider.svg',
  modelOptionLabel, modelOptionValue, modelShortLabel,
  Tooltip, Popover, SHORTCUT_ICON_TONE_CLASS: {}, message: { info() {} },
};
for (const match of patched.slice(start, end).matchAll(/jsxRuntimeExports\.jsxs?\(([A-Z][A-Za-z0-9_$]*),/g)) {
  deps[match[1]] ??= Icon;
}
const Component = new Function('deps', `with(deps){${patched.slice(start, end)};return ChatInputActionsRow;}`)(deps);
const models = [
  { provider_name: 'Provider', provider_kind: 'openai', model: 'org/compact-model', name: 'Compact Model' },
  { provider_name: 'Other', provider_kind: 'openai', model: 'other-model', name: 'Other Model' },
];
const base = {
  isMobile: false, isStreaming: false, canSend: false, text: 'Draft stays here',
  polishing: false, uploading: false, recording: false, transcribing: false,
  availableModels: models, selectedModel: 'Provider/org/compact-model',
  onModelChange: value => changed.push(value), onSubmit: () => submitted.push('submit'),
  slashPickerGroups: null, slashMenuItems: [], onFileSelect() {}, onFolderSelect() {},
  onNewChat() {}, onPolish() {}, onToggleVoice() {}, onCancel() {}, onSlashShortcutSelect() {},
};
const reset = () => { values = []; changed.length = submitted.length = navigated.length = 0; };
const render = (overrides = {}) => {
  cursor = 0; effects = [];
  const tree = Component({ ...base, ...overrides });
  effects.forEach(fn => fn());
  return tree;
};
const trigger = tree => nodes(tree, node => node.props?.['data-testid'] === 'composer-model-shortcut')[0];
const picker = tree => nodes(tree, node => node.type === Popover && node.props?.content?.props?.role === 'dialog')[0];
const menuButton = (tree, name) => nodes(tree, node => node.type === 'button' && content(node).includes(name))[0];

reset();
let tree = render();
assert.equal(content(trigger(tree)), 'Compact Model');
assert.equal(trigger(tree).props.type, 'button');
assert.match(trigger(tree).props['aria-label'], /Provider \/ Compact Model/);
assert.equal(picker(tree).props.open, false);
picker(tree).props.onOpenChange(true);
tree = render();
assert.equal(picker(tree).props.open, true);
menuButton(picker(tree).props.content, 'Other / Other Model').props.onClick();
assert.deepEqual(changed, ['Other/other-model']);
assert.equal(picker(render()).props.open, false);
assert.deepEqual(submitted, []);

reset();
tree = render({ selectedModel: null, defaultModel: 'Provider/org/compact-model' });
assert.equal(content(trigger(tree)), 'Compact Model');
assert.match(trigger(tree).props['aria-label'], /Auto · Provider \/ Compact Model/);
picker(tree).props.onOpenChange(true);
tree = render({ selectedModel: null, defaultModel: 'Provider/org/compact-model' });
menuButton(picker(tree).props.content, 'Auto').props.onClick();
assert.deepEqual(changed, [null], 'Auto retains the existing null override behavior');

reset();
tree = render();
picker(tree).props.onOpenChange(true);
tree = render();
menuButton(picker(tree).props.content, 'Provider / Compact Model').props.onClick();
assert.deepEqual(changed, [null], 'Clicking the active row retains the original toggle-to-auto behavior');

reset();
tree = render({ selectedModel: null, defaultModel: null });
assert.equal(content(trigger(tree)), 'Auto');
assert.deepEqual(changed, []);
assert.equal(trigger(render({ availableModels: undefined })), undefined);
assert.equal(trigger(render({ availableModels: [] })), undefined);
assert.equal(trigger(render({ onModelChange: undefined })), undefined);

reset();
tree = render({ disabled: true });
assert.equal(trigger(tree).props.disabled, true);
picker(tree).props.onOpenChange(true);
assert.equal(picker(render({ disabled: true })).props.open, false);
assert.deepEqual(changed, []);

reset();
tree = render({ isStreaming: true });
assert.notEqual(trigger(tree).props.disabled, true);
picker(tree).props.onOpenChange(true);
tree = render({ isStreaming: true });
menuButton(picker(tree).props.content, 'Other / Other Model').props.onClick();
assert.deepEqual(changed, ['Other/other-model']);
assert.deepEqual(submitted, [], 'Choosing the next turn model never sends the draft');

reset();
tree = render({ isMobile: true, selectedModel: 'Provider/very-long/model-without-alias' });
assert.equal(trigger(tree).props['data-compact'], true);
assert.equal(content(trigger(tree)), 'model-without-alias');
assert.match(trigger(tree).props['aria-label'], /Provider\/very-long\/model-without-alias/);

reset();
tree = render();
picker(tree).props.onOpenChange(true);
tree = render();
const plus = nodes(tree, node => node.type === Popover && node.props?.overlayClassName === 'plusMenuPopover')[0];
plus.props.onOpenChange(true);
assert.equal(picker(render()).props.open, false, 'Opening More tools dismisses the quick model popover');

assert.equal(fs.readFileSync(new URL('../../dashboard/src/pages/Chat/components/ChatInputModelShortcut.css', import.meta.url), 'utf8'),
  fs.readFileSync(new URL('../packages/octop/dashboard/assets/model-shortcut.css', import.meta.url), 'utf8'));
console.log('PASS existing model menu identity, friendly/current/default labels, popup lifecycle, exact selection/Auto callbacks, unavailable/disabled states, streaming-next-turn semantics, compact labels and no accidental send');
