/** Small form and chat integration layer for Octop's original avatar library. */
const AVATAR_SHAPES = new Set(['blob', 'pebble', 'squircle', 'droplet', 'cloud', 'star', 'triangle']);

export function userBubblePresentation(agent, isTeamRoom, bubbleStyle) {
  if (isTeamRoom || !agent || !AVATAR_SHAPES.has(agent.avatar_shape)) return {};
  const colors = bubbleStyle(agent.avatar_color || 'ink');
  return {
    'data-expert-color': agent.avatar_color || 'ink',
    style: {
      ...colors,
      '--expert-selection-background': colors.color,
      '--expert-selection-foreground': colors.backgroundColor,
    },
  };
}

export function createAvatarSettings({ React, avatars }) {
  const h = React.createElement;
  return function AvatarSettings({ shape, color, onShapeChange, onColorChange,
    disabled = false, imagePicker, hasImage, onUseImage }) {
    return h('div', { className: 'octop-avatar-settings' },
      h(avatars.ShapeColorPicker, { shape, color: color || 'ink', onShapeChange, onColorChange, disabled }),
      !shape ? h('p', { className: 'octop-avatar-mode-hint' }, '当前使用图片或原头像，选择形状即可启用动态头像。') : null,
      h('details', { className: 'octop-avatar-image-options' },
        h('summary', null, '图片头像'),
        h('div', { className: 'octop-avatar-image-body' }, imagePicker,
          shape && hasImage ? h('button', { type: 'button', disabled, className: 'octop-avatar-restore-image', onClick: onUseImage }, '使用已上传图片') : null)));
  };
}
