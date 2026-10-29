import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { createProjectFolderPicker } from '../packages/octop/dashboard/assets/project-folder-picker.js';

// Use the same real React and jsdom dependencies as the existing dashboard.
const require = createRequire(new URL('../../dashboard/package.json', import.meta.url));
const { JSDOM } = require('jsdom');
const dom = new JSDOM('<!doctype html><body></body>', { url: 'http://localhost/' });
for (const name of ['window', 'document', 'HTMLElement', 'Node', 'MutationObserver']) globalThis[name] = name === 'window' ? dom.window : dom.window[name];
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator });
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const React = require('react');
const { createRoot } = require('react-dom/client');
const { Simulate } = require('react-dom/test-utils');
const { act } = React;
const h = React.createElement;
const views = new Set();
let passed = 0;
const defaults = roots => ({ default_root_dir: roots[0], tree_root: roots[0], browse_roots: roots });
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const entries = (path, children = []) => ({ path, entries: children.map(([name, value]) => ({ name, path: value })) });
const settle = () => act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); });

async function mount(handler, initialPath = '') {
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  const calls = [], selected = [], closed = [];
  const Dialog = ({ title, busy, onClose, children }) => {
    assert.equal(busy, false, 'Closing the chooser must remain possible while browsing');
    return h('section', { role: 'dialog', 'aria-label': title }, h('button', { 'aria-label': '关闭选择器', onClick: onClose }, '×'), children);
  };
  const Component = createProjectFolderPicker({ React, Dialog, readableError: error => error.message,
    request: (url, options) => {
      assert.ok(!options?.method || options.method === 'GET', 'The chooser must never write to the filesystem');
      assert.ok(url === '/filesystem/defaults' || url.startsWith('/filesystem/dirs?path='));
      calls.push({ url, options });
      return handler(url === '/filesystem/defaults' ? null : new URL(url, 'http://localhost').searchParams.get('path'), url);
    } });
  const view = {
    container, calls, selected, closed,
    button(text) { const value = [...container.querySelectorAll('button')].find(node => node.textContent === text || node.getAttribute('aria-label') === text); assert.ok(value, `Missing button ${text}`); return value; },
    input() { return container.querySelector('input[aria-label="文件夹位置"]'); },
    text() { return container.textContent; },
    async click(text) { await act(async () => view.button(text).click()); await settle(); },
    async folder(path) { const button = [...container.querySelectorAll('button[title]')].find(node => node.title === path); assert.ok(button, `Missing folder ${path}`); await act(async () => button.click()); await settle(); },
    async draft(value) { await act(async () => Simulate.change(view.input(), { target: { value } })); },
    async enter() { await act(async () => Simulate.keyDown(view.input(), { key: 'Enter', nativeEvent: { isComposing: false } })); await settle(); },
    async drive(value) { const select = container.querySelector('select'); assert.ok([...select.options].some(option => option.value === value)); await act(async () => Simulate.change(select, { target: { value } })); await settle(); },
    async destroy() { if (!views.has(view)) return; await act(async () => root.unmount()); container.remove(); views.delete(view); },
  };
  views.add(view);
  await act(async () => root.render(h(Component, { initialPath, onSelect: path => selected.push(path), onClose: () => closed.push(true) })));
  await settle();
  return view;
}

async function test(name, task) {
  try { await task(); passed++; console.log(`PASS ${name}`); }
  finally { for (const view of [...views]) await view.destroy(); }
}

try {
  await test('home default, canonical result and exactly one confirmation', async () => {
    const view = await mount(path => path === null ? defaults(['/']) : entries('/Users/test'));
    assert.equal(new URL(view.calls[1].url, 'http://localhost').searchParams.get('path'), '~');
    assert.equal(view.input().value, '/Users/test');
    assert.match(view.text(), /没有子文件夹/);
    await view.click('选择此文件夹'); await view.click('选择此文件夹');
    assert.deepEqual(view.selected, ['/Users/test']);
    assert.equal(view.calls.length, 2);
    assert.equal(view.closed.length, 0);
  });

  await test('directory navigation and cancellation preserve the outer value', async () => {
    const view = await mount(path => path === null ? defaults(['/']) : path === '~' || path === '/home/me'
      ? entries('/home/me', [['项目 A', '/home/me/项目 A']]) : entries(path), '/home/me');
    await view.folder('/home/me/项目 A');
    assert.equal(view.input().value, '/home/me/项目 A');
    await view.click('上一级文件夹');
    assert.equal(view.input().value, '/home/me');
    await view.click('取消');
    assert.deepEqual(view.selected, []);
    assert.equal(view.closed.length, 1);
  });

  await test('Windows drives, drive-root parent boundary and backslash input', async () => {
    const view = await mount(path => path === null ? defaults(['C:/', 'D:/']) : path === '~'
      ? entries('C:/Users/Test') : path === 'D:/' ? entries('D:/', [['src', 'D:/src']]) : entries(path));
    assert.equal(view.container.querySelector('select').value, 'C:/');
    await view.drive('D:/');
    assert.equal(view.button('上一级文件夹').disabled, true);
    await view.folder('D:/src');
    await view.click('上一级文件夹');
    assert.equal(view.input().value, 'D:/');
    assert.equal(view.button('上一级文件夹').disabled, true);
    await view.draft('D:\\new\\项目 A');
    await view.click('选择此文件夹');
    assert.deepEqual(view.selected, ['D:/new/项目 A']);
    assert.ok(view.calls.some(call => call.url.includes('D%3A%2Fnew%2F')));
  });

  await test('policy root is the default and upward navigation stays within it', async () => {
    const view = await mount(path => {
      if (path === null) return defaults(['/allowed']);
      assert.ok(path === '/allowed' || path === '/allowed/sub');
      return entries(path, path === '/allowed' ? [['sub', '/allowed/sub']] : []);
    });
    assert.equal(view.input().value, '/allowed');
    assert.equal(view.button('上一级文件夹').disabled, true);
    await view.folder('/allowed/sub'); await view.click('上一级文件夹');
    assert.equal(view.input().value, '/allowed');
    assert.equal(view.button('上一级文件夹').disabled, true);
  });

  await test('edited location is verified before confirming, using the returned canonical path', async () => {
    const view = await mount(path => path === null ? defaults(['/']) : path === '~/docs'
      ? entries('/home/me/docs') : entries('/resolved/new'), '~/docs');
    assert.equal(view.input().value, '/home/me/docs');
    await view.draft('/link/new'); await view.click('选择此文件夹');
    assert.deepEqual(view.selected, ['/resolved/new']);
    assert.equal(new URL(view.calls.at(-1).url, 'http://localhost').searchParams.get('path'), '/link/new');
  });

  await test('lookup failures never select the previously displayed folder and can recover', async () => {
    const view = await mount(path => {
      if (path === null) return defaults(['/']);
      if (path === '/missing') throw new Error('folder unavailable');
      return entries(path === '~' ? '/home/me' : path);
    });
    await view.draft('/missing'); await view.click('前往');
    assert.match(view.container.querySelector('[role="alert"]').textContent, /folder unavailable/);
    await view.click('选择此文件夹');
    assert.deepEqual(view.selected, []);
    await view.drive('/'); await view.click('选择此文件夹');
    assert.deepEqual(view.selected, ['/']);
  });

  await test('defaults error can retry without dropping the initially entered path', async () => {
    let attempts = 0;
    const view = await mount(path => {
      if (path === null) { if (++attempts === 1) throw new Error('temporary error'); return defaults(['/']); }
      assert.equal(path, '/original/项目'); return entries(path);
    }, '/original/项目');
    assert.equal(view.input().value, '/original/项目');
    assert.equal(view.button('选择此文件夹').disabled, true);
    await view.click('重试');
    assert.equal(view.input().value, '/original/项目');
    assert.equal(view.container.querySelector('[role="alert"]'), null);
  });

  await test('stale directory responses and errors cannot replace the latest navigation', async () => {
    const home = deferred(), c = deferred(), d = deferred();
    const view = await mount(path => path === null ? defaults(['C:/', 'D:/']) : path === '~' ? home.promise : path === 'D:/' ? d.promise : c.promise);
    await view.drive('D:/'); await view.drive('C:/');
    await act(async () => c.resolve(entries('C:/'))); await settle();
    await act(async () => d.reject(new Error('stale directory error'))); await settle();
    await act(async () => home.resolve(entries('C:/Users/old'))); await settle();
    assert.equal(view.input().value, 'C:/');
    assert.equal(view.container.querySelector('[role="alert"]'), null);
    await view.click('选择此文件夹');
    assert.deepEqual(view.selected, ['C:/']);
  });

  await test('duplicate Go/Enter requests and confirmation while loading are blocked', async () => {
    const slow = deferred();
    const view = await mount(path => path === null ? defaults(['/']) : path === '/slow' ? slow.promise : entries('/home/me'));
    await view.draft('/slow'); await view.click('前往');
    await view.click('前往'); await view.enter(); await view.click('选择此文件夹');
    assert.equal(view.calls.filter(call => call.url.includes('%2Fslow')).length, 1);
    assert.deepEqual(view.selected, []);
    await act(async () => slow.resolve(entries('/slow'))); await settle();
    await view.click('选择此文件夹');
    assert.deepEqual(view.selected, ['/slow']);
  });

  await test('editing again during confirmation does not choose the obsolete draft', async () => {
    const pending = deferred();
    const view = await mount(path => path === null ? defaults(['/']) : path === '/first' ? pending.promise : entries(path === '~' ? '/home/me' : path));
    await view.draft('/first'); await view.click('选择此文件夹');
    await view.draft('/second');
    await act(async () => pending.resolve(entries('/first'))); await settle();
    assert.deepEqual(view.selected, []);
    assert.equal(view.input().value, '/second');
    await view.click('选择此文件夹');
    assert.deepEqual(view.selected, ['/second']);
  });

  await test('invalid new navigation invalidates an older pending lookup', async () => {
    const pending = deferred();
    const view = await mount(path => path === null ? defaults(['/']) : path === '/slow' ? pending.promise : entries('/home/me'));
    await view.draft('/slow'); await view.click('前往');
    await view.draft('relative'); await view.enter();
    await act(async () => pending.resolve(entries('/slow'))); await settle();
    assert.match(view.container.querySelector('[role="alert"]').textContent, /绝对路径/);
    assert.equal(view.input().value, 'relative');
    await view.click('选择此文件夹');
    assert.deepEqual(view.selected, []);
  });

  await test('closing ignores pending results and does not select or make later requests', async () => {
    const pending = deferred();
    const view = await mount(path => path === null ? defaults(['/']) : pending.promise);
    await view.click('取消'); await view.destroy();
    await act(async () => pending.resolve(entries('/late'))); await settle();
    assert.deepEqual(view.selected, []);
    assert.equal(view.closed.length, 1);
    assert.equal(view.calls.length, 2);
    const roots = deferred();
    const second = await mount(() => roots.promise);
    await second.click('关闭选择器'); await second.destroy();
    await act(async () => roots.resolve(defaults(['/']))); await settle();
    assert.equal(second.calls.length, 1, 'No directory request may start after closing');
    assert.deepEqual(second.selected, []);
  });

  console.log(`PASS ${passed} real React folder-picker behavior checks; all filesystem requests are read-only.`);
} finally {
  for (const view of [...views]) await view.destroy();
  dom.window.close();
}
