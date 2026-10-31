import { randomAvatar, portraitFor } from "./expert-presentation.avatars-v24.js";
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

export function createAvatarSettings({ React, avatars, useTranslation }) {
  const h = React.createElement;
  return function AvatarSettings({ shape, color, onShapeChange, onColorChange, disabled = false }) {
    const translation = useTranslation?.();
    const selected = shape ? {shape,color:color||'ink'} : portraitFor('expert',avatars);
    return h('div', { className: 'octop-avatar-settings' },
      h(avatars.ShapeColorPicker, { ...selected, onShapeChange, onColorChange, disabled }),
      h('button',{type:'button',disabled,className:'octop-avatar-random',onClick:()=>{const next=randomAvatar();onShapeChange(next.shape);onColorChange(next.color)}},translation?.t('experts.randomAvatar',{defaultValue:translation?.i18n?.language?.startsWith('zh')?'随机换一组':'Randomize avatar'})||'随机换一组'));
  };
}
