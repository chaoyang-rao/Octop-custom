import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { createAccountAvatar } from '../packages/octop/dashboard/assets/account-avatar.js';

const root = path.dirname(fileURLToPath(import.meta.url));
const mainFile = path.join(root, '../packages/octop/dashboard/assets/index.BsYGCvv_.avatars-v5.js');
const run = spawnSync('python3', ['-c',
  'from pathlib import Path; import runpy,sys; p=runpy.run_path(sys.argv[1]); print(p["patch_account_avatar_settings"](Path(sys.argv[2]).read_text()),end="")',
  path.join(root, 'account-avatar-settings-patch.py'), mainFile], { encoding: 'utf8', maxBuffer: 4 * 1024 * 1024 });
assert.equal(run.status, 0, run.stderr);
const main = run.stdout;
const h = (type, props, key) => ({ type, props: { ...props, key } });
let state = [], cursor = 0;
const React = {
  createElement: (type, props, ...children) => ({ type, props: { ...props, children } }),
  useState(initial) { const at = cursor++; if (!(at in state)) state[at] = initial; return [state[at], value => { state[at] = value; }]; },
  useRef: value => ({ current: value }), useEffect() {},
};
const marker = () => null;
const Account = createAccountAvatar({ React, ProfileAvatar: marker });
const deps = {
  jsxRuntimeExports: { jsx: h, jsxs: h }, reactExports: React,
  useTranslation: () => ({ t: key => key }),
  presetsFor: kind => kind === 'role'
    ? [{ id: 'member', labelKey: 'member', Icon: marker }, { id: 'award', labelKey: 'award', Icon: marker }]
    : [{ id: 'user', labelKey: 'user', Icon: marker }, { id: 'staff', labelKey: 'staff', src: '/staff.svg' }],
  ProfileAvatar: marker, AccountInitialAvatar: Account, Button: marker, ImagePlus: marker,
  styles$i: new Proxy({}, { get: (_, key) => key }),
};
const start = main.indexOf('function ProfileAvatarPicker(');
const end = main.indexOf('const menuPopover=', start);
const Picker = new Function('deps', `with(deps){${main.slice(start, end)};return ProfileAvatarPicker;}`)(deps);
function all(tree, predicate) {
  if (Array.isArray(tree)) return tree.flatMap(child => all(child, predicate));
  if (!tree || typeof tree !== 'object') return [];
  return [...(predicate(tree) ? [tree] : []), ...all(tree.props?.children, predicate)];
}
function render(props) { cursor = 0; return Picker(props); }
let chosen;
state = [null];
let tree = render({ kind: 'user', avatarUrl: null, icon: null, user: { display_name: '饶朝洋' }, onSelectIcon: value => { chosen = value; } });
let options = all(tree, node => node.type === 'button');
assert.equal(options.length, 3, 'The account name option is prepended without discarding existing built-ins');
assert.equal(options[0].props['aria-label'], '无图片（显示姓名）');
assert.equal(options[0].props['aria-pressed'], true);
assert.equal(options[1].props['aria-pressed'], false);
options[0].props.onClick();
assert.equal(chosen, null, 'Choosing name mode must use the nullable icon contract that also clears the active image');
options[1].props.onClick();
assert.equal(chosen, 'user', 'The former default user icon is now an explicit built-in selection');
options[2].props.onClick();
assert.equal(chosen, 'staff');
const preview = all(tree, node => node.type === Account)[0];
assert.equal(preview.props.user.display_name, '饶朝洋');
assert.equal(preview.props.user.avatar_url, null);
assert.equal(preview.props.user.avatar_icon, null);

state = [null];
tree = render({ kind: 'user', avatarUrl: '/uploaded.png', icon: 'staff' });
options = all(tree, node => node.type === 'button');
assert.ok(options.every(option => option.props['aria-pressed'] === false), 'An uploaded image must not falsely mark a preset as active');
state = [null];
tree = render({ kind: 'role', avatarUrl: null, icon: null, onSelectIcon: value => { chosen = value; } });
options = all(tree, node => node.type === 'button');
assert.equal(options.length, 2, 'Role selectors must retain their original option count');
assert.equal(options[0].props['aria-label'], 'adminUsers.avatarDefault');
assert.equal(options[0].props['aria-pressed'], true);
assert.equal(all(tree, node => node.type === Account).length, 0, 'Role previews must not use the account name fallback');

// Execute the actual current-account selection callback with a fake API to
// verify persisted response synchronization, plus optimistic rollback on error.
const callbackStart = main.indexOf('ProfileAvatarPicker,{kind:"user",user,avatarUrl:user.avatar_url,icon:user.avatar_icon,onSelectIcon:') + 'ProfileAvatarPicker,{kind:"user",user,avatarUrl:user.avatar_url,icon:user.avatar_icon,onSelectIcon:'.length;
const callbackEnd = main.indexOf(',onPick:async file=>', callbackStart);
const callbackSource = main.slice(callbackStart, callbackEnd);
const before = { id: 2, display_name: '饶朝洋', avatar_url: '/old.png', avatar_icon: 'staff' };
const updates = [], requests = [];
const persisted = { ...before, avatar_url: null, avatar_icon: null };
let reject = false;
const callback = new Function('user', 'onUserChange', 'authApi', 'message', 'apiErrorMessage', 't', `return (${callbackSource});`)(
  before, value => updates.push(value), { setAvatarIcon: async icon => { requests.push(icon); if (reject) throw Error('offline'); return { ...persisted, avatar_icon: icon }; } },
  { error() {} }, error => error.message, value => value);
await callback(null);
assert.deepEqual(requests, [null]);
assert.equal(updates[0].avatar_url, null);
assert.equal(updates[0].avatar_icon, null);
assert.deepEqual(updates.at(-1), persisted, 'The complete server response must replace CurrentUserContext');
await callback('doctor');
assert.equal(updates.at(-1).avatar_icon, 'doctor');
assert.equal(updates.at(-1).avatar_url, null);
reject = true;
await assert.rejects(() => callback(null), /offline/);
assert.equal(updates.at(-1), before, 'Failed selections must restore the previous visible account');
const uploadStart = callbackEnd + ',onPick:'.length;
const uploadEnd = main.indexOf(',onRemove:async()=>', uploadStart);
const uploadSource = main.slice(uploadStart, uploadEnd);
let uploaded;
const upload = new Function('user', 'onUserChange', 'authApi', 'message', 'apiErrorMessage', 't', `return (${uploadSource});`)(
  before, value => updates.push(value), { uploadAvatar: async file => { uploaded = file; return { avatar_url: '/new-image.png' }; } },
  { error() {} }, error => error.message, value => value);
const file = { name: 'avatar.png' };
await upload(file);
assert.equal(uploaded, file);
assert.equal(updates.at(-1).avatar_url, '/new-image.png');
assert.equal(updates.at(-1).avatar_icon, 'staff', 'The retained built-in must not override a newly uploaded image');
assert.equal(Account({ user: updates.at(-1) }).type, marker);
assert.equal(Account({ user: updates.at(-1) }).props.url, '/new-image.png');
console.log('PASS name-first user picker, all built-ins, uploaded-image context sync/priority, unchanged role picker, nullable clear/save synchronization and rollback');
