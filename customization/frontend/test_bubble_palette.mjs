import assert from 'node:assert/strict';
import {SHAPES,COLORS,avatarFrame,avatarUrl,parseAvatarUrl,bubbleStyle,contrast} from '../packages/octop/dashboard/assets/expert-avatars.js';

const lightColors={jade:'#19B7A2',rose:'#DB779A',amber:'#DCAA46',coral:'#E5805D'};
const darkColors=new Set(['ink','blue','violet']);
for(const color of COLORS){
  const bubble=bubbleStyle(color.id);
  assert.equal(bubble.color,darkColors.has(color.id)?'#FFFFFF':'#0B101B');
  assert.ok(contrast(color.hex,bubble.color)>=4.5,`${color.id} readable text`);
  if(lightColors[color.id])assert.equal(color.hex,lightColors[color.id],'Bright colors should not be unnecessarily darkened');
  for(const shape of SHAPES){
    assert.equal(avatarFrame(shape.id,color.id,0).base,bubble.backgroundColor,'Avatar and bubble use identical base color');
    assert.deepEqual(parseAvatarUrl(avatarUrl(shape.id,color.id)),{shape:shape.id,color:color.id});
    assert.deepEqual(parseAvatarUrl(`/expert-avatars/v1/${shape.id}-${color.id}.svg?v=old#cached`),{shape:shape.id,color:color.id});
  }
}
assert.equal(parseAvatarUrl('/expert-avatars/v3/blob-ink.svg'),null);
assert.equal(parseAvatarUrl('https://external.invalid/expert-avatars/v2/blob-ink.svg'),null);
console.log('PASS deep-color white text, bright-color dark text, >=4.5 contrast, identical avatar/bubble colors and v1/v2 compatibility');
