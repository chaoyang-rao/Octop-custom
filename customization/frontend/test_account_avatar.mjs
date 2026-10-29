import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { accountDisplayName, accountInitials, initialsFromName, createAccountAvatar }
  from '../packages/octop/dashboard/assets/account-avatar.js';

const cases = [
  ['', '我'], ['   ', '我'], [null, '我'], ['饶朝洋', '朝洋'], ['饶', '饶'],
  ['欧阳娜娜', '娜娜'], ['饶 朝洋', '朝洋'], ['Alice Smith', 'AS'],
  ['  alice   bob smith ', 'AS'], ['alice', 'AL'], ['A', 'A'], ['José da Silva', 'JS'],
  ['alice-smith', 'AS'], ['12345', '12'], ['🙂', '我'],
];
for (const [input, expected] of cases) assert.equal(initialsFromName(input), expected);
assert.equal(accountDisplayName({ display_name: '饶朝洋', username: 'rao' }), '饶朝洋');
assert.equal(accountInitials({ display_name: '  ', username: 'Alice Smith' }), 'AS');
assert.equal(accountInitials({ username: 'rao' }), 'RA');
assert.equal(accountInitials(undefined), '我');

const React = { createElement: (type, props, ...children) => ({ type, props: { ...props, children } }) };
let directProfileCalls = 0;
const ProfileAvatar = () => { directProfileCalls++; throw new Error('ProfileAvatar must be mounted through React'); };
const AccountInitialAvatar = createAccountAvatar({ React, ProfileAvatar });
const account = { display_name: '饶朝洋', username: 'rao', avatar_url: null, avatar_icon: null };
const result = AccountInitialAvatar({ user: account, className: 'keep-original-fixed-slot' });
assert.equal(result.type, 'span');
assert.equal(result.props.className, 'keep-original-fixed-slot');
assert.equal(result.props['aria-label'], '饶朝洋');
assert.deepEqual(result.props.children, ['朝洋']);
assert.equal(result.props.style.background, 'var(--fn-bg-secondary, rgba(128,128,128,.06))');
assert.equal(result.props.style.border, '1px solid var(--fn-border-primary, rgba(128,128,128,.26))');
assert.equal(result.props.style.borderRadius, '50%');
assert.equal(result.props.style.boxSizing, 'border-box');
assert.equal(result.props.style.aspectRatio, '1 / 1');
assert.equal(result.props.style.width, result.props.style.height);
assert.equal(result.props.style.width, 'var(--account-avatar-size, 32px)');
assert.equal(result.props.style.boxShadow, 'none');
assert.equal(result.props.style.color, 'var(--fn-text-primary)');
assert.deepEqual(AccountInitialAvatar({ user: { display_name: 'Alice Smith' } }).props.children, ['AS']);
const imageUser = { ...account, avatar_url: ' /old.png ', avatar_icon: 'staff' };
const photo = AccountInitialAvatar({ user: imageUser, className: 'existing-image-slot' });
assert.equal(photo.type, ProfileAvatar);
assert.equal(photo.props.url, '/old.png', 'An uploaded image is passed to the original image-first renderer');
assert.equal(photo.props.icon, 'staff', 'The original preset may remain as image fallback');
assert.ok(photo.props.className.split(' ').includes('existing-image-slot'));
assert.ok(photo.props.className.split(' ').includes('octop-account-profile-avatar'), 'Uploaded and preset avatars retain the circular account frame');
assert.equal(photo.props.kind, 'user');
assert.equal(imageUser.avatar_url, ' /old.png ', 'Rendering must not mutate persisted account fields');
const builtin = AccountInitialAvatar({ user: { ...account, avatar_icon: 'doctor' } });
assert.equal(builtin.type, ProfileAvatar);
assert.equal(builtin.props.icon, 'doctor');
assert.equal(builtin.props.url, null);
assert.equal(AccountInitialAvatar({ user: { ...account, avatar_url: ' ', avatar_icon: '\t' } }).type, 'span');
assert.equal(directProfileCalls, 0, 'Image/preset modes must use a React component boundary rather than calling hook functions');

const root = path.dirname(fileURLToPath(import.meta.url));
const css = fs.readFileSync(path.join(root, '../packages/octop/dashboard/assets/account-avatar.css'), 'utf8');
assert.ok(css.includes('[data-octop-geometric-avatar]{'));
assert.ok(css.includes(':has(>svg[data-octop-geometric-avatar]:only-child)'));
assert.ok(css.includes('background:transparent!important'));
assert.ok(css.includes('overflow:visible!important'));
assert.ok(!css.includes('outline:'), 'Keyboard focus outlines must remain available');
assert.ok(!css.includes('path') && !css.includes('stroke:'), 'The character contour belongs to the art');
assert.ok(!css.includes('data-expert-color'), 'Account/frame styling must not touch message bubble colors');
assert.ok(css.includes('--account-avatar-size:32px;'), 'Dock avatar keeps a 32px circular slot');
assert.ok(css.includes('--account-avatar-size:min(36px,var(--chat-msg-avatar-slot,36px));'), 'Message avatar fits the current message slot');
assert.ok(css.includes('width:var(--account-avatar-size)!important;'));
assert.ok(css.includes('height:var(--account-avatar-size)!important;'));
assert.ok(css.includes('border-radius:50%!important;'));
assert.ok(css.includes('.octop-account-profile-avatar{'));
console.log('PASS account initials (15 cases), image/preset/name priority, React hook boundary, circular theme-aware 32/36px slots and geometry-only frameless scope');
