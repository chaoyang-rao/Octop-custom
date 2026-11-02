/**
 * Sidebar icon set "精工细线" (fine-line precision).
 *
 * Hand-drawn 24x24 geometry: 1.35px strokes, butt caps, miter joins, and a
 * secondary stroke at 72% opacity so each glyph stays legible at 16px while
 * remaining visually lighter than the previous lucide set. Colour is inherited
 * through `currentColor`, so active / dark / hover states keep working.
 */
export function createNavIcons({ React }) {
  const svg = (size, children) =>
    React.createElement(
      'svg',
      {
        width: size,
        height: size,
        viewBox: '0 0 24 24',
        fill: 'none',
        stroke: 'currentColor',
        strokeWidth: 1.35,
        strokeLinecap: 'butt',
        strokeLinejoin: 'miter',
        'aria-hidden': true,
        focusable: 'false',
        display: 'block',
      },
      children,
    );

  const path = (d, secondary) =>
    React.createElement('path', { key: d, d, strokeOpacity: secondary ? 0.72 : 1 });

  const line = (x1, y1, x2, y2, secondary) =>
    React.createElement('line', {
      key: `${x1}-${y1}-${x2}-${y2}`,
      x1,
      y1,
      x2,
      y2,
      strokeOpacity: secondary ? 0.72 : 1,
    });

  const circle = (cx, cy, r, secondary) =>
    React.createElement('circle', {
      key: `${cx}-${cy}-${r}`,
      cx,
      cy,
      r,
      strokeOpacity: secondary ? 0.72 : 1,
    });

  const rect = (x, y, w, h, rx, secondary) =>
    React.createElement('rect', {
      key: `${x}-${y}-${w}-${h}`,
      x,
      y,
      width: w,
      height: h,
      rx,
      strokeOpacity: secondary ? 0.72 : 1,
    });

  const GLYPHS = {
    chat: [
      path('M4.2 7a2.8 2.8 0 0 1 2.8-2.8h10a2.8 2.8 0 0 1 2.8 2.8v6.6a2.8 2.8 0 0 1-2.8 2.8H10.4L6.6 19.6V16.2A2.8 2.8 0 0 1 4.2 13.6z'),
      circle(8.4, 10.4, 1, true),
      circle(12, 10.4, 1, true),
      circle(15.6, 10.4, 1, true),
    ],
    conversations: [
      rect(3.2, 4.2, 12.6, 8.6, 2.4),
      rect(8.2, 10.4, 12.6, 8.6, 2.4, true),
      line(11.2, 15, 16.2, 15, true),
    ],
    experts: [
      circle(12, 8, 3),
      path('M5.4 19.2c0-3.4 3-6.1 6.6-6.1s6.6 2.7 6.6 6.1'),
      path('M19 3.4l.9 2 2 .9-2 .9-.9 2-.9-2-2-.9 2-.9z', true),
    ],
    tasks: [
      rect(4.6, 4.2, 14.8, 16.6, 2.6),
      rect(9, 2.6, 6, 2.6, 1.2),
      path('M8.4 11.6l1.9 1.9 3.9-3.9'),
      line(8.4, 17, 15.6, 17, true),
    ],
    'task-queue': [
      circle(10, 12, 6),
      path('M10 9.2V12l2.1 1.3'),
      line(17.4, 7.2, 21, 7.2, true),
      line(17.4, 12, 21, 12, true),
      line(17.4, 16.8, 21, 16.8, true),
    ],
    'token-usage': [
      rect(4, 13, 3.4, 7, 1),
      rect(10.3, 9, 3.4, 11, 1),
      rect(16.6, 4.6, 3.4, 15.4, 1, true),
    ],
    personalization: [
      path('M11 3.2l1.8 4.2 4.2 1.8-4.2 1.8L11 15.2 9.2 11 5 9.2 9.2 7.4z'),
      circle(17.2, 16.4, 2.3, true),
    ],
    channels: [
      circle(12, 12, 1.7),
      path('M7.6 8.4a6.2 6.2 0 0 1 8.8 0', true),
      path('M5 5.6a10.4 10.4 0 0 1 14 0', true),
      path('M12 14v3.4'),
    ],
    connectors: [
      path('M10.6 13.4a3.6 3.6 0 0 1 0-5.1l1.9-1.9a3.6 3.6 0 0 1 5.1 5.1l-1 1'),
      path('M13.4 10.6a3.6 3.6 0 0 1 0 5.1l-1.9 1.9a3.6 3.6 0 0 1-5.1-5.1l1-1', true),
    ],
    'account-connections': [
      circle(9.2, 8, 2.8),
      path('M3.8 18.6c0-2.9 2.4-5.2 5.4-5.2 1.6 0 3 .7 4 1.9'),
      path('M15.4 17.6a2.6 2.6 0 0 1 3.7-3.7l1 1a2.6 2.6 0 0 1-3.7 3.7', true),
    ],
    'mobile-access': [
      rect(7.6, 2.8, 8.8, 18.4, 2.6),
      line(10.8, 18.6, 13.2, 18.6),
      path('M17.8 7.4a6.4 6.4 0 0 1 0 9', true),
      path('M20.4 5a10 10 0 0 1 0 14', true),
    ],
    'skill-packages': [
      path('M12 2.8l8.2 4.6v9.2L12 21.2l-8.2-4.6V7.4z'),
      path('M3.8 7.4l8.2 4.6 8.2-4.6', true),
      path('M12 12v9.2', true),
    ],
    'knowledge-bases': [
      path('M4.4 5.2h6.2a2.6 2.6 0 0 1 2.6 2.6v12H7a2.6 2.6 0 0 1-2.6-2.6z'),
      path('M13.2 7.8a2.6 2.6 0 0 1 2.6-2.6h3.8v14.6h-6.4', true),
    ],
    bridge: [
      path('M3 18.6v-4.4a9 9 0 0 1 18 0v4.4'),
      line(3, 14.2, 21, 14.2, true),
      line(7.4, 14.2, 7.4, 18.6, true),
      line(16.6, 14.2, 16.6, 18.6, true),
    ],
    workbench: [
      rect(3.4, 4, 17.2, 16, 2.6),
      line(3.4, 9.6, 20.6, 9.6, true),
      line(9.6, 9.6, 9.6, 20, true),
    ],
    'remote-desktop': [
      rect(2.8, 4.4, 18.4, 12, 2.2),
      line(12, 16.4, 12, 19.8),
      line(8.2, 20.8, 15.8, 20.8),
      path('M15.6 11.4l-4.6 1.6 1.6-4.6 1 1z', true),
    ],
    acp: [
      circle(6.4, 7, 2.1),
      circle(17.6, 7, 2.1),
      circle(12, 17.6, 2.1),
      line(8.2, 8.1, 10.3, 15.6, true),
      line(15.8, 8.1, 13.7, 15.6, true),
    ],
    'admin-users': [
      circle(9, 8, 3),
      path('M3.2 19.4c0-3.2 2.6-5.8 5.8-5.8s5.8 2.6 5.8 5.8'),
      circle(17, 9, 2.4, true),
      path('M15.6 13.9c2.6.2 4.6 2.4 4.6 5', true),
    ],
    models: [
      rect(7, 7, 10, 10, 2.2),
      rect(10.2, 10.2, 3.6, 3.6, 1),
      line(10, 3.4, 10, 7, true),
      line(14, 3.4, 14, 7, true),
      line(10, 17, 10, 20.6, true),
      line(14, 17, 14, 20.6, true),
      line(3.4, 10, 7, 10, true),
      line(3.4, 14, 7, 14, true),
      line(17, 10, 20.6, 10, true),
      line(17, 14, 20.6, 14, true),
    ],
    'admin-storage': [
      rect(3.4, 4.4, 17.2, 6.2, 2),
      rect(3.4, 13.4, 17.2, 6.2, 2),
      circle(7, 7.5, 0.9, true),
      circle(7, 16.5, 0.9, true),
      line(11, 7.5, 17, 7.5, true),
      line(11, 16.5, 17, 16.5, true),
    ],
    'admin-plugins': [
      line(9, 3.2, 9, 6.2),
      line(15, 3.2, 15, 6.2),
      rect(6.4, 6.2, 11.2, 8.6, 2.4),
      line(12, 14.8, 12, 21.6),
      line(8.6, 21.6, 15.4, 21.6, true),
    ],
    'admin-security': [
      path('M12 2.8l7.4 3.1v6.3c0 4.7-3.1 8.2-7.4 9.6-4.3-1.4-7.4-4.9-7.4-9.6V5.9z'),
      path('M8.8 12.2l2.4 2.4 4.4-4.4', true),
    ],
    'admin-advanced': [
      line(3.6, 7.4, 20.4, 7.4),
      line(3.6, 16.6, 20.4, 16.6),
      circle(9, 7.4, 2.2, true),
      circle(15.6, 16.6, 2.2, true),
    ],
  };

  const FALLBACK_KEY = 'chat';

  return {
    glyphs: Object.keys(GLYPHS),
    has: (key) => Object.prototype.hasOwnProperty.call(GLYPHS, key),
    get: (key, size) => svg(size || 16, GLYPHS[key] || GLYPHS[FALLBACK_KEY]),
  };
}
