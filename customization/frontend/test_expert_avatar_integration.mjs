import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createAvatarSettings, userBubblePresentation } from '../packages/octop/dashboard/assets/expert-avatar-integration.js';

const calls = [];
const bubbleStyle = color => { calls.push(color); return { backgroundColor: '#19B7A2', color: '#0B101B' }; };
assert.deepEqual(userBubblePresentation({ avatar_shape: 'blob', avatar_color: 'jade' }, true, bubbleStyle), {});
assert.deepEqual(userBubblePresentation({ avatar_shape: null, avatar_color: 'jade' }, false, bubbleStyle), {});
assert.deepEqual(userBubblePresentation({ avatar_shape: 'unrecognized', avatar_color: 'jade' }, false, bubbleStyle), {});
assert.equal(calls.length, 0, 'Team rooms and original-image experts must not acquire bubble styling');
const styled = userBubblePresentation({ avatar_shape: 'blob', avatar_color: 'jade' }, false, bubbleStyle);
assert.equal(styled['data-expert-color'], 'jade');
assert.equal(styled.style.backgroundColor, '#19B7A2');
assert.equal(styled.style.color, '#0B101B');
assert.equal(styled.style['--expert-selection-background'], '#0B101B');
assert.equal(styled.style['--expert-selection-foreground'], '#19B7A2');
userBubblePresentation({ avatar_shape: 'triangle', avatar_color: null }, false, bubbleStyle);
assert.equal(calls.at(-1), 'ink');

const React = { createElement: (type, props, ...children) => ({ type, props: { ...props, children } }) };
const Picker = () => null;
const Settings = createAvatarSettings({ React, avatars: { ShapeColorPicker: Picker } });
const shapeChange = () => {}, colorChange = () => {}, useImage = () => {};
const tree = Settings({ shape: 'star', color: 'amber', onShapeChange: shapeChange, onColorChange: colorChange,
  imagePicker: { type: 'original-upload-picker' }, hasImage: true, onUseImage: useImage });
const picker = tree.props.children[0];
assert.equal(picker.type, Picker);
assert.equal(picker.props.shape, 'star');
assert.equal(picker.props.color, 'amber');
assert.equal(picker.props.onShapeChange, shapeChange);
assert.equal(picker.props.onColorChange, colorChange);
assert.equal(tree.props.children.length, 2, 'Expert settings contain only shape/color selection and randomize');
assert.equal(tree.props.children[1].type, 'button');
assert.ok(!JSON.stringify(tree).includes('original-upload-picker'), 'Old expert upload UI is not rendered');

const root = path.dirname(fileURLToPath(import.meta.url));
const manifestPath = path.join(root, 'avatar-asset-release.json');
if (fs.existsSync(manifestPath)) {
  const release = JSON.parse(fs.readFileSync(manifestPath));
  const assets = path.join(root, '../packages/octop/dashboard/assets');
  assert.equal(release.assets.length, 217 + (release.additional_assets?.length ?? 4), 'Only the active baseline graph and explicitly registered helper assets are versioned');
  assert.equal(new Set(release.assets).size, release.assets.length, 'Release assets must be unique');
  for (const name of release.assets.filter(name => name.endsWith('.js'))) {
    const source = fs.readFileSync(path.join(assets, name), 'utf8');
    assert.ok(!source.includes('.projects-v2.js'), `Old module graph reference: ${name}`);
    for (const match of source.matchAll(/(?:from\s*|import\s*\()?["']\.\/([^"']+\.(?:js|css))["']/g)) {
      assert.ok(fs.existsSync(path.join(assets, match[1])), `Missing module ${match[1]} in ${name}`);
    }
  }
  const messages = fs.readFileSync(path.join(assets, `index.Bexwf9h5.${release.release}.js`), 'utf8');
  assert.ok(messages.includes('className:chatStyles.userText,...userBubblePresentation(activeAgent,isTeamRoom,expertAvatarUi.bubbleStyle)'));
  const main = fs.readFileSync(path.join(assets, release.main), 'utf8');
  for (const wrapper of ['ExpertIcon','ExpertAgentAvatar']) {
    const start=main.indexOf(`function ${wrapper}(props){`);
    const end=main.indexOf(`function Legacy${wrapper}(`,start);
    const body=main.slice(start,end);
    assert.ok(body.includes('jsxRuntimeExports.jsx(expertPresentation.ExpertPortrait,props)'), 'Every expert image mounts the geometry-only portrait through React');
    assert.ok(!body.includes('useAuthImageSrc') && !body.includes('reactExports.use'), 'Wrapper never conditionally invokes hooks');
  }
  assert.ok(main.includes('createProjectFolders'), 'Existing project folders customization must remain');
  assert.ok(main.includes('sso') || main.includes('SSO'), 'The saved desktop SSO customization must remain');
}
console.log('PASS avatar picker binding, private uploaded-image retention, solo-only user bubble style, team and account scope, selection contrast' + (fs.existsSync(manifestPath) ? ', versioned graph and previous customizations' : ' (graph checks run after build)'));
