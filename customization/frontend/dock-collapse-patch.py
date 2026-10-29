"""Pure, narrowly scoped patch for Octop's existing global navigation state.

Run after the existing main-module customizations. Do not change the shared
avatar builder here: the parent release assembles this patch with its others.
"""
EXTRA_ASSETS = ('dock-collapse.js', 'dock-collapse.css')
STYLESHEETS = ('dock-collapse.css',)


def _once(source, old, new):
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f'Expected one dock patch point, found {count}: {old[:100]}')
    return source.replace(old, new, 1)


def patch_dock_collapse(source):
    source = 'import {createDockCollapseUi} from "./dock-collapse.js";\n' + source
    source = _once(source, 'function Sidebar({selectedKey,collapsed,onToggle,isMobile}){',
        'const DockCollapseToggle=createDockCollapseUi({React:reactExports});function Sidebar({selectedKey,collapsed,onToggle,isMobile}){')

    # Desktop branch only: the mobile navigation keeps its existing drawer and
    # close action. This is the application dock, not the chat-history panel.
    source = _once(source,
        ':jsxRuntimeExports.jsxs("div",{style:{width:isRailCollapsed?COLLAPSED_WIDTH:EXPANDED_WIDTH,minWidth:isRailCollapsed?COLLAPSED_WIDTH:EXPANDED_WIDTH,',
        ':jsxRuntimeExports.jsxs("div",{id:"octop-global-dock","data-dock-collapsed":isRailCollapsed?"true":"false",style:{width:isRailCollapsed?COLLAPSED_WIDTH:EXPANDED_WIDTH,minWidth:isRailCollapsed?COLLAPSED_WIDTH:EXPANDED_WIDTH,')
    source = _once(source,
        'children:brandInner}),jsxRuntimeExports.jsx("div",{style:{flex:1,minHeight:0,overflowY:isMinimal&&minimalPane==="records"?"hidden":"auto",',
        'children:brandInner}),jsxRuntimeExports.jsx(DockCollapseToggle,{collapsed:isRailCollapsed,onToggle}),jsxRuntimeExports.jsx("div",{style:{flex:1,minHeight:0,overflowY:isMinimal&&minimalPane==="records"?"hidden":"auto",')

    # Keep icon-only links named for keyboard and screen-reader navigation.
    start = source.index('function SidebarCollapsedIconNav(')
    end = source.index('function SidebarMinimalPaneToggle(', start)
    nav = source[start:end]
    nav = _once(nav, 'type:"button",onClick:()=>onNavigate(item.path),',
        'type:"button","aria-label":t(item.labelKey),"aria-current":active2?"page":void 0,onClick:()=>onNavigate(item.path),')
    source = source[:start] + nav + source[end:]

    # The visible toggle already uses MainLayout's persistent onToggle. Make the
    # pre-existing keyboard/event route use that same persistence function too.
    source = _once(source,
        'reactExports.useEffect(()=>{const handler=()=>setCollapsed(prev=>!prev);return window.addEventListener("octop:toggle-nav",handler),()=>window.removeEventListener("octop:toggle-nav",handler)},[])',
        'reactExports.useEffect(()=>{const handler=()=>{persistNavCollapsed(!collapsed)};return window.addEventListener("octop:toggle-nav",handler),()=>window.removeEventListener("octop:toggle-nav",handler)},[collapsed,persistNavCollapsed])')
    return source


if __name__ == '__main__':
    import argparse
    from pathlib import Path
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.write_text(patch_dock_collapse(args.input.read_text()))
