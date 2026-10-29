/** Visible global navigation toggle; state remains owned by Octop MainLayout. */
export function createDockCollapseUi({ React }) {
  const h = React.createElement;
  return function DockCollapseToggle({ collapsed, onToggle }) {
    const label = collapsed ? '展开导航' : '收起导航';
    return h('div', { className: 'octop-dock-toggle-row' },
      h('button', {
        type: 'button', onClick: onToggle,
        className: `octop-dock-toggle${collapsed ? ' is-collapsed' : ''}`,
        'aria-label': label, 'aria-expanded': !collapsed,
        'aria-controls': 'octop-global-dock', title: label,
      }, h('svg', { width: 16, height: 16, viewBox: '0 0 24 24', fill: 'none',
        stroke: 'currentColor', strokeWidth: 1.7, strokeLinecap: 'round', strokeLinejoin: 'round',
        'aria-hidden': true, focusable: 'false' },
        h('rect', { x: 3, y: 3, width: 18, height: 18, rx: 3 }),
        h('path', { d: 'M9 3v18' }),
        h('path', { d: collapsed ? 'm13 8 4 4-4 4' : 'm17 8-4 4 4 4' })),
      collapsed ? null : h('span', null, label)));
  };
}
