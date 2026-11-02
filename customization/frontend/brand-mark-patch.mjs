/**
 * Ship a monochrome brand: the collapsed sidebar rail used the coloured app
 * icon (`/pwa-192.png`), which reads as a solid block once the logo is forced
 * to black/white. Point it at the transparent glyph so it follows the theme
 * like the wordmark instead.
 */

const OLD = 'src:isRailCollapsed?"/pwa-192.png":wordmarkSrc';
const NEW = 'src:isRailCollapsed?(isDark?"/logo_mark_white.png":"/logo_mark_dark.png"):wordmarkSrc';

export function patchBrandMark(source) {
  const hits = source.split(OLD).length - 1;
  if (hits === 0) {
    if (source.includes('logo_mark_white.png')) return source;
    throw new Error('Collapsed brand logo anchor not found');
  }
  return source.split(OLD).join(NEW);
}

const WORDMARK = [
  ['"/logo_horizontal_white.png"', '"/logo_horizontal_white_mono.png"'],
  ['"/logo_horizontal_dark.png"', '"/logo_horizontal_dark_mono.png"'],
];

export function patchBrandWordmark(source) {
  return WORDMARK.reduce((text, [from, to]) => text.split(from).join(to), source);
}
