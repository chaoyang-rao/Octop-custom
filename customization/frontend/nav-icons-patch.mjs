/**
 * Swap the sidebar glyphs for the "精工细线" set in the shipped shell chunk.
 *
 * The catalog comes from `buildLegacyNavSections`; four extra entries
 * (conversations / task-queue / account-connections / mobile-access) are cloned
 * from a sibling item and would otherwise inherit its icon, so their clones get
 * an explicit icon too.
 */

const ICON_ENTRY = /(\{key:"([a-z-]+)",path:[^,]*,icon:)jsxRuntimeExports\.jsx\(\w+,\{size:iconSize,strokeWidth:iconStroke\}\)/g;

const CLONE_ICONS = [
  ['{...chat,key:"conversations",path:"/conversations",labelKey:"nav.conversations"}',
    '{...chat,key:"conversations",path:"/conversations",labelKey:"nav.conversations",icon:navIcons.get("conversations")}'],
  ['{...task,key:"task-queue",path:"/task-queue",labelKey:"nav.taskQueue"}',
    '{...task,key:"task-queue",path:"/task-queue",labelKey:"nav.taskQueue",icon:navIcons.get("task-queue")}'],
  ['{...connector,key:"account-connections",path:"/account-connections",labelKey:"nav.accountConnections"}',
    '{...connector,key:"account-connections",path:"/account-connections",labelKey:"nav.accountConnections",icon:navIcons.get("account-connections")}'],
  ['{...bridge,key:"mobile-access",path:"/mobile-access",labelKey:"nav.mobileAccess"}',
    '{...bridge,key:"mobile-access",path:"/mobile-access",labelKey:"nav.mobileAccess",icon:navIcons.get("mobile-access")}'],
];

export function patchNavIconsSource(source) {
  if (source.includes('navIcons.get(')) throw new Error('Sidebar icon patch was already applied');
  let replaced = 0;
  let out = source.replace(ICON_ENTRY, (_match, prefix, key) => {
    replaced += 1;
    return `${prefix}navIcons.get("${key}")`;
  });
  if (replaced !== 19) throw new Error(`Expected 19 sidebar icons, rewrote ${replaced}`);

  for (const [before, after] of CLONE_ICONS) {
    const count = out.split(before).length - 1;
    if (count !== 1) throw new Error(`Sidebar clone anchor expected once, found ${count}: ${before.slice(0, 60)}`);
    out = out.replace(before, after);
  }

  out = 'import {createNavIcons} from "./nav-icons.js";\n' + out;
  // Module scope: the clone entries live in buildNavSections, a *different*
  // function from buildLegacyNavSections, so a function-local const would not be
  // visible there (runtime "Can't find variable: navIcons").
  const reactImport = 'from"./vendor-react.';
  const importAt = out.indexOf(reactImport);
  if (importAt < 0) throw new Error('React import anchor changed');
  const importEnd = out.indexOf(';', importAt) + 1;
  if (importEnd <= 0) throw new Error('React import terminator changed');
  out = `${out.slice(0, importEnd)}const navIcons=createNavIcons({React:reactExports});${out.slice(importEnd)}`;
  if (out.indexOf('const navIcons=') > out.indexOf('navIcons.get(')) {
    throw new Error('Sidebar icon helper must be declared before its uses');
  }
  return out;
}
