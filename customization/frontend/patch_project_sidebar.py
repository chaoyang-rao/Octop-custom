"""Rebuild the Octop 1.0.2 project sidebar integration from its saved baseline.

All JS/CSS files get a release suffix so cached lazy chunks cannot load a second
copy of the old application's state module. Existing assets are left in place.
The app's pre-existing desktop SSO changes are preserved from the backup.
"""
from pathlib import Path
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'baselines' / 'original' / 'octop' / 'dashboard'
DASH = ROOT / 'packages' / 'octop' / 'dashboard'
ASSETS = DASH / 'assets'
MAIN = 'index.BsYGCvv_.js'
RELEASE = 'projects-v2'


def replace_once(text, old, new):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f'Expected one patch point, got {count}: {old[:100]}')
    return text.replace(old, new, 1)


s = (BASE / 'assets' / MAIN).read_text()
s = 'import {createProjectFolders} from "./project-folders.js";\n' + s
s = replace_once(s, 'threadId:row2.thread_id,updatedAt:',
    'threadId:row2.thread_id,projectPath:row2.project_path??null,projectName:row2.project_name??null,updatedAt:')

# Original rows keep their rename / delete / fork / pin behavior and receive one
# extra menu item from the project component. Both layout variants are covered.
for marker, end in [('const SessionItem=', 'function ActiveAgentCard'),
                    ('const PreviewSessionRow=', 'function MinimalAgentSessionNav')]:
    a, b = s.index(marker), s.index(end, s.index(marker))
    block = s[a:b]
    block = replace_once(block, 'forkDisabled,forkDisabledHint})',
        'forkDisabled,forkDisabledHint,projectMenuItems=[]})')
    block = replace_once(block, '},{key:"delete",label:', '},...projectMenuItems,{key:"delete",label:')
    s = s[:a] + block + s[b:]

factory = '''const ProjectSessionList=createProjectFolders({React:reactExports,request,toSession,sortSessions,Row:SessionItem,CompactRow:()=>PreviewSessionRow,resolveStatus:resolveSessionWorkStatus,emitSessionEvent,onSessionEvent,Dropdown,Plus,More:Ellipsis,Chevron:ChevronRight});'''
s = replace_once(s, 'function ActiveAgentCard(', factory + 'function ActiveAgentCard(')

a, b = s.index('function ActiveAgentCard('), s.index('function InactiveAgentRow(')
block = s[a:b]
cut = block.index('jsxRuntimeExports.jsx("div",{className:chatStyles.agentCardSessions,children:')
assert block.endswith(']})}')
block = block[:cut] + '''jsxRuntimeExports.jsx("div",{className:chatStyles.agentCardSessions,children:jsxRuntimeExports.jsx(ProjectSessionList,{agent,sessions,activeId,searchQuery,onSelect,onDelete,onRename,onPin,onFork,activeForkDisabled,activeForkDisabledHint,liveWorkingIds})})]})}'''
s = s[:a] + block + s[b:]

a, b = s.index('function MinimalAgentSessionNav('), s.index('const edge="RailEdgeControl')
block = s[a:b]
cut = block.index('expanded?jsxRuntimeExports.jsx("div",{className:chatStyles.minimalAgentSessions,children:')
block = block[:cut] + '''expanded?jsxRuntimeExports.jsx("div",{className:chatStyles.minimalAgentSessions,children:jsxRuntimeExports.jsx(ProjectSessionList,{agent,sessions:list2,activeId,searchQuery,onSelect,onDelete:(id,compact)=>handleDelete(agent.agent_id,id,compact),onRename:(id,name)=>handleRename(agent.agent_id,id,name),onPin:(id,pinned)=>handlePin(agent.agent_id,id,pinned),onFork,activeForkDisabled,activeForkDisabledHint,liveWorkingIds,compact:!0})}):null]},agent.agent_id)})]})}'''
s = s[:a] + block + s[b:]

for old in ('sessionsFor(agent.agent_id).map(session=>session.name)', 'own.map(session=>session.name)'):
    s = replace_once(s, old, old.replace('session.name)', '`${session.name} ${session.projectName||""} ${session.projectPath||""}`)'))

sources = {p.name: p.read_text() for p in (BASE / 'assets').iterdir()
    if p.suffix in ('.js', '.css')}
sources[MAIN] = s
for name in ('project-folders.js', 'project-folders.css'):
    sources[name] = (ASSETS / name).read_text()
mapping = {name: f'{Path(name).stem}.{RELEASE}{Path(name).suffix}' for name in sources}
pattern = re.compile('|'.join(re.escape(name) for name in sorted(mapping, key=len, reverse=True)))
rewrite = lambda text: pattern.sub(lambda match: mapping[match.group()], text)
for name, content in sources.items():
    (ASSETS / mapping[name]).write_text(rewrite(content))

html = (BASE / 'index.html').read_text()
html = html.replace('</head>', '    <link rel="stylesheet" href="/assets/project-folders.css">\n  </head>')
(DASH / 'index.html').write_text(rewrite(html))
sw = rewrite((BASE / 'sw.js').read_text())
(DASH / 'sw.js').write_text(f'/* Project folders release {RELEASE}. */\n' + sw)
(ROOT / 'frontend' / 'asset-release.json').write_text(json.dumps({
    'release': RELEASE, 'main': mapping[MAIN], 'assets': list(mapping.values()),
    'baseline_main_sha256': hashlib.sha256((BASE / 'assets' / MAIN).read_bytes()).hexdigest(),
}, indent=2))
print(f'Prepared {len(mapping)} versioned assets, entry {mapping[MAIN]}')
